

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from collecteur.erreurs import PayloadInvalide

__all__ = ["Referentiel", "Station"]

_journal: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Station:
    """Une station connue du référentiel."""

    code: str
    commune: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None


class Referentiel:


    def __init__(self, stations: Iterable[Station] = ()) -> None:
        self._stations: dict[str, Station] = {s.code.upper(): s for s in stations}
        #: Codes rencontrés dans les relevés sans exister au référentiel.
        self.inconnues: set[str] = set()

    # -- chargement

    @classmethod
    def depuis_csv(cls, chemin: Path | str, *, delimiteur: str = ";") -> Referentiel:
        chemin = Path(chemin)
        if not chemin.exists():
            raise PayloadInvalide(
                "referentiel", raison="Fichier introuvable", apercu=str(chemin)
            )

        stations: list[Station] = []
        with chemin.open(encoding="utf-8-sig", newline="") as fichier:
            for ligne in csv.DictReader(fichier, delimiter=delimiteur):
                brut = {(cle or "").strip().lower(): (valeur or "") for cle, valeur in ligne.items()}
                code = brut.get("code_station", "").strip()
                if not code:
                    continue
                stations.append(
                    Station(
                        code=code.upper(),
                        commune=brut.get("commune", "").strip() or None,
                        latitude=_flottant(brut.get("latitude")),
                        longitude=_flottant(brut.get("longitude")),
                        altitude_m=_flottant(brut.get("altitude_m")),
                    )
                )
        return cls(stations)

    def ajouter_depuis_api(self, stations: Iterable[Mapping[str, object]]) -> int:

        avant = len(self._stations)
        for brut in stations:
            code = str(brut.get("code", "")).strip().upper()
            if not code:
                continue
            self._stations[code] = Station(
                code=code,
                commune=_texte(brut.get("commune")),
                latitude=_flottant(brut.get("lat")),
                longitude=_flottant(brut.get("lon")),
            )
        return len(self._stations) - avant

    # -- interrogation

    def connait(self, code: str) -> bool:

        normalise = code.strip().upper()
        if normalise in self._stations:
            return True
        self.inconnues.add(normalise)
        return False

    def station(self, code: str) -> Station | None:
        return self._stations.get(code.strip().upper())

    def __len__(self) -> int:
        return len(self._stations)

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code.strip().upper() in self._stations

    def __repr__(self) -> str:
        return f"Referentiel({len(self._stations)} stations)"


def _flottant(valeur: object) -> float | None:
    if valeur is None or valeur == "":
        return None
    try:
        return float(str(valeur).replace(",", "."))
    except ValueError:
        return None


def _texte(valeur: object) -> str | None:
    texte = str(valeur).strip() if valeur is not None else ""
    return texte or None
