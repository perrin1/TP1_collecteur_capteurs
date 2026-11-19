"""
Modèle du domaine  parties A1 et A2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from collecteur.erreurs import ReleveIncoherent

__all__ = [
    "GRANDEURS_PAR_UNITE_CANONIQUE",
    "PLAGES_PHYSIQUES",
    "SOURCES_CONNUES",
    "UNITES_CANONIQUES",
    "Grandeur",
    "Qualite",
    "Releve",
]


#  A2 Énumérations



class Grandeur(StrEnum):

    TEMPERATURE = "temperature"
    HUMIDITE_SOL = "humidite_sol"
    HUMIDITE_AIR = "humidite_air"
    PLUVIOMETRIE = "pluviometrie"
    CONDUCTIVITE = "conductivite"

    @classmethod
    def depuis_texte(cls, brut: str, *, source: str | None = None) -> Grandeur:

        nettoye = brut.replace("﻿", "").strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return cls(nettoye)
        except ValueError:
            raise ReleveIncoherent(
                "Grandeur inconnue",
                champ="grandeur",
                valeur=brut,
                source=source,
            ) from None


class Qualite(StrEnum):

    VALIDE = "valide"
    SUSPECTE = "suspecte"
    REJETE = "rejete"

#  Constantes du domaine

UNITES_CANONIQUES: Final[frozenset[str]] = frozenset({"degC", "pct", "mm", "dS_m"})


GRANDEURS_PAR_UNITE_CANONIQUE: Final[Mapping[Grandeur, str]] = {
    Grandeur.TEMPERATURE: "degC",
    Grandeur.HUMIDITE_SOL: "pct",
    Grandeur.HUMIDITE_AIR: "pct",
    Grandeur.PLUVIOMETRIE: "mm",
    Grandeur.CONDUCTIVITE: "dS_m",
}


PLAGES_PHYSIQUES: Final[Mapping[Grandeur, tuple[float, float]]] = {
    Grandeur.TEMPERATURE: (-10.0, 60.0),
    Grandeur.HUMIDITE_SOL: (0.0, 100.0),
    Grandeur.HUMIDITE_AIR: (0.0, 100.0),
    Grandeur.PLUVIOMETRIE: (0.0, 500.0),
    Grandeur.CONDUCTIVITE: (0.0, 20.0),
}

SOURCES_CONNUES: Final[frozenset[str]] = frozenset({"A", "B", "C"})

#  A1  Le relevé normalisé

@dataclass(frozen=True, slots=True)
class Releve:


    releve_id: str
    station: str
    horodatage: datetime
    grandeur: Grandeur
    valeur: float
    unite: str
    qualite: Qualite
    source: str

    # -- invariantes

    def __post_init__(self) -> None:
        if not self.releve_id or not self.releve_id.strip():
            raise ReleveIncoherent(
                "Identifiant de relevé vide",
                champ="releve_id",
                valeur=self.releve_id,
                source=self.source,
            )

        if not self.station or not self.station.strip():
            raise ReleveIncoherent(
                "Code station vide",
                champ="station",
                valeur=self.station,
                releve_id=self.releve_id,
                source=self.source,
            )

        if self.station != self.station.upper():
            raise ReleveIncoherent(
                "Code station attendu en majuscules",
                champ="station",
                valeur=self.station,
                releve_id=self.releve_id,
                source=self.source,
            )

        if not isinstance(self.horodatage, datetime):
            raise ReleveIncoherent(
                "Horodatage absent ou non daté",
                champ="horodatage",
                valeur=self.horodatage,
                releve_id=self.releve_id,
                source=self.source,
            )

        if self.horodatage.tzinfo is None or self.horodatage.utcoffset() is None:
            raise ReleveIncoherent(
                "Horodatage naïf : fuseau horaire absent",
                champ="horodatage",
                valeur=self.horodatage.isoformat(),
                releve_id=self.releve_id,
                source=self.source,
            )

        if self.horodatage.utcoffset() != UTC.utcoffset(None):
            raise ReleveIncoherent(
                "Horodatage non converti en UTC",
                champ="horodatage",
                valeur=self.horodatage.isoformat(),
                releve_id=self.releve_id,
                source=self.source,
            )

        if not isinstance(self.grandeur, Grandeur):
            raise ReleveIncoherent(
                "Grandeur non normalisée",
                champ="grandeur",
                valeur=self.grandeur,
                releve_id=self.releve_id,
                source=self.source,
            )

        if not isinstance(self.qualite, Qualite):
            raise ReleveIncoherent(
                "Qualité non normalisée",
                champ="qualite",
                valeur=self.qualite,
                releve_id=self.releve_id,
                source=self.source,
            )

        if not math.isfinite(self.valeur):
            raise ReleveIncoherent(
                "Valeur non finie (NaN ou infinie)",
                champ="valeur",
                valeur=self.valeur,
                releve_id=self.releve_id,
                source=self.source,
            )

        if self.unite not in UNITES_CANONIQUES:
            raise ReleveIncoherent(
                "Unité non canonique",
                champ="unite",
                valeur=self.unite,
                releve_id=self.releve_id,
                source=self.source,
            )

        attendue = GRANDEURS_PAR_UNITE_CANONIQUE[self.grandeur]
        if self.unite != attendue:
            raise ReleveIncoherent(
                f"Unité incompatible avec la grandeur (attendu {attendue})",
                champ="unite",
                valeur=self.unite,
                releve_id=self.releve_id,
                source=self.source,
            )

        if self.source not in SOURCES_CONNUES:
            raise ReleveIncoherent(
                "Source inconnue",
                champ="source",
                valeur=self.source,
                releve_id=self.releve_id,
            )

    # -- construction

    @classmethod
    def creer(
        cls,
        *,
        releve_id: str,
        station: str,
        horodatage: datetime,
        grandeur: Grandeur | str,
        valeur: float,
        unite: str,
        source: str,
        qualite: Qualite = Qualite.VALIDE,
    ) -> Releve:

        if horodatage.tzinfo is None:
            raise ReleveIncoherent(
                "Horodatage naïf transmis à Releve.creer : le fuseau doit être "
                "déterminé par le lecteur",
                champ="horodatage",
                valeur=horodatage.isoformat(),
                releve_id=releve_id,
                source=source,
            )

        return cls(
            releve_id=releve_id.strip(),
            station=station.strip().upper(),
            horodatage=horodatage.astimezone(UTC),
            grandeur=(
                grandeur
                if isinstance(grandeur, Grandeur)
                else Grandeur.depuis_texte(grandeur, source=source)
            ),
            valeur=float(valeur),
            unite=unite,
            qualite=qualite,
            source=source.strip().upper(),
        )

    # -- transformations

    def avec_qualite(self, qualite: Qualite) -> Releve:

        return replace(self, qualite=qualite)

    def dans_la_plage(self) -> bool:

        bas, haut = PLAGES_PHYSIQUES[self.grandeur]
        return bas <= self.valeur <= haut

    # -- représentation

    def __str__(self) -> str:
        return (
            f"{self.releve_id} {self.station} "
            f"{self.horodatage:%Y-%m-%d %H:%M}Z "
            f"{self.grandeur}={self.valeur:g} {self.unite} "
            f"({self.qualite})"
        )
