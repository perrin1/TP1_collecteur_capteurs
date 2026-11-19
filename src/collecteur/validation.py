

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from collecteur.domaine import PLAGES_PHYSIQUES, Qualite, Releve
from collecteur.referentiel import Referentiel

__all__ = [
    "Anomalie",
    "RapportValidation",
    "Validateur",
    "marquer_capteurs_bloques",
]

_journal: Final = logging.getLogger(__name__)


class Anomalie(StrEnum):
    """Motif pour lequel un relevé devient suspect."""

    HORS_PLAGE = "hors_plage"
    HORODATAGE_FUTUR = "horodatage_futur"
    STATION_INCONNUE = "station_inconnue"
    CAPTEUR_BLOQUE = "capteur_bloque"


@dataclass(slots=True)
class RapportValidation:

    examines: int = 0
    suspects: int = 0
    series_bloquees: int = 0
    plus_longue_serie: int = 0
    anomalies: Counter[Anomalie] = field(default_factory=Counter)
    stations_inconnues: set[str] = field(default_factory=set)

    def signaler(self, anomalie: Anomalie) -> None:
        self.anomalies[anomalie] += 1

    def resume(self) -> str:
        details = " ".join(f"{a.value}={n}" for a, n in sorted(self.anomalies.items()))
        return f"examines={self.examines} suspects={self.suspects} {details}".strip()


@dataclass(slots=True)
class Validateur:

    referentiel: Referentiel | None = None
    marge_futur: timedelta = timedelta(hours=1)
    maintenant: Callable[[], datetime] = lambda: datetime.now(UTC)
    rapport: RapportValidation = field(default_factory=RapportValidation)

    def valider(self, flux: Iterable[Releve]) -> Iterator[Releve]:
        limite = self.maintenant() + self.marge_futur

        for releve in flux:
            self.rapport.examines += 1
            motifs: list[Anomalie] = []


            if not releve.dans_la_plage():
                motifs.append(Anomalie.HORS_PLAGE)

            if releve.horodatage > limite:
                motifs.append(Anomalie.HORODATAGE_FUTUR)

            if self.referentiel is not None and not self.referentiel.connait(releve.station):
                motifs.append(Anomalie.STATION_INCONNUE)
                self.rapport.stations_inconnues.add(releve.station)

            if not motifs:
                yield releve
                continue

            for motif in motifs:
                self.rapport.signaler(motif)
            self.rapport.suspects += 1
            _journal.debug("relevé suspect %s : %s", releve.releve_id, motifs)

            yield releve.avec_qualite(Qualite.SUSPECTE)

    def valider_tout(
        self,
        flux: Iterable[Releve],
        *,
        longueur_min: int = 12,
        cle: Callable[[Releve], Hashable] | None = None,
    ) -> list[Releve]:

        releves = list(self.valider(flux))
        return marquer_capteurs_bloques(
            releves,
            longueur_min=longueur_min,
            cle=cle,
            rapport=self.rapport,
        )



def marquer_capteurs_bloques(
    releves: Sequence[Releve],
    *,
    longueur_min: int = 12,
    cle: Callable[[Releve], Hashable] | None = None,
    rapport: RapportValidation | None = None,
) -> list[Releve]:

    if not releves:
        return []

    extraire = cle or (lambda r: r.source)
    rapport = rapport or RapportValidation()

    a_marquer: set[int] = set()
    groupes: dict[Hashable, list[int]] = {}
    for indice, releve in enumerate(releves):
        groupes.setdefault(extraire(releve), []).append(indice)

    for indices in groupes.values():
        indices.sort(key=lambda i: releves[i].horodatage)
        debut = 0
        for position in range(1, len(indices) + 1):
            fini = position == len(indices)
            rompue = not fini and releves[indices[position]].valeur != releves[indices[position - 1]].valeur
            if not (fini or rompue):
                continue

            longueur = position - debut
            rapport.plus_longue_serie = max(rapport.plus_longue_serie, longueur)
            if longueur > longueur_min:
                rapport.series_bloquees += 1
                a_marquer.update(indices[debut:position])
            debut = position

    if not a_marquer:
        return list(releves)

    rapport.anomalies[Anomalie.CAPTEUR_BLOQUE] += len(a_marquer)
    _journal.info(
        "%d relevés marqués bloqués, répartis sur %d série(s)",
        len(a_marquer),
        rapport.series_bloquees,
    )

    return [
        releve.avec_qualite(Qualite.SUSPECTE) if indice in a_marquer else releve
        for indice, releve in enumerate(releves)
    ]


def plages_depassees(releve: Releve) -> tuple[float, float] | None:
    bornes = PLAGES_PHYSIQUES[releve.grandeur]
    return None if bornes[0] <= releve.valeur <= bornes[1] else bornes
