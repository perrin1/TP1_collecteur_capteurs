# -*- coding: utf-8 -*-
"""TP1 — Station C : API REST volontairement instable.

Usage :
    python faux_api.py            # écoute sur http://127.0.0.1:8777
    python faux_api.py --port 9000 --sain   # sans pannes, pour comparer

Routes :
    GET /health
    GET /stations
    GET /releves?page=N&taille=100

Comportements de panne (route /releves uniquement) :
    - 503 Service Unavailable        ~20 %
    - réponse lente (2 à 5 s)        ~10 %
    - payload JSON tronqué           ~8 %
    - relevés dupliqués dans la page ~15 %

Aucune dépendance externe : uniquement la bibliothèque standard.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RNG = random.Random(4242)
TOTAL_RELEVES = 5200
TAILLE_MAX = 500
DEBUT = datetime(2026, 3, 1, tzinfo=timezone.utc)

STATIONS = [
    {"code": "STC-21", "commune": "Parakou", "lat": 9.3372, "lon": 2.6303},
    {"code": "STC-22", "commune": "Djougou", "lat": 9.7085, "lon": 1.6660},
    {"code": "STC-23", "commune": "Glazoué", "lat": 7.9777, "lon": 2.2410},
]
GRANDEURS = {
    "temperature": (18.0, 41.0, "C"),
    "humidite_sol": (8.0, 62.0, "%"),
    "humidite_air": (25.0, 98.0, "%"),
    "pluviometrie": (0.0, 48.0, "mm"),
    "conductivite": (0.2, 3.4, "dS/m"),
}

MODE_SAIN = False


def _releve(i: int) -> dict:
    r = random.Random(90000 + i)  # déterministe par index
    grandeur = r.choice(list(GRANDEURS))
    bas, haut, unite = GRANDEURS[grandeur]
    ts = DEBUT + timedelta(minutes=12 * i)
    return {
        "releve_id": f"C-{i:06d}",
        "station_code": r.choice(STATIONS)["code"],
        "horodatage_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "grandeur": grandeur,
        "valeur": round(r.uniform(bas, haut), 2),
        "unite": unite,
        "qualite_capteur": r.choice(["ok", "ok", "ok", "degrade"]),
    }


def _page(page: int, taille: int) -> dict:
    debut = page * taille
    items = [_releve(i) for i in range(debut, min(debut + taille, TOTAL_RELEVES))]
    # Doublons dans ~15 % des pages
    if not MODE_SAIN and items and RNG.random() < 0.15:
        for _ in range(RNG.randint(1, 4)):
            items.append(dict(RNG.choice(items)))
        RNG.shuffle(items)
    return {
        "page": page,
        "taille": taille,
        "total": TOTAL_RELEVES,
        "pages_total": (TOTAL_RELEVES + taille - 1) // taille,
        "releves": items,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # journal compact
        print(f"  [{self.log_date_time_string()}] {fmt % args}")

    def _envoyer(self, code: int, charge: bytes, type_mime: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", f"{type_mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(charge)))
        self.end_headers()
        self.wfile.write(charge)

    def _json(self, code: int, obj) -> None:
        self._envoyer(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/health":
            self._json(200, {"statut": "ok", "mode": "sain" if MODE_SAIN else "instable"})
            return

        if u.path == "/stations":
            self._json(200, {"stations": STATIONS})
            return

        if u.path != "/releves":
            self._json(404, {"erreur": "route inconnue", "chemin": u.path})
            return

        try:
            page = int(q.get("page", ["0"])[0])
            taille = min(int(q.get("taille", ["100"])[0]), TAILLE_MAX)
        except ValueError:
            self._json(400, {"erreur": "parametres invalides"})
            return
        if page < 0 or taille < 1:
            self._json(400, {"erreur": "parametres hors bornes"})
            return

        if not MODE_SAIN:
            tirage = RNG.random()
            if tirage < 0.20:
                self._json(503, {"erreur": "service indisponible", "reessayer_dans_s": 2})
                return
            if tirage < 0.30:
                time.sleep(RNG.uniform(2.0, 5.0))
            elif tirage < 0.38:
                # Payload tronqué : JSON coupé au milieu, Content-Length cohérent
                brut = json.dumps(_page(page, taille), ensure_ascii=False)
                coupe = brut[: int(len(brut) * RNG.uniform(0.35, 0.7))].encode("utf-8")
                self._envoyer(200, coupe)
                return

        self._json(200, _page(page, taille))


def main() -> None:
    global MODE_SAIN
    ap = argparse.ArgumentParser(description="Station C — API instable (TP1)")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--sain", action="store_true", help="désactive toutes les pannes")
    a = ap.parse_args()
    MODE_SAIN = a.sain

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Station C en écoute sur http://127.0.0.1:{a.port}")
    print(f"Mode : {'SAIN (aucune panne)' if MODE_SAIN else 'INSTABLE'}")
    print(f"{TOTAL_RELEVES} relevés disponibles. Ctrl+C pour arrêter.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de la station C.")
        srv.server_close()


if __name__ == "__main__":
    main()
