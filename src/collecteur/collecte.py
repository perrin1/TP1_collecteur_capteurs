
from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from collecteur.domaine import Releve
from collecteur.erreurs import CollecteError
from collecteur.file_attente import FileHorsLigne, RequeteDifferee
from collecteur.journalisation import JournalCollecte
from collecteur.referentiel import Referentiel
from collecteur.sources import LecteurAPI, LecteurCSV, LecteurJSON, SourceReleves
from collecteur.stockage import Entrepot, ResultatEcriture
from collecteur.validation import RapportValidation, Validateur, marquer_capteurs_bloques

__all__ = ["Collecteur", "ResultatCollecte", "construire_sources"]

_journal: Final = logging.getLogger(__name__)


@dataclass(slots=True)
class ResultatCollecte:
    """Bilan d'une exécution, par source."""

    source: str
    lus: int = 0
    emis: int = 0
    rejetes: int = 0
    dupliques: int = 0
    retentes: int = 0
    inseres: int = 0
    deja_vus: int = 0
    pages_differees: int = 0
    statut: str = "ok"
    erreur: str | None = None

    def compteurs(self) -> dict[str, int]:
        return {
            "lus": self.lus,
            "emis": self.emis,
            "rejetes": self.rejetes,
            "dupliques": self.dupliques,
            "retentes": self.retentes,
            "inseres": self.inseres,
            "deja_vus": self.deja_vus,
            "pages_differees": self.pages_differees,
        }


@dataclass(slots=True)
class Collecteur:

    entrepot: Entrepot
    validateur: Validateur = field(default_factory=Validateur)
    file: FileHorsLigne = field(default_factory=FileHorsLigne)
    journal: JournalCollecte = field(
        default_factory=lambda: JournalCollecte(logging.getLogger("collecteur"))
    )
    depuis: datetime | None = None

    def collecter(self, sources: Sequence[SourceReleves]) -> list[ResultatCollecte]:
        resultats = [self.collecter_une(source) for source in sources]
        self._appliquer_series_bloquees()
        return resultats

    def collecter_une(self, source: SourceReleves) -> ResultatCollecte:
        debut = self.journal.debut(source.nom, str(source))
        resultat = ResultatCollecte(source=source.nom)

        try:
            ecriture = self.entrepot.enregistrer(self._flux(source))
        except CollecteError as erreur:
            resultat.statut = "echec"
            resultat.erreur = str(erreur)
            self.journal.incident(source.nom, "collecte interrompue", detail=str(erreur))
            _journal.exception("collecte de la source %s interrompue", source.nom)
            ecriture = ResultatEcriture()

        self._reporter(resultat, source, ecriture)

        self.entrepot.journaliser_collecte(
            source.nom,
            demarree_le=debut,
            lus=resultat.lus,
            inseres=resultat.inseres,
            deja_vus=resultat.deja_vus,
            rejetes=resultat.rejetes,
            retentes=resultat.retentes,
        )
        self.journal.fin(
            source.nom,
            demarree_le=debut,
            compteurs=resultat.compteurs(),
            statut=resultat.statut,
        )
        return resultat


    def _flux(self, source: SourceReleves) -> Iterator[Releve]:
        flux = source.lire()
        if self.depuis is not None:
            seuil = self.depuis
            flux = (releve for releve in flux if releve.horodatage >= seuil)
        return self.validateur.valider(flux)

    def _reporter(
        self,
        resultat: ResultatCollecte,
        source: SourceReleves,
        ecriture: ResultatEcriture,
    ) -> None:
        stats = source.statistiques
        resultat.lus = stats.lus
        resultat.emis = stats.emis
        resultat.rejetes = stats.rejetes
        resultat.dupliques = stats.dupliques
        resultat.retentes = stats.retentes
        resultat.inseres = ecriture.inseres
        resultat.deja_vus = ecriture.deja_vus + ecriture.mis_a_jour

        pages = getattr(source, "pages_abandonnees", [])
        for page in pages:
            empilee = self.file.empiler(
                RequeteDifferee(
                    source=source.nom,
                    cible="/releves",
                    parametres={"page": int(page)},
                    motif="tentatives épuisées",
                )
            )
            if empilee:
                resultat.pages_differees += 1

    def _appliquer_series_bloquees(self) -> None:
        series = self.entrepot.series_bloquees_sql()
        if not series:
            return

        marques = self.entrepot.marquer_series_bloquees()
        self.validateur.rapport.series_bloquees = len(series)
        self.validateur.rapport.plus_longue_serie = max(n for _, _, n in series)
        _journal.info("%d relevés marqués suspects par %d série(s)", marques, len(series))

    def rapport_validation(self) -> RapportValidation:
        return self.validateur.rapport


def construire_sources(
    *,
    racine_donnees: Path | str = "data",
    url_api: str = "http://127.0.0.1:8777",
    noms: Sequence[str] = ("A", "B", "C"),
) -> list[SourceReleves]:
    racine = Path(racine_donnees)
    disponibles: dict[str, SourceReleves] = {
        "A": LecteurCSV(racine / "station_A_releves.csv"),
        "B": LecteurJSON(racine / "station_B_releves.json"),
        "C": LecteurAPI(url_api),
    }
    return [disponibles[nom.upper()] for nom in noms if nom.upper() in disponibles]


def construire_referentiel(
    racine_donnees: Path | str = "data",
    *,
    api: LecteurAPI | None = None,
) -> Referentiel:
    referentiel = Referentiel.depuis_csv(Path(racine_donnees) / "stations_reference.csv")
    if api is not None:
        try:
            ajoutees = referentiel.ajouter_depuis_api(api.stations())
            _journal.info("%d station(s) ajoutée(s) depuis l'API", ajoutees)
        except CollecteError as erreur:
            _journal.warning("référentiel API indisponible : %s", erreur)
    return referentiel


def maintenant_utc() -> datetime:
    return datetime.now(UTC)


__all__ += ["construire_referentiel", "marquer_capteurs_bloques"]
