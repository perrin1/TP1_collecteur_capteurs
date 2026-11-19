

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collecteur.domaine import Grandeur, Qualite, Releve

CSV_MINIMAL = (
    "﻿releve_id;Station;DATE_HEURE;grandeur;Valeur;unite;capteur_serie\r\n"
    # Trois formats de date mélangés
    "A-000001;STA-01;2026-03-01 08:00:00;temperature;25,40;degC;SN1\r\n"
    "A-000002;sta-02;02/03/2026 09:30;humidite_sol;41,20;pct;SN2\r\n"
    "A-000003;STA-01;2026-03-03T10:15:00+00:00;pluviometrie;35,0;dmm;SN3\r\n"
    # Fahrenheit annoncé
    "A-000004;STA-03;2026-03-04 11:00:00;TEMPERATURE;98,60;degF;SN4\r\n"
    # Doublon exact de la première ligne
    "A-000001;STA-01;2026-03-01 08:00:00;temperature;25,40;degC;SN1\r\n"
    # Valeur illisible : rejetée, sans faire tomber le reste
    "A-000005;STA-01;2026-03-05 12:00:00;temperature;abc;degC;SN5\r\n"
)


@pytest.fixture
def csv_station_a(tmp_path: Path) -> Path:
    chemin = tmp_path / "station_A_releves.csv"
    chemin.write_bytes(CSV_MINIMAL.encode("utf-8"))
    return chemin


@pytest.fixture
def json_station_b(tmp_path: Path) -> Path:
    document = {
        "schema": "station-b/v2",
        "genere_le": "2026-03-01T00:00:00+00:00",
        "mesures": [
            {
                "id": "B-000001",
                "station": {"code": "STB-11", "firmware": "2.1.0"},
                "ts": "2026-03-01T08:00:00+00:00",
                "fuseau": "UTC",
                "mesure": {"type": "temperature", "valeur": 27.5, "unite": "degC"},
                "batterie_pct": 80,
            },
            {
                # Heure murale 08:00 déclarée à Porto-Novo : 07:00 UTC.
                "id": "B-000002",
                "station": {"code": "STB-12", "firmware": "2.2.0"},
                "ts": "2026-03-01T08:00:00+00:00",
                "fuseau": "Africa/Porto-Novo",
                "mesure": {"type": "humidite_air", "valeur": 0.62, "unite": "ratio"},
                "batterie_pct": 55,
            },
        ],
        "mesures_differees": [
            {
                # Fahrenheit non annoncé : 104 « degC » valent 40 °C.
                "id": "B-000003",
                "station": {"code": "STB-99", "firmware": "1.0.0"},
                "ts": "2026-03-01T09:00:00+00:00",
                "fuseau": "UTC",
                "mesure": {"type": "temperature", "valeur": 104.0, "unite": "degC"},
                "batterie_pct": 20,
            }
        ],
    }
    chemin = tmp_path / "station_B_releves.json"
    chemin.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    return chemin


@pytest.fixture
def csv_referentiel(tmp_path: Path) -> Path:
    chemin = tmp_path / "stations_reference.csv"
    chemin.write_text(
        "code_station;commune;latitude;longitude;altitude_m;date_installation\n"
        "STA-01;Parakou;9.3372;2.6303;350;2024-01-01\n"
        "STA-02;Djougou;9.7085;1.6660;430;2024-01-01\n"
        "STA-03;Glazoue;7.9777;2.2410;210;2024-01-01\n"
        "STB-11;Bohicon;7.1782;2.0667;166;2024-01-01\n"
        "STB-12;Natitingou;10.3047;1.3797;460;2024-01-01\n",
        encoding="utf-8",
    )
    return chemin


def releve(
    identifiant: str = "X-1",
    *,
    station: str = "STA-01",
    heure: int = 8,
    jour: int = 1,
    grandeur: Grandeur = Grandeur.TEMPERATURE,
    valeur: float = 25.0,
    unite: str = "degC",
    qualite: Qualite = Qualite.VALIDE,
    source: str = "A",
) -> Releve:
    return Releve(
        releve_id=identifiant,
        station=station,
        horodatage=datetime(2026, 3, jour, heure, 0, tzinfo=UTC),
        grandeur=grandeur,
        valeur=valeur,
        unite=unite,
        qualite=qualite,
        source=source,
    )
