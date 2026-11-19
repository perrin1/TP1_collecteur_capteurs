

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from collecteur import __version__
from collecteur.collecte import Collecteur, construire_referentiel, construire_sources
from collecteur.erreurs import CollecteError
from collecteur.file_attente import FileHorsLigne, RequeteDifferee
from collecteur.journalisation import JournalCollecte, configurer_journal
from collecteur.reseau import PolitiqueRetry
from collecteur.sources import LecteurAPI
from collecteur.stockage import Entrepot
from collecteur.validation import Validateur

__all__ = ["construire_analyseur", "main"]

_journal: Final = logging.getLogger(__name__)

_SOURCES_PAR_DEFAUT: Final = "A,B,C"




def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="collecteur",
        description="Collecte, normalise et stocke les relevés de capteurs agricoles.",
    )
    analyseur.add_argument("--version", action="version", version=f"collecteur {__version__}")

    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--base", type=Path, default=Path("collecte.db"), help="base SQLite")
    commun.add_argument(
        "--verbeux",
        "-v",
        action="count",
        default=0,
        help="-v pour le détail, -vv pour le diagnostic complet",
    )
    commun.add_argument("--journal", type=Path, default=None, help="fichier de journal JSON")
    commun.add_argument(
        "--format-journal",
        choices=("texte", "json"),
        default="texte",
        help="format du journal affiché à l'écran",
    )

    sous = analyseur.add_subparsers(dest="commande", required=True)

    collecter = sous.add_parser(
        "collecter", parents=[commun], help="lit les sources et stocke les relevés"
    )
    collecter.add_argument(
        "--source",
        default=_SOURCES_PAR_DEFAUT,
        help="sources à lire, séparées par des virgules (défaut : A,B,C)",
    )
    collecter.add_argument(
        "--depuis",
        type=_date,
        default=None,
        help="ne garder que les relevés à partir de cette date (AAAA-MM-JJ)",
    )
    collecter.add_argument("--donnees", type=Path, default=Path("data"), help="dossier des sources")
    collecter.add_argument("--url", default="http://127.0.0.1:8777", help="URL de la station C")
    collecter.add_argument(
        "--tentatives", type=int, default=5, help="nombre maximal de tentatives par page"
    )
    collecter.add_argument(
        "--delai-initial", type=float, default=1.0, help="premier délai de reprise, en secondes"
    )

    sous.add_parser("statut", parents=[commun], help="affiche l'état de la base et de la file")

    rejouer = sous.add_parser(
        "rejouer-file", parents=[commun], help="rejoue les requêtes mises de côté"
    )
    rejouer.add_argument("--url", default="http://127.0.0.1:8777", help="URL de la station C")

    return analyseur


def _date(texte: str) -> datetime:
    try:
        date = datetime.fromisoformat(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"date illisible : {texte!r} (attendu AAAA-MM-JJ)"
        ) from None
    return date if date.tzinfo else date.replace(tzinfo=UTC)



def commande_collecter(arguments: argparse.Namespace) -> int:
    noms = [nom.strip().upper() for nom in str(arguments.source).split(",") if nom.strip()]
    politique = PolitiqueRetry(
        tentatives_max=arguments.tentatives,
        delai_initial_s=arguments.delai_initial,
    )

    sources = construire_sources(
        racine_donnees=arguments.donnees, url_api=arguments.url, noms=noms
    )
    if not sources:
        print(f"Aucune source reconnue dans {arguments.source!r}", file=sys.stderr)
        return 2

    for source in sources:
        if isinstance(source, LecteurAPI):
            source.politique = politique

    api = next((s for s in sources if isinstance(s, LecteurAPI)), None)
    referentiel = construire_referentiel(arguments.donnees, api=api)

    with Entrepot(arguments.base) as entrepot:
        collecteur = Collecteur(
            entrepot=entrepot,
            validateur=Validateur(referentiel=referentiel),
            journal=JournalCollecte(logging.getLogger("collecteur")),
            depuis=arguments.depuis,
        )

        resultats = collecteur.collecter(sources)

        print(f"\nBase : {arguments.base}  ({entrepot.compter()} relevés)")
        _tableau(
            ["source", "lus", "émis", "rejetés", "doublons", "reprises", "insérés", "déjà vus"],
            [
                [
                    r.source,
                    r.lus,
                    r.emis,
                    r.rejetes,
                    r.dupliques,
                    r.retentes,
                    r.inseres,
                    r.deja_vus,
                ]
                for r in resultats
            ],
        )

        differees = sum(r.pages_differees for r in resultats)
        if differees:
            print(f"\n{differees} requête(s) mise(s) en file. `collecteur rejouer-file` les reprendra.")

        echecs = [r for r in resultats if r.statut != "ok"]
        for echec in echecs:
            print(f"  ÉCHEC {echec.source} : {echec.erreur}", file=sys.stderr)
        return 1 if echecs else 0


