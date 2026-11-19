

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from collecteur.domaine import Grandeur, Qualite, Releve
from collecteur.erreurs import ConfigurationInvalide, PayloadInvalide, ReleveIncoherent
from collecteur.normalisation import (
    fahrenheit_implicite,
    normaliser_unite,
    parser_horodatage,
)
from collecteur.sources.base import SourceReleves, StatistiquesLecture

__all__ = ["LecteurJSON"]

_journal: Final = logging.getLogger(__name__)

_TABLEAUX: Final[tuple[str, ...]] = ("mesures", "mesures_differees")

_TAILLE_TAMPON: Final[int] = 64 * 1024


class LecteurJSON:

    nom = "B"

    def __init__(
        self,
        chemin: Path | str,
        *,
        deduire_fahrenheit: bool = True,
    ) -> None:
        self.chemin: Path = Path(chemin)
        self.deduire_fahrenheit: bool = deduire_fahrenheit
        self.statistiques: StatistiquesLecture = StatistiquesLecture(source=self.nom)
        self._fuseaux: dict[str, ZoneInfo] = {}

    def lire(self) -> Iterator[Releve]:
        if not self.chemin.exists():
            raise PayloadInvalide(
                self.nom,
                raison="Fichier introuvable",
                apercu=str(self.chemin),
            )

        _verifier_base_de_fuseaux()
        vus: set[str] = set()

        for tableau in _TABLEAUX:
            for enregistrement in _objets_du_tableau(self.chemin, tableau, source=self.nom):
                self.statistiques.lus += 1
                try:
                    releve = self._construire(enregistrement)
                except ReleveIncoherent as erreur:
                    self.statistiques.rejeter(erreur.raison)
                    _journal.debug("relevé rejeté : %s", erreur)
                    continue
                except (KeyError, TypeError, ValueError) as erreur:
                    self.statistiques.rejeter(type(erreur).__name__)
                    _journal.debug("enregistrement illisible : %s", erreur)
                    continue

                if releve.releve_id in vus:
                    self.statistiques.dupliques += 1
                else:
                    vus.add(releve.releve_id)

                self.statistiques.emis += 1
                yield releve


    def _construire(self, enr: Mapping[str, object]) -> Releve:
        releve_id = str(enr["id"]).strip()
        station_brute = enr.get("station") or {}
        if not isinstance(station_brute, Mapping):
            raise ReleveIncoherent(
                "Bloc station absent ou mal formé",
                champ="station",
                valeur=station_brute,
                releve_id=releve_id,
                source=self.nom,
            )

        mesure = enr.get("mesure") or {}
        if not isinstance(mesure, Mapping):
            raise ReleveIncoherent(
                "Bloc mesure absent ou mal formé",
                champ="mesure",
                valeur=mesure,
                releve_id=releve_id,
                source=self.nom,
            )

        horodatage = parser_horodatage(
            str(enr["ts"]),
            fuseau_declare=self._fuseau(str(enr.get("fuseau", "UTC")), releve_id),
            releve_id=releve_id,
            source=self.nom,
        )

        grandeur = Grandeur.depuis_texte(str(mesure["type"]), source=self.nom)
        unite_brute = str(mesure["unite"])
        valeur, unite = normaliser_unite(
            float(mesure["valeur"]),
            unite_brute,
            releve_id=releve_id,
            source=self.nom,
        )
        if unite != unite_brute.strip():
            self.statistiques.unites_converties += 1

        if self.deduire_fahrenheit and fahrenheit_implicite(valeur, grandeur, unite):
            valeur = (valeur - 32.0) * 5.0 / 9.0
            self.statistiques.fahrenheit_deduits += 1

        return Releve.creer(
            releve_id=releve_id,
            station=str(station_brute["code"]),
            horodatage=horodatage,
            grandeur=grandeur,
            valeur=valeur,
            unite=unite,
            qualite=Qualite.VALIDE,
            source=self.nom,
        )

    def _fuseau(self, nom: str, releve_id: str) -> ZoneInfo:
        cle = nom.strip() or "UTC"
        fuseau = self._fuseaux.get(cle)
        if fuseau is not None:
            return fuseau

        try:
            fuseau = ZoneInfo(cle)
        except (ZoneInfoNotFoundError, ValueError):
            raise ReleveIncoherent(
                "Fuseau horaire déclaré inconnu",
                champ="fuseau",
                valeur=nom,
                releve_id=releve_id,
                source=self.nom,
            ) from None

        self._fuseaux[cle] = fuseau
        return fuseau

    def __repr__(self) -> str:
        return f"LecteurJSON({self.chemin.name!r})"




def _verifier_base_de_fuseaux() -> None:
    """Vérifie que la base de fuseaux est lisible, avant de lire quoi que ce soit.

    Sans cette vérification, l'absence de `tzdata` ne se traduit par aucune
    erreur visible : chaque relevé est rejeté séparément pour « fuseau
    inconnu », le compteur monte à 3 800 et la collecte se termine avec un
    statut « ok ». On perd un tiers du jeu de données sans que rien ne
    l'annonce — exactement le genre de panne que ce TP demande d'éviter.

    Échouer d'emblée, avec le nom du paquet à installer, coûte une ligne et
    épargne une heure de recherche.
    """
    try:
        ZoneInfo("Africa/Porto-Novo")
    except ZoneInfoNotFoundError:
        raise ConfigurationInvalide(
            "base de fuseaux horaires",
            valeur="introuvable",
            attendu="le paquet tzdata (python -m pip install tzdata)",
        ) from None


def _objets_du_tableau(
    chemin: Path,
    cle: str,
    *,
    source: str,
    taille_tampon: int = _TAILLE_TAMPON,
) -> Iterator[dict[str, object]]:
    decodeur = json.JSONDecoder()
    motif = f'"{cle}"'

    with chemin.open(encoding="utf-8") as fichier:
        tampon = ""

        position = -1
        while position < 0:
            morceau = fichier.read(taille_tampon)
            if not morceau:
                return
            tampon += morceau
            position = tampon.find(motif)
        tampon = tampon[position + len(motif) :]

        while "[" not in tampon:
            morceau = fichier.read(taille_tampon)
            if not morceau:
                raise PayloadInvalide(
                    source, raison=f"Tableau « {cle} » sans ouverture"
                )
            tampon += morceau
        tampon = tampon[tampon.index("[") + 1 :]


        while True:
            tampon = tampon.lstrip(" \t\r\n,")

            if tampon.startswith("]"):
                return

            if not tampon:
                morceau = fichier.read(taille_tampon)
                if not morceau:
                    raise PayloadInvalide(
                        source, raison=f"Tableau « {cle} » non refermé"
                    )
                tampon += morceau
                continue

            try:
                objet, fin = decodeur.raw_decode(tampon)
            except json.JSONDecodeError:
                morceau = fichier.read(taille_tampon)
                if not morceau:
                    raise PayloadInvalide(
                        source,
                        raison=f"JSON invalide dans « {cle} »",
                        octets_recus=len(tampon),
                        apercu=tampon,
                    ) from None
                tampon += morceau
                continue

            tampon = tampon[fin:]
            if isinstance(objet, dict):
                yield objet


if TYPE_CHECKING:

    def _conforme(lecteur: LecteurJSON) -> SourceReleves:
        return lecteur
