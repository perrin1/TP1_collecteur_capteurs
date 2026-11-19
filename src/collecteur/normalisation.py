

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, tzinfo
from typing import Final

from collecteur.domaine import PLAGES_PHYSIQUES, Grandeur
from collecteur.erreurs import ReleveIncoherent

__all__ = [
    "ALIAS_UNITES",
    "FORMATS_DATE",
    "fahrenheit_implicite",
    "normaliser_unite",
    "parser_horodatage",
]



#  C1 — Unités

ALIAS_UNITES: Final[Mapping[str, str]] = {
    "degc": "degC",
    "c": "degC",
    "°c": "degC",
    "degf": "degF",
    "f": "degF",
    "°f": "degF",
    "pct": "pct",
    "%": "pct",
    "ratio": "ratio",
    "mm": "mm",
    "dmm": "dmm",
    "ds_m": "dS_m",
    "ds/m": "dS_m",
    "dsm": "dS_m",
}


_CONVERSIONS: Final[Mapping[str, tuple[str, Callable[[float], float]]]] = {
    "degF": ("degC", lambda v: (v - 32.0) * 5.0 / 9.0),
    "ratio": ("pct", lambda v: v * 100.0),
    "dmm": ("mm", lambda v: v / 10.0),
}


def normaliser_unite(
    valeur: float,
    unite_brute: str,
    *,
    releve_id: str | None = None,
    source: str | None = None,
) -> tuple[float, str]:

    reconnue = ALIAS_UNITES.get(unite_brute.strip().lower())
    if reconnue is None:
        raise ReleveIncoherent(
            "Unité inconnue",
            champ="unite",
            valeur=unite_brute,
            releve_id=releve_id,
            source=source,
        )

    conversion = _CONVERSIONS.get(reconnue)
    if conversion is None:
        return float(valeur), reconnue

    canonique, transformer = conversion
    return transformer(float(valeur)), canonique


def fahrenheit_implicite(valeur: float, grandeur: Grandeur, unite: str) -> bool:

    if grandeur is not Grandeur.TEMPERATURE or unite != "degC":
        return False
    _, maximum = PLAGES_PHYSIQUES[Grandeur.TEMPERATURE]
    return valeur > maximum



#  C2 — Horodatages

FORMATS_DATE: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%dT%H:%M:%SZ",
    "%d/%m/%Y %H:%M:%S",
)


def parser_horodatage(
    brut: str,
    *,
    fuseau_declare: tzinfo | None = None,
    fuseau_par_defaut: tzinfo = UTC,
    releve_id: str | None = None,
    source: str | None = None,
) -> datetime:

    texte = brut.replace("﻿", "").strip()
    if not texte:
        raise ReleveIncoherent(
            "Horodatage vide",
            champ="horodatage",
            valeur=brut,
            releve_id=releve_id,
            source=source,
        )

    date = _decoder(texte)
    if date is None:
        raise ReleveIncoherent(
            "Format d'horodatage non reconnu",
            champ="horodatage",
            valeur=brut,
            releve_id=releve_id,
            source=source,
        )

    if fuseau_declare is not None:

        return date.replace(tzinfo=fuseau_declare).astimezone(UTC)

    if date.tzinfo is None:
        date = date.replace(tzinfo=fuseau_par_defaut)

    return date.astimezone(UTC)


def _decoder(texte: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:
        pass

    for format_date in FORMATS_DATE:
        try:
            return datetime.strptime(texte, format_date)  # noqa: DTZ007
        except ValueError:
            continue

    return None