def commande_statut(arguments: argparse.Namespace) -> int:
    if not Path(arguments.base).exists():
        print(f"Aucune base à {arguments.base}. Lancez `collecteur collecter`.")
        return 1

    with Entrepot(arguments.base) as entrepot:
        print(f"Base : {arguments.base}  ({entrepot.compter()} relevés)\n")

        _tableau(
            ["source", "relevés", "dernier relevé"],
            [
                [source, nombre, _horodatage(entrepot.derniere_collecte(source))]
                for source, nombre in entrepot.comptes_par_source().items()
            ],
        )

        print()
        _tableau(
            ["qualité", "relevés"],
            [[qualite, nombre] for qualite, nombre in entrepot.comptes_par_qualite().items()],
        )

        series = entrepot.series_bloquees_sql()
        if series:
            print(f"\n{len(series)} série(s) de capteur bloqué, la plus longue de "
                  f"{max(n for _, _, n in series)} relevés.")

        lignes = list(
            entrepot.connexion.execute(
                "SELECT source, finie_le, lus, inseres, deja_vus, rejetes, retentes "
                "FROM collectes ORDER BY id DESC LIMIT 5"
            )
        )
        if lignes:
            print("\nCinq dernières collectes :")
            _tableau(
                ["source", "terminée", "lus", "insérés", "déjà vus", "rejetés", "reprises"],
                [
                    [
                        ligne["source"],
                        str(ligne["finie_le"])[:19],
                        ligne["lus"],
                        ligne["inseres"],
                        ligne["deja_vus"],
                        ligne["rejetes"],
                        ligne["retentes"],
                    ]
                    for ligne in lignes
                ],
            )

    file = FileHorsLigne()
    en_attente = list(file)
    print(f"\nFile hors-ligne : {len(en_attente)} requête(s) en attente")
    for requete in en_attente[:10]:
        print(f"  {requete.source} {requete.cible} {requete.parametres} — {requete.motif}")
    return 0


def commande_rejouer(arguments: argparse.Namespace) -> int:
    file = FileHorsLigne()
    en_attente = list(file.rejouer())
    if not en_attente:
        print("File vide, rien à rejouer.")
        return 0

    print(f"{len(en_attente)} requête(s) à rejouer.")
    lecteur = LecteurAPI(arguments.url)
    pages = [_page(requete) for requete in en_attente if requete.source == "C"]
    pages = [page for page in pages if page is not None]

    with Entrepot(arguments.base) as entrepot:
        try:
            resultat = entrepot.enregistrer(lecteur.lire_pages([p for p in pages if p is not None]))
        except CollecteError as erreur:
            print(f"Rejeu interrompu : {erreur}", file=sys.stderr)
            _reempiler(file, en_attente)
            return 1

    print(f"Rejeu terminé : {resultat.resume()}")

    # Les pages toujours indisponibles retournent en file, compteur incrémenté.
    restantes = [
        RequeteDifferee(
            source=requete.source,
            cible=requete.cible,
            parametres=requete.parametres,
            motif=requete.motif,
            tentatives=requete.tentatives + 1,
        )
        for requete in en_attente
        if _page(requete) in lecteur.pages_abandonnees
    ]
    _reempiler(file, restantes)
    if restantes:
        print(f"{len(restantes)} requête(s) toujours en échec, remises en file.")
    return 0


def _reempiler(file: FileHorsLigne, requetes: Sequence[RequeteDifferee]) -> None:
    for requete in requetes:
        file.empiler(requete)


def _page(requete: RequeteDifferee) -> int | None:
    valeur = requete.parametres.get("page")
    return valeur if isinstance(valeur, int) else None


def _tableau(entetes: Sequence[str], lignes: Sequence[Sequence[object]]) -> None:
    if not lignes:
        return
    colonnes = [
        max(len(str(entetes[i])), *(len(str(ligne[i])) for ligne in lignes))
        for i in range(len(entetes))
    ]
    separateur = "  "
    print(separateur.join(str(e).ljust(largeur) for e, largeur in zip(entetes, colonnes, strict=True)))
    print(separateur.join("-" * largeur for largeur in colonnes))
    for ligne in lignes:
        print(
            separateur.join(
                str(valeur).ljust(largeur)
                for valeur, largeur in zip(ligne, colonnes, strict=True)
            )
        )


def _horodatage(instant: datetime | None) -> str:
    return instant.isoformat(timespec="minutes") if instant else "—"




def main(argv: Sequence[str] | None = None) -> int:
    arguments = construire_analyseur().parse_args(argv)

    niveaux = {0: logging.WARNING, 1: logging.INFO}
    configurer_journal(
        niveau=niveaux.get(arguments.verbeux, logging.DEBUG),
        fichier=arguments.journal,
        format_console=arguments.format_journal,
    )

    commandes = {
        "collecter": commande_collecter,
        "statut": commande_statut,
        "rejouer-file": commande_rejouer,
    }

    try:
        return commandes[arguments.commande](arguments)
    except CollecteError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        _journal.debug("détail", exc_info=True)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompu. Les relevés déjà écrits sont conservés.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
