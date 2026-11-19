

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = ["FileHorsLigne", "RequeteDifferee"]

_journal: Final = logging.getLogger(__name__)


def _entier(valeur: object) -> int:
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else 0


@dataclass(frozen=True, slots=True)
class RequeteDifferee:

    source: str
    cible: str
    parametres: dict[str, str | int] = field(default_factory=dict)
    motif: str = ""
    tentatives: int = 0
    creee_le: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def cle(self) -> tuple[str, str, str]:
        return (self.source, self.cible, json.dumps(self.parametres, sort_keys=True))

    @classmethod
    def depuis_json(cls, brut: dict[str, object]) -> RequeteDifferee:
        parametres = brut.get("parametres")
        return cls(
            source=str(brut.get("source", "")),
            cible=str(brut.get("cible", "")),
            parametres=dict(parametres) if isinstance(parametres, dict) else {},
            motif=str(brut.get("motif", "")),
            tentatives=_entier(brut.get("tentatives")),
            creee_le=str(brut.get("creee_le", "")),
        )


class FileHorsLigne:

    def __init__(self, chemin: Path | str = "file_attente/requetes.jsonl") -> None:
        self.chemin: Path = Path(chemin)
        self.lignes_corrompues: int = 0


    def empiler(self, requete: RequeteDifferee) -> bool:
        if any(existante.cle() == requete.cle() for existante in self):
            _journal.debug("requête déjà en file : %s", requete.cible)
            return False

        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self.chemin.open("a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(asdict(requete), ensure_ascii=False) + "\n")
            fichier.flush()
            os.fsync(fichier.fileno())

        _journal.info("requête différée : %s (%s)", requete.cible, requete.motif)
        return True

    def vider(self) -> None:
        self.chemin.unlink(missing_ok=True)

    def remplacer(self, requetes: list[RequeteDifferee]) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        descripteur, provisoire = tempfile.mkstemp(
            dir=self.chemin.parent, prefix=".file-", suffix=".tmp"
        )
        try:
            with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
                for requete in requetes:
                    fichier.write(json.dumps(asdict(requete), ensure_ascii=False) + "\n")
                fichier.flush()
                os.fsync(fichier.fileno())
            Path(provisoire).replace(self.chemin)
        except BaseException:
            Path(provisoire).unlink(missing_ok=True)
            raise


    def __iter__(self) -> Iterator[RequeteDifferee]:
        self.lignes_corrompues = 0
        if not self.chemin.exists():
            return

        with self.chemin.open(encoding="utf-8") as fichier:
            for numero, ligne in enumerate(fichier, start=1):
                texte = ligne.strip()
                if not texte:
                    continue
                try:
                    brut = json.loads(texte)
                except json.JSONDecodeError:
                    self.lignes_corrompues += 1
                    _journal.warning(
                        "ligne %d de la file illisible, ignorée (arrêt brutal ?)", numero
                    )
                    continue
                if isinstance(brut, dict):
                    yield RequeteDifferee.depuis_json(brut)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __bool__(self) -> bool:
        return any(True for _ in self)

    def rejouer(self) -> Iterator[RequeteDifferee]:
        en_attente = list(self)
        if not en_attente:
            return
        self.vider()
        _journal.info("rejeu de %d requête(s) différée(s)", len(en_attente))
        yield from en_attente

    def __repr__(self) -> str:
        return f"FileHorsLigne({self.chemin.as_posix()!r}, {len(self)} en attente)"
