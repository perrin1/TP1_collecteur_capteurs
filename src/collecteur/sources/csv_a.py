
from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final

from collecteur.domaine import Qualite, Releve
from collecteur.erreurs import PayloadInvalide, ReleveIncoherent
from collecteur.normalisation import normaliser_unite, parser_horodatage
from collecteur.sources.base import SourceReleves, StatistiquesLecture

__all__ = ["LecteurCSV"]

_journal: Final = logging.getLogger(__name__)

#: Entêtes attendues, une fois la casse normalisée.
_COLONNES_REQUISES: Final[frozenset[str]] = frozenset(
    {"releve_id", "station", "date_heure", "grandeur", "valeur", "unite"}
)


class LecteurCSV:

    nom = "A"

    def __init__(self, chemin: Path | str, *, delimiteur: str = ";") -> None:
        self.chemin: Path = Path(chemin)
        self.delimiteur: str = delimiteur
        self.statistiques: StatistiquesLecture = StatistiquesLecture(source=self.nom)

    def lire(self) -> Iterator[Releve]:
        if not self.chemin.exists():
            raise PayloadInvalide(
                self.nom,
                raison="Fichier introuvable",
                apercu=str(self.chemin),
            )

        with self.chemin.open(encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.DictReader(fichier, delimiter=self.delimiteur)
            if lecteur.fieldnames is None:
                raise PayloadInvalide(self.nom, raison="Fichier vide")

            colonnes = {nom: _canon(nom) for nom in lecteur.fieldnames}
            manquantes = _COLONNES_REQUISES - set(colonnes.values())
            if manquantes:
                raise PayloadInvalide(
                    self.nom,
                    raison=f"Colonnes manquantes : {sorted(manquantes)}",
                    apercu=str(lecteur.fieldnames),
                )

            vus: set[str] = set()

            for ligne in lecteur:
                self.statistiques.lus += 1
                brut = {colonnes[cle]: (valeur or "") for cle, valeur in ligne.items() if cle in colonnes}

                try:
                    releve = self._construire(brut)
                except ReleveIncoherent as erreur:
                    self.statistiques.rejeter(erreur.raison)
                    _journal.debug("ligne rejetée : %s", erreur)
                    continue
                except (ValueError, KeyError) as erreur:
                    self.statistiques.rejeter(type(erreur).__name__)
                    _journal.debug("ligne illisible : %s", erreur)
                    continue

                if releve.releve_id in vus:
                    self.statistiques.dupliques += 1
                else:
                    vus.add(releve.releve_id)

                self.statistiques.emis += 1
                yield releve

    def _construire(self, brut: dict[str, str]) -> Releve:
        releve_id = brut["releve_id"].strip()

        horodatage = parser_horodatage(
            brut["date_heure"],
            releve_id=releve_id,
            source=self.nom,
        )

        # Les deux espaces retires sont differents : U+202F, espace fine insecable,
        # sert de separateur de milliers dans certains exports.
        valeur_texte = brut["valeur"].strip().replace(" ", "").replace(" ", "")  # noqa: RUF001
        try:
            valeur_brute = float(valeur_texte.replace(",", "."))
        except ValueError:
            raise ReleveIncoherent(
                "Valeur numérique illisible",
                champ="valeur",
                valeur=brut["valeur"],
                releve_id=releve_id,
                source=self.nom,
            ) from None

        valeur, unite = normaliser_unite(
            valeur_brute,
            brut["unite"],
            releve_id=releve_id,
            source=self.nom,
        )
        if unite != brut["unite"].strip():
            self.statistiques.unites_converties += 1

        return Releve.creer(
            releve_id=releve_id,
            station=brut["station"],
            horodatage=horodatage,
            grandeur=brut["grandeur"],
            valeur=valeur,
            unite=unite,
            qualite=Qualite.VALIDE,
            source=self.nom,
        )

    def __repr__(self) -> str:
        return f"LecteurCSV({self.chemin.name!r})"


def _canon(entete: str) -> str:
    return entete.replace("﻿", "").strip().lower()


if TYPE_CHECKING:

    def _conforme(lecteur: LecteurCSV) -> SourceReleves:
        return lecteur
