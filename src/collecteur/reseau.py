

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

from collecteur.erreurs import ConfigurationInvalide, SourceIndisponible

__all__ = ["PolitiqueRetry", "avec_retry"]

_journal: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolitiqueRetry:


    tentatives_max: int = 5
    delai_initial_s: float = 1.0
    facteur: float = 2.0
    delai_max_s: float = 16.0
    gigue: float = 0.1
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if self.tentatives_max < 1:
            raise ConfigurationInvalide(
                "tentatives_max", valeur=self.tentatives_max, attendu=">= 1"
            )
        if self.delai_initial_s < 0 or self.delai_max_s < self.delai_initial_s:
            raise ConfigurationInvalide(
                "delai_max_s",
                valeur=self.delai_max_s,
                attendu=">= delai_initial_s",
            )
        if self.facteur < 1.0:
            raise ConfigurationInvalide("facteur", valeur=self.facteur, attendu=">= 1.0")
        if not 0.0 <= self.gigue <= 1.0:
            raise ConfigurationInvalide("gigue", valeur=self.gigue, attendu="entre 0 et 1")
        if self.timeout_s <= 0:
            raise ConfigurationInvalide("timeout_s", valeur=self.timeout_s, attendu="> 0")

    def delais(self, *, alea: random.Random | None = None) -> Iterator[float]:

        tirage = alea or random
        delai = self.delai_initial_s
        for _ in range(self.tentatives_max - 1):
            borne = min(delai, self.delai_max_s)
            ecart = borne * self.gigue
            yield max(0.0, borne + tirage.uniform(-ecart, ecart))
            delai *= self.facteur

    def duree_maximale_s(self) -> float:
        return sum(min(self.delai_initial_s * self.facteur**n, self.delai_max_s) for n in range(self.tentatives_max - 1))


def avec_retry[T](
    appel: Callable[[], T],
    *,
    politique: PolitiqueRetry,
    source: str,
    description: str,
    recuperables: tuple[type[BaseException], ...],
    alea: random.Random | None = None,
    dormir: Callable[[float], None] = time.sleep,
    au_reessai: Callable[[int, BaseException], None] | None = None,
) -> T:
    debut = time.monotonic()
    derniere: BaseException | None = None
    delais = politique.delais(alea=alea)

    for tentative in range(1, politique.tentatives_max + 1):
        try:
            return appel()
        except recuperables as erreur:
            derniere = erreur
            if au_reessai is not None:
                au_reessai(tentative, erreur)

            if tentative == politique.tentatives_max:
                break

            attente = next(delais, politique.delai_max_s)
            _journal.warning(
                "%s : échec %d/%d (%s), nouvelle tentative dans %.1f s",
                description,
                tentative,
                politique.tentatives_max,
                type(erreur).__name__,
                attente,
            )
            dormir(attente)

    raise SourceIndisponible(
        source,
        url=description,
        tentatives=politique.tentatives_max,
        delai_total_s=time.monotonic() - debut,
        cause=derniere,
    )
