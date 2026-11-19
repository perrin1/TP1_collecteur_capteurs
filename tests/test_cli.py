

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collecteur.cli import construire_analyseur, main
from collecteur.stockage import Entrepot
from tests.conftest import releve


def test_sans_commande_echoue() -> None:
    with pytest.raises(SystemExit):
        construire_analyseur().parse_args([])


def test_analyse_des_options() -> None:
    arguments = construire_analyseur().parse_args(
        ["collecter", "--source", "A,B", "--depuis", "2026-03-15", "-vv"]
    )
    assert arguments.commande == "collecter"
    assert arguments.source == "A,B"
    assert arguments.depuis == datetime(2026, 3, 15, tzinfo=UTC)
    assert arguments.verbeux == 2


def test_date_illisible_refusee() -> None:
    with pytest.raises(SystemExit):
        construire_analyseur().parse_args(["collecter", "--depuis", "hier"])


def test_collecter_sur_les_fichiers(
    tmp_path: Path,
    csv_station_a: Path,
    json_station_b: Path,
    csv_referentiel: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "collecte.db"
    code = main(
        [
            "collecter",
            "--source",
            "A,B",
            "--donnees",
            str(csv_station_a.parent),
            "--base",
            str(base),
        ]
    )

    assert code == 0
    sortie = capsys.readouterr().out
    assert "source" in sortie

    with Entrepot(base) as entrepot:
        assert entrepot.comptes_par_source() == {"A": 4, "B": 3}


def test_collecter_est_idempotent_depuis_la_cli(
    tmp_path: Path, csv_station_a: Path, csv_referentiel: Path
) -> None:
    """La preuve F2, passée par la ligne de commande."""
    base = tmp_path / "collecte.db"
    options = ["collecter", "--source", "A", "--donnees", str(csv_station_a.parent),
               "--base", str(base)]

    assert main(options) == 0
    with Entrepot(base) as entrepot:
        premier = entrepot.compter()

    assert main(options) == 0
    with Entrepot(base) as entrepot:
        assert entrepot.compter() == premier


def test_option_depuis_filtre_le_flux(
    tmp_path: Path, csv_station_a: Path, csv_referentiel: Path
) -> None:
    base = tmp_path / "collecte.db"
    main(
        [
            "collecter",
            "--source",
            "A",
            "--donnees",
            str(csv_station_a.parent),
            "--base",
            str(base),
            "--depuis",
            "2026-03-03",
        ]
    )
    with Entrepot(base) as entrepot:
        identifiants = {r.releve_id for r in entrepot.releves()}
    assert identifiants == {"A-000003", "A-000004"}


def test_source_inconnue_renvoie_un_code_derreur(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["collecter", "--source", "Z", "--base", str(tmp_path / "x.db")])
    assert code == 2
    assert "Aucune source" in capsys.readouterr().err


def test_statut_sans_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["statut", "--base", str(tmp_path / "absente.db")])
    assert code == 1
    assert "Aucune base" in capsys.readouterr().out


def test_statut_affiche_les_comptes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = tmp_path / "collecte.db"
    with Entrepot(base) as entrepot:
        entrepot.enregistrer([releve("A-1"), releve("B-1", source="B", station="STB-11")])

    assert main(["statut", "--base", str(base)]) == 0
    sortie = capsys.readouterr().out
    assert "2 relevés" in sortie
    assert "File hors-ligne" in sortie


def test_rejouer_file_vide(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["rejouer-file", "--base", str(tmp_path / "collecte.db")])
    assert code == 0
    assert "rien à rejouer" in capsys.readouterr().out


def test_namespace_complet_pour_chaque_commande() -> None:
    """Les options communes existent sur les trois commandes."""
    analyseur = construire_analyseur()
    for commande in ("collecter", "statut", "rejouer-file"):
        arguments = analyseur.parse_args([commande])
        assert isinstance(arguments, argparse.Namespace)
        assert hasattr(arguments, "base")
        assert hasattr(arguments, "verbeux")
        assert hasattr(arguments, "journal")
