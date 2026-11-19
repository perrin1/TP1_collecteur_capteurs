

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from collecteur.domaine import Grandeur, Qualite, Releve

__all__ = ["Entrepot", "ResultatEcriture"]

_journal: Final = logging.getLogger(__name__)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS releves (
    releve_id   TEXT    PRIMARY KEY,
    station     TEXT    NOT NULL,
    horodatage  TEXT    NOT NULL,
    grandeur    TEXT    NOT NULL,
    valeur      REAL    NOT NULL,
    unite       TEXT    NOT NULL,
    qualite     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    vu_le       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_releves_station_ts ON releves (station, horodatage);
CREATE INDEX IF NOT EXISTS idx_releves_source     ON releves (source);
CREATE INDEX IF NOT EXISTS idx_releves_qualite    ON releves (qualite);

CREATE TABLE IF NOT EXISTS collectes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    demarree_le TEXT    NOT NULL,
    finie_le    TEXT,
    lus         INTEGER NOT NULL DEFAULT 0,
    inseres     INTEGER NOT NULL DEFAULT 0,
    deja_vus    INTEGER NOT NULL DEFAULT 0,
    rejetes     INTEGER NOT NULL DEFAULT 0,
    retentes    INTEGER NOT NULL DEFAULT 0
);
"""

_INSERTION: Final = """
INSERT INTO releves
    (releve_id, station, horodatage, grandeur, valeur, unite, qualite, source, vu_le)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(releve_id) DO UPDATE SET
    station    = excluded.station,
    horodatage = excluded.horodatage,
    grandeur   = excluded.grandeur,
    valeur     = excluded.valeur,
    unite      = excluded.unite,
    qualite    = excluded.qualite,
    source     = excluded.source
WHERE
    releves.valeur  IS NOT excluded.valeur
    OR releves.qualite IS NOT excluded.qualite
