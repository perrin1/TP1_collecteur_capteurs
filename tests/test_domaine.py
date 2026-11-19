

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from collecteur.domaine import Grandeur, Qualite, Releve
from collecteur.erreurs import CollecteError, ReleveIncoherent
from tests.conftest import releve


def test_releve_valide_se_construit() -> None:
    r = releve("A-1", valeur=25.4)
    assert r.grandeur is Grandeur.TEMPERATURE
    assert r.horodatage.tzinfo is not None
    assert r.dans_la_plage()


def test_releve_est_fige() -> None:
    r = releve()
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.valeur = 99.0  # type: ignore[misc]


def test_avec_qualite_ne_mute_pas_loriginal() -> None:
    r = releve()
    s = r.avec_qualite(Qualite.SUSPECTE)
    assert s.qualite is Qualite.SUSPECTE
    assert r.qualite is Qualite.VALIDE
    assert s.releve_id == r.releve_id


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("releve_id", "  "),
        ("station", "sta-01"),
        ("unite", "degF"),
        ("unite", "pct"),
        ("source", "Z"),
        ("valeur", float("nan")),
        ("valeur", float("inf")),
    ],
)
def test_invariantes_structurelles_refusees(champ: str, valeur: object) -> None:
    base = {
        "releve_id": "A-1",
        "station": "STA-01",
        "horodatage": datetime(2026, 3, 1, tzinfo=UTC),
        "grandeur": Grandeur.TEMPERATURE,
        "valeur": 25.0,
        "unite": "degC",
        "qualite": Qualite.VALIDE,
        "source": "A",
    }
    with pytest.raises(ReleveIncoherent):
        Releve(**{**base, champ: valeur})  # type: ignore[arg-type]


def test_horodatage_naif_refuse() -> None:
    with pytest.raises(ReleveIncoherent):
        Releve.creer(
            releve_id="A-1",
            station="STA-01",
            horodatage=datetime(2026, 3, 1),  # noqa: DTZ001
            grandeur=Grandeur.TEMPERATURE,
            valeur=25.0,
            unite="degC",
            source="A",
        )


def test_creer_canonise_station_et_fuseau() -> None:
    r = Releve.creer(
        releve_id=" A-9 ",
        station="sta-07",
        horodatage=datetime(2026, 3, 1, 9, 0, tzinfo=timezone(timedelta(hours=1))),
        grandeur="TEMPERATURE ",
        valeur=25.0,
        unite="degC",
        source="a",
    )
    assert r.releve_id == "A-9"
    assert r.station == "STA-07"
    assert r.source == "A"
    assert r.horodatage == datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def test_valeur_hors_plage_reste_acceptee() -> None:
    """La frontière du TP : hors plage n'est pas une erreur de structure."""
    r = releve(valeur=95.0)
    assert not r.dans_la_plage()
    assert r.qualite is Qualite.VALIDE


def test_grandeur_absorbe_casse_et_bom() -> None:
    assert Grandeur.depuis_texte("﻿ TEMPERATURE ") is Grandeur.TEMPERATURE
    assert Grandeur.depuis_texte("humidite-sol") is Grandeur.HUMIDITE_SOL
    with pytest.raises(ReleveIncoherent):
        Grandeur.depuis_texte("pression")


def test_exception_porte_son_contexte() -> None:
    erreur = ReleveIncoherent("Unité inconnue", champ="unite", valeur="kPa", source="A")
    assert isinstance(erreur, CollecteError)
    assert erreur.champ == "unite"
    assert "kPa" in str(erreur)
    assert "champ=" in str(erreur)
