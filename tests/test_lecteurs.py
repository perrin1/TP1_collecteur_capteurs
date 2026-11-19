"""Parties B et C — un test par lecteur, plus la normalisation (D5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from collecteur.domaine import Grandeur, Qualite
from collecteur.erreurs import ReleveIncoherent
from collecteur.normalisation import normaliser_unite, parser_horodatage
from collecteur.referentiel import Referentiel
from collecteur.sources import LecteurCSV, LecteurJSON, SourceReleves
from collecteur.validation import Anomalie, Validateur, marquer_capteurs_bloques
from tests.conftest import releve


@pytest.mark.parametrize(
    ("valeur", "unite_brute", "attendu", "unite_attendue"),
    [
        (98.6, "degF", 37.0, "degC"),
        (98.6, "F", 37.0, "degC"),
        (27.4, "C", 27.4, "degC"),
        (0.62, "ratio", 62.0, "pct"),
        (62.0, "%", 62.0, "pct"),
        (35.0, "dmm", 3.5, "mm"),
        (2.4, "dS/m", 2.4, "dS_m"),
    ],
)
def test_conversion_unites(
    valeur: float, unite_brute: str, attendu: float, unite_attendue: str
) -> None:
    obtenu, unite = normaliser_unite(valeur, unite_brute)
    assert unite == unite_attendue
    assert obtenu == pytest.approx(attendu, abs=1e-9)


def test_unite_inconnue_rejetee() -> None:
    with pytest.raises(ReleveIncoherent):
        normaliser_unite(1.0, "kPa")




@pytest.mark.parametrize(
    "brut",
    ["2026-03-01 08:00:00", "01/03/2026 08:00", "2026-03-01T08:00:00+00:00"],
)
def test_trois_formats_donnent_le_meme_instant(brut: str) -> None:
    assert parser_horodatage(brut) == datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def test_fuseau_declare_prime_sur_le_decalage_ecrit() -> None:
    """Le piège de la station B : `ts` dit +00:00, `fuseau` dit Porto-Novo."""
    from zoneinfo import ZoneInfo

    obtenu = parser_horodatage(
        "2026-03-01T08:00:00+00:00", fuseau_declare=ZoneInfo("Africa/Porto-Novo")
    )
    assert obtenu == datetime(2026, 3, 1, 7, 0, tzinfo=UTC)


def test_format_inconnu_rejete() -> None:
    with pytest.raises(ReleveIncoherent):
        parser_horodatage("hier matin")


def test_lecteur_csv(csv_station_a: Path) -> None:
    lecteur = LecteurCSV(csv_station_a)
    assert isinstance(lecteur, SourceReleves)

    releves = list(lecteur.lire())
    stats = lecteur.statistiques

    # 6 lignes de données, dont une illisible.
    assert stats.lus == 6
    assert stats.rejetes == 1
    assert len(releves) == 5

    par_id = {r.releve_id: r for r in releves}

    # Le BOM n'a pas cassé la première colonne.
    assert "A-000001" in par_id
    # Casse de la station corrigée.
    assert par_id["A-000002"].station == "STA-02"
    # dmm -> mm.
    assert par_id["A-000003"].valeur == pytest.approx(3.5)
    assert par_id["A-000003"].unite == "mm"
    # degF -> degC, et grandeur en majuscules absorbée.
    assert par_id["A-000004"].grandeur is Grandeur.TEMPERATURE
    assert par_id["A-000004"].valeur == pytest.approx(37.0)
    # Doublon exact compté, mais pas supprimé : c'est le stockage qui tranche.
    assert stats.dupliques == 1


def test_lecteur_csv_fichier_absent(tmp_path: Path) -> None:
    from collecteur.erreurs import PayloadInvalide

    with pytest.raises(PayloadInvalide):
        list(LecteurCSV(tmp_path / "absent.csv").lire())



def test_lecteur_json_lit_les_deux_tableaux(json_station_b: Path) -> None:
    lecteur = LecteurJSON(json_station_b)
    releves = {r.releve_id: r for r in lecteur.lire()}

    # Le relevé différé est bien là : c'est tout l'enjeu.
    assert set(releves) == {"B-000001", "B-000002", "B-000003"}
    assert lecteur.statistiques.lus == 3


def test_lecteur_json_applique_le_fuseau_declare(json_station_b: Path) -> None:
    releves = {r.releve_id: r for r in LecteurJSON(json_station_b).lire()}
    assert releves["B-000002"].horodatage == datetime(2026, 3, 1, 7, 0, tzinfo=UTC)
    assert releves["B-000002"].unite == "pct"
    assert releves["B-000002"].valeur == pytest.approx(62.0)


def test_lecteur_json_deduit_le_fahrenheit_implicite(json_station_b: Path) -> None:
    lecteur = LecteurJSON(json_station_b)
    releves = {r.releve_id: r for r in lecteur.lire()}
    assert releves["B-000003"].valeur == pytest.approx(40.0)
    assert lecteur.statistiques.fahrenheit_deduits == 1


def test_deduction_desactivable(json_station_b: Path) -> None:
    releves = {r.releve_id: r for r in LecteurJSON(json_station_b, deduire_fahrenheit=False).lire()}
    assert releves["B-000003"].valeur == pytest.approx(104.0)


def test_lecture_json_reste_paresseuse(json_station_b: Path) -> None:
    """Un itérateur, pas une liste : le premier relevé arrive avant la fin."""
    flux = LecteurJSON(json_station_b).lire()
    premier = next(flux)
    assert premier.releve_id == "B-000001"



def test_hors_plage_marque_mais_conserve() -> None:
    validateur = Validateur()
    sortie = list(validateur.valider([releve("A-1", valeur=95.0)]))
    assert len(sortie) == 1
    assert sortie[0].qualite is Qualite.SUSPECTE
    assert validateur.rapport.anomalies[Anomalie.HORS_PLAGE] == 1


def test_horodatage_futur_marque() -> None:
    fige = datetime(2026, 3, 1, tzinfo=UTC)
    validateur = Validateur(maintenant=lambda: fige)
    sortie = list(validateur.valider([releve("A-1", jour=28)]))
    assert sortie[0].qualite is Qualite.SUSPECTE
    assert validateur.rapport.anomalies[Anomalie.HORODATAGE_FUTUR] == 1


def test_station_inconnue_marquee(csv_referentiel: Path) -> None:
    validateur = Validateur(referentiel=Referentiel.depuis_csv(csv_referentiel))
    sortie = list(validateur.valider([releve("B-1", station="STB-99", source="B")]))
    assert sortie[0].qualite is Qualite.SUSPECTE
    assert validateur.rapport.stations_inconnues == {"STB-99"}


def test_capteur_bloque_detecte_au_dela_du_seuil() -> None:
    serie = [releve(f"A-{i}", heure=i, valeur=21.0) for i in range(15)]
    sortie = marquer_capteurs_bloques(serie, longueur_min=12)
    assert all(r.qualite is Qualite.SUSPECTE for r in sortie)


def test_serie_trop_courte_non_marquee() -> None:
    serie = [releve(f"A-{i}", heure=i, valeur=21.0) for i in range(12)]
    sortie = marquer_capteurs_bloques(serie, longueur_min=12)
    assert all(r.qualite is Qualite.VALIDE for r in sortie)


def test_aucun_releve_nest_jamais_supprime(csv_referentiel: Path) -> None:
    """L'invariante centrale de la partie C."""
    entree = [
        releve("A-1", valeur=95.0),
        releve("A-2", station="STB-99", source="B"),
        releve("A-3"),
    ]
    validateur = Validateur(referentiel=Referentiel.depuis_csv(csv_referentiel))
    sortie = validateur.valider_tout(entree)
    assert len(sortie) == len(entree)
    assert {r.releve_id for r in sortie} == {r.releve_id for r in entree}


def test_absence_de_tzdata_echoue_vite(json_station_b: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from zoneinfo import ZoneInfoNotFoundError

    from collecteur.erreurs import ConfigurationInvalide
    from collecteur.sources import json_b

    def sans_base(*_: object, **__: object) -> object:
        raise ZoneInfoNotFoundError("pas de base")

    monkeypatch.setattr(json_b, "ZoneInfo", sans_base)

    # Sans cette garde, les 3 800 relevés seraient rejetés un par un et la
    # collecte se terminerait avec un statut « ok ».
    with pytest.raises(ConfigurationInvalide, match="tzdata"):
        list(LecteurJSON(json_station_b).lire())
