

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "FormateurJSON",
    "JournalCollecte",
    "configurer_journal",
]

#: Attributs posés par `logging` lui-même : tout le reste vient de `extra=`.
_ATTRIBUTS_STANDARD: Final[frozenset[str]] = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class FormateurJSON(logging.Formatter):


    def format(self, record: logging.LogRecord) -> str:
        charge: dict[str, object] = {
            "horodatage": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "niveau": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        for cle, valeur in record.__dict__.items():
            if cle not in _ATTRIBUTS_STANDARD and not cle.startswith("_"):
                charge[cle] = valeur

        if record.exc_info:
            charge["exception"] = self.formatException(record.exc_info)

        return json.dumps(charge, ensure_ascii=False, default=str)


def configurer_journal(
    *,
    niveau: int | str = logging.INFO,
    fichier: Path | str | None = None,
    format_console: str = "texte",
) -> logging.Logger:

    racine = logging.getLogger("collecteur")
    racine.setLevel(niveau)
    racine.handlers.clear()
    racine.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(
        FormateurJSON()
        if format_console == "json"
        else logging.Formatter("%(levelname)-8s %(name)-28s %(message)s")
    )
    racine.addHandler(console)

    if fichier is not None:
        chemin = Path(fichier)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        vers_fichier = logging.FileHandler(chemin, encoding="utf-8")
        vers_fichier.setFormatter(FormateurJSON())
        racine.addHandler(vers_fichier)

    return racine


@dataclass(slots=True)
class JournalCollecte:


    logger: logging.Logger

    def debut(self, source: str, cible: str) -> datetime:
        instant = datetime.now(UTC)
        self.logger.info(
            "collecte démarrée",
            extra={"evenement": "debut", "source": source, "cible": cible},
        )
        return instant

    def fin(
        self,
        source: str,
        *,
        demarree_le: datetime,
        compteurs: Mapping[str, int],
        statut: str = "ok",
    ) -> None:
        duree = (datetime.now(UTC) - demarree_le).total_seconds()
        self.logger.info(
            "collecte terminée",
            extra={
                "evenement": "fin",
                "source": source,
                "statut": statut,
                "duree_s": round(duree, 3),
                **dict(compteurs),
            },
        )

    def incident(self, source: str, message: str, **contexte: object) -> None:
        self.logger.error(
            message,
            extra={"evenement": "incident", "source": source, **contexte},
        )
