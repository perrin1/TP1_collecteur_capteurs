

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from collecteur.domaine import Releve

__all__ = ["SourceReleves", "StatistiquesLecture"]


@dataclass(slots=True)
class StatistiquesLecture:


    source: str
    lus: int = 0
    emis: int = 0
    rejetes: int = 0
    dupliques: int = 0
    retentes: int = 0
    pages: int = 0
    unites_converties: int = 0
    fahrenheit_deduits: int = 0
    raisons_rejet: Counter[str] = field(default_factory=Counter)

    def rejeter(self, raison: str) -> None:
        self.rejetes += 1
        self.raisons_rejet[raison] += 1

    def resume(self) -> str:
        return (
            f"source={self.source} lus={self.lus} emis={self.emis} "
            f"rejetes={self.rejetes} dupliques={self.dupliques} "
            f"retentes={self.retentes} pages={self.pages} "
            f"unites_converties={self.unites_converties}"
        )


@runtime_checkable
class SourceReleves(Protocol):


    nom: str
    statistiques: StatistiquesLecture

    def lire(self) -> Iterator[Releve]: ...
