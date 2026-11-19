# -*- coding: utf-8 -*-
"""TP1 — Génère les sources station A (CSV) et station B (JSON).

Usage :
    python generer_donnees.py

Produit dans ./data/ :
    station_A_releves.csv   — 4 200 lignes, séparateur ';', décimale ','
    station_B_releves.json  — ~3 800 relevés, structure imbriquée
    stations_reference.csv  — métadonnées (volontairement incomplètes)
"""
from __future__ import annotations

import csv
import json
import os
import random
from datetime import datetime, timedelta, timezone

RNG = random.Random(20261110)
ICI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ICI, "data")

DEBUT = datetime(2026, 3, 1, tzinfo=timezone.utc)
STATIONS_A = ["STA-01", "STA-02", "STA-03", "STA-07"]
STATIONS_B = ["STB-11", "STB-12", "STB-13"]

# Grandeur -> (min, max, unite_principale)
PROFILS = {
    "temperature": (18.0, 41.0, "degC"),
    "humidite_sol": (8.0, 62.0, "pct"),
    "humidite_air": (25.0, 98.0, "pct"),
    "pluviometrie": (0.0, 48.0, "mm"),
    "conductivite": (0.2, 3.4, "dS_m"),
}

FORMATS_DATE = [
    lambda d: d.strftime("%Y-%m-%d %H:%M:%S"),
    lambda d: d.strftime("%d/%m/%Y %H:%M"),
    lambda d: d.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
]

# Casse incohérente des entêtes : fait partie du piège
ENTETES_A = ["releve_id", "Station", "DATE_HEURE", "grandeur", "Valeur", "unite", "capteur_serie"]


def _valeur(grandeur: str) -> float:
    bas, haut, _ = PROFILS[grandeur]
    return round(RNG.uniform(bas, haut), 2)


def generer_csv(chemin: str, n: int = 4200) -> None:
    lignes = []
    horodatage = DEBUT
    bloque_restant = 0
    valeur_bloquee = 0.0

    for i in range(n):
        horodatage += timedelta(minutes=RNG.choice([10, 15, 20, 30]))
        station = RNG.choice(STATIONS_A)
        grandeur = RNG.choice(list(PROFILS))
        unite = PROFILS[grandeur][2]
        valeur = _valeur(grandeur)

        # Capteur bloqué : 14 relevés identiques d'affilée
        if bloque_restant > 0:
            valeur = valeur_bloquee
            bloque_restant -= 1
        elif RNG.random() < 0.004:
            bloque_restant = 14
            valeur_bloquee = valeur

        # Températures en Fahrenheit pour ~7 % des lignes, unité ANNONCÉE ici
        if grandeur == "temperature" and RNG.random() < 0.07:
            valeur = round(valeur * 9 / 5 + 32, 2)
            unite = "degF"

        # Pluviométrie parfois en 1/10 mm, unité annoncée
        if grandeur == "pluviometrie" and RNG.random() < 0.12:
            valeur = round(valeur * 10, 1)
            unite = "dmm"

        d = horodatage
        # 2 relevés dans le futur (piège secondaire n°1)
        if i in (1337, 3901):
            d = datetime.now(timezone.utc) + timedelta(days=RNG.randint(40, 120))

        lignes.append({
            "releve_id": f"A-{i:06d}",
            "Station": station if RNG.random() > 0.01 else station.lower(),
            "DATE_HEURE": RNG.choice(FORMATS_DATE)(d),
            "grandeur": grandeur if RNG.random() > 0.03 else grandeur.upper(),
            "Valeur": str(valeur).replace(".", ","),
            "unite": unite,
            "capteur_serie": f"SN{RNG.randint(10000, 99999)}",
        })

    # Doublons exacts
    for _ in range(45):
        lignes.append(dict(RNG.choice(lignes)))
    RNG.shuffle(lignes)

    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    # BOM volontaire (piège secondaire n°4)
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ENTETES_A, delimiter=";")
        w.writeheader()
        w.writerows(lignes)
    print(f"  station_A_releves.csv : {len(lignes)} lignes")


def generer_json(chemin: str, n: int = 3800) -> None:
    horodatage = DEBUT
    immediates, differees = [], []

    for i in range(n):
        horodatage += timedelta(minutes=RNG.choice([5, 10, 15]))
        grandeur = RNG.choice(list(PROFILS))
        valeur = _valeur(grandeur)
        unite = PROFILS[grandeur][2]

        # Humidités en fraction 0-1 pour ~20 %, unité annoncée
        if grandeur.startswith("humidite") and RNG.random() < 0.20:
            valeur = round(valeur / 100, 4)
            unite = "ratio"

        # PIÈGE n°2 : Fahrenheit NON annoncé, unite reste "degC"
        if grandeur == "temperature" and RNG.random() < 0.05:
            valeur = round(valeur * 9 / 5 + 32, 2)
            unite = "degC"

        station = RNG.choice(STATIONS_B)
        # PIÈGE n°3 : station fantôme absente du référentiel
        if RNG.random() < 0.012:
            station = "STB-99"

        enr = {
            "id": f"B-{i:06d}",
            "station": {"code": station, "firmware": f"2.{RNG.randint(1, 9)}.{RNG.randint(0, 9)}"},
            "ts": horodatage.isoformat(),
            "fuseau": RNG.choice(["UTC", "Africa/Porto-Novo"]),
            "mesure": {"type": grandeur, "valeur": valeur, "unite": unite},
            "batterie_pct": RNG.randint(12, 100),
        }
        # Un tiers des relevés arrive en différé
        (differees if RNG.random() < 0.33 else immediates).append(enr)

    doc = {
        "schema": "station-b/v2",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "mesures": immediates,
        "mesures_differees": differees,
    }
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"  station_B_releves.json : {len(immediates)} immédiates + {len(differees)} différées")


def generer_reference(chemin: str) -> None:
    lignes = []
    for code in STATIONS_A + STATIONS_B:  # STB-99 volontairement absent
        lignes.append({
            "code_station": code,
            "commune": RNG.choice(["Parakou", "Djougou", "Bohicon", "Natitingou", "Glazoué"]),
            "latitude": round(RNG.uniform(6.4, 11.2), 5),
            "longitude": round(RNG.uniform(1.6, 3.4), 5),
            "altitude_m": RNG.randint(20, 480),
            "date_installation": (DEBUT - timedelta(days=RNG.randint(200, 1400))).strftime("%Y-%m-%d"),
        })
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0]), delimiter=";")
        w.writeheader()
        w.writerows(lignes)
    print(f"  stations_reference.csv : {len(lignes)} stations (STB-99 volontairement absente)")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    print("Génération des sources TP1 :")
    generer_csv(os.path.join(DATA, "station_A_releves.csv"))
    generer_json(os.path.join(DATA, "station_B_releves.json"))
    generer_reference(os.path.join(DATA, "stations_reference.csv"))
    print("\nTerminé. Lance ensuite le serveur de la station C :")
    print("    python faux_api.py")