"""


@dataclass(frozen=True, slots=True)
class ResultatEcriture:


    recus: int = 0
    inseres: int = 0
    mis_a_jour: int = 0
    deja_vus: int = 0

    def __add__(self, autre: ResultatEcriture) -> ResultatEcriture:
        return ResultatEcriture(
            recus=self.recus + autre.recus,
            inseres=self.inseres + autre.inseres,
            mis_a_jour=self.mis_a_jour + autre.mis_a_jour,
            deja_vus=self.deja_vus + autre.deja_vus,
        )

    def resume(self) -> str:
        return (
            f"recus={self.recus} inseres={self.inseres} "
            f"mis_a_jour={self.mis_a_jour} deja_vus={self.deja_vus}"
        )


class Entrepot:

    def __init__(self, chemin: Path | str = "collecte.db", *, taille_lot: int = 500) -> None:
        self.chemin: Path = Path(chemin)
        self.taille_lot: int = taille_lot
        self._connexion: sqlite3.Connection | None = None


    def ouvrir(self) -> Self:
        if self._connexion is not None:
            return self

        if self.chemin.parent != Path():
            self.chemin.parent.mkdir(parents=True, exist_ok=True)

        self._connexion = sqlite3.connect(self.chemin, isolation_level=None)
        self._connexion.row_factory = sqlite3.Row
        self._connexion.execute("PRAGMA journal_mode=WAL")
        self._connexion.execute("PRAGMA synchronous=NORMAL")
        self._connexion.execute("PRAGMA foreign_keys=ON")
        self._connexion.executescript(_SCHEMA)
        return self

    def fermer(self) -> None:
        if self._connexion is not None:
            self._connexion.close()
            self._connexion = None

    def __enter__(self) -> Self:
        return self.ouvrir()

    def __exit__(
        self,
        type_exception: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.fermer()

    @property
    def connexion(self) -> sqlite3.Connection:
        if self._connexion is None:
            raise RuntimeError("Entrepot non ouvert : utilisez `with Entrepot(...) as e:`")
        return self._connexion


    def enregistrer(self, releves: Iterable[Releve]) -> ResultatEcriture:
        connexion = self.connexion
        maintenant = datetime.now(UTC).isoformat()

        avant = self.compter()
        recus = 0
        modifications_avant = connexion.total_changes

        connexion.execute("BEGIN")
        try:
            for lot in _par_lots(releves, self.taille_lot):
                recus += len(lot)
                connexion.executemany(
                    _INSERTION,
                    [
                        (
                            r.releve_id,
                            r.station,
                            r.horodatage.isoformat(),
                            str(r.grandeur),
                            r.valeur,
                            r.unite,
                            str(r.qualite),
                            r.source,
                            maintenant,
                        )
                        for r in lot
                    ],
                )
            connexion.execute("COMMIT")
        except BaseException:
            connexion.execute("ROLLBACK")
            raise

        apres = self.compter()
        inseres = apres - avant
        modifications = connexion.total_changes - modifications_avant
        mis_a_jour = max(0, modifications - inseres)

        resultat = ResultatEcriture(
            recus=recus,
            inseres=inseres,
            mis_a_jour=mis_a_jour,
            deja_vus=recus - inseres - mis_a_jour,
        )
        _journal.info("écriture terminée : %s", resultat.resume())
        return resultat

    def journaliser_collecte(
        self,
        source: str,
        *,
        demarree_le: datetime,
        lus: int,
        inseres: int,
        deja_vus: int,
        rejetes: int,
        retentes: int,
    ) -> int:
        curseur = self.connexion.execute(
            "INSERT INTO collectes "
            "(source, demarree_le, finie_le, lus, inseres, deja_vus, rejetes, retentes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                demarree_le.isoformat(),
                datetime.now(UTC).isoformat(),
                lus,
                inseres,
                deja_vus,
                rejetes,
                retentes,
            ),
        )
        return int(curseur.lastrowid or 0)


    def compter(self, *, source: str | None = None, qualite: Qualite | None = None) -> int:
        requete = "SELECT COUNT(*) FROM releves"
        conditions: list[str] = []
        parametres: list[str] = []
        if source is not None:
            conditions.append("source = ?")
            parametres.append(source)
        if qualite is not None:
            conditions.append("qualite = ?")
            parametres.append(str(qualite))
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)

        ligne = self.connexion.execute(requete, parametres).fetchone()
        return int(ligne[0]) if ligne else 0

    def comptes_par_source(self) -> dict[str, int]:
        return {
            str(ligne["source"]): int(ligne["n"])
            for ligne in self.connexion.execute(
                "SELECT source, COUNT(*) AS n FROM releves GROUP BY source ORDER BY source"
            )
        }

    def comptes_par_qualite(self) -> dict[str, int]:
        return {
            str(ligne["qualite"]): int(ligne["n"])
            for ligne in self.connexion.execute(
                "SELECT qualite, COUNT(*) AS n FROM releves GROUP BY qualite ORDER BY qualite"
            )
        }

    def derniere_collecte(self, source: str) -> datetime | None:
        ligne = self.connexion.execute(
            "SELECT MAX(horodatage) AS maxi FROM releves WHERE source = ?", (source,)
        ).fetchone()
        if ligne is None or ligne["maxi"] is None:
            return None
        return datetime.fromisoformat(str(ligne["maxi"]))

    def series_bloquees_sql(self, longueur_min: int = 12) -> list[tuple[str, float, int]]:
        requete = """
        WITH numerote AS (
            SELECT source, valeur,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY horodatage) AS rang,
                   ROW_NUMBER() OVER (PARTITION BY source, valeur ORDER BY horodatage) AS rang_valeur
            FROM releves
        )
        SELECT source, valeur, COUNT(*) AS longueur
        FROM numerote
        GROUP BY source, valeur, rang - rang_valeur
        HAVING COUNT(*) > ?
        ORDER BY longueur DESC
        """
        return [
            (str(ligne["source"]), float(ligne["valeur"]), int(ligne["longueur"]))
            for ligne in self.connexion.execute(requete, (longueur_min,))
        ]

    def marquer_series_bloquees(self, longueur_min: int = 12) -> int:
        requete = """
        UPDATE releves SET qualite = 'suspecte'
        WHERE qualite = 'valide' AND releve_id IN (
            WITH numerote AS (
                SELECT releve_id, source, valeur,
                       ROW_NUMBER() OVER (PARTITION BY source ORDER BY horodatage) AS rang,
                       ROW_NUMBER() OVER (PARTITION BY source, valeur ORDER BY horodatage) AS rang_valeur
                FROM releves
            ),
            series AS (
                SELECT source, valeur, rang - rang_valeur AS ile
                FROM numerote
                GROUP BY source, valeur, rang - rang_valeur
                HAVING COUNT(*) > ?
            )
            SELECT n.releve_id
            FROM numerote AS n
            JOIN series AS s
              ON n.source = s.source
             AND n.valeur = s.valeur
             AND n.rang - n.rang_valeur = s.ile
        )
        """
        curseur = self.connexion.execute(requete, (longueur_min,))
        marques = curseur.rowcount
        if marques:
            _journal.info("%d relevés marqués bloqués en base", marques)
        return marques

    def releves(self, *, limite: int | None = None) -> Iterator[Releve]:
        requete = "SELECT * FROM releves ORDER BY horodatage"
        if limite is not None:
            requete += f" LIMIT {int(limite)}"
        for ligne in self.connexion.execute(requete):
            yield Releve(
                releve_id=str(ligne["releve_id"]),
                station=str(ligne["station"]),
                horodatage=datetime.fromisoformat(str(ligne["horodatage"])),
                grandeur=Grandeur(str(ligne["grandeur"])),
                valeur=float(ligne["valeur"]),
                unite=str(ligne["unite"]),
                qualite=Qualite(str(ligne["qualite"])),
                source=str(ligne["source"]),
            )

    def __repr__(self) -> str:
        return f"Entrepot({self.chemin.name!r})"


def _par_lots[T](elements: Iterable[T], taille: int) -> Iterator[list[T]]:
    lot: list[T] = []
    for element in elements:
        lot.append(element)
        if len(lot) >= taille:
            yield lot
            lot = []
    if lot:
        yield lot
