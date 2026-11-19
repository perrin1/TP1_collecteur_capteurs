

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

import requests

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from collecteur.erreurs import SourceIndisponible  # noqa: E402
from collecteur.reseau import PolitiqueRetry  # noqa: E402
from collecteur.sources import LecteurAPI  # noqa: E402
from collecteur.stockage import Entrepot  # noqa: E402

SEUIL_LENTEUR_S = 2.0




@contextmanager
def station_c(port: int, *, sain: bool = False) -> Iterator[subprocess.Popen[bytes]]:
    commande = [sys.executable, str(RACINE / "faux_api.py"), "--port", str(port)]
    if sain:
        commande.append("--sain")

    processus = subprocess.Popen(
        commande, cwd=RACINE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        _attendre(port)
        yield processus
    finally:
        processus.terminate()
        try:
            processus.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processus.kill()


def _attendre(port: int, *, limite_s: float = 15.0) -> None:
    echeance = time.monotonic() + limite_s
    while time.monotonic() < echeance:
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                return
        except requests.RequestException:
            time.sleep(0.2)
    raise RuntimeError(f"station C injoignable sur le port {port}")



def mesurer_pannes(appels: int = 200, port: int = 8801) -> Counter[str]:
    comptes: Counter[str] = Counter()
    durees: list[float] = []

    with station_c(port):
        session = requests.Session()
        for numero in range(appels):
            page = numero % 52
            debut = time.monotonic()
            try:
                reponse = session.get(
                    f"http://127.0.0.1:{port}/releves",
                    params={"page": page, "taille": 100},
                    timeout=30,
                )
            except requests.RequestException:
                comptes["erreur_reseau"] += 1
                continue

            duree = time.monotonic() - debut
            durees.append(duree)

            if reponse.status_code == 503:
                comptes["503"] += 1
                continue
            if reponse.status_code != 200:
                comptes[f"http_{reponse.status_code}"] += 1
                continue

            try:
                charge = json.loads(reponse.text)
            except json.JSONDecodeError:
                comptes["payload_tronque"] += 1
                continue

            if duree >= SEUIL_LENTEUR_S:
                comptes["lente"] += 1

            releves = charge.get("releves", [])
            identifiants = [r.get("releve_id") for r in releves]
            if len(identifiants) != len(set(identifiants)):
                comptes["page_avec_doublons"] += 1
                comptes["releves_dupliques"] += len(identifiants) - len(set(identifiants))

            comptes["reponses_exploitables"] += 1

        session.close()

    comptes["appels"] = appels
    comptes["duree_mediane_ms"] = int(sorted(durees)[len(durees) // 2] * 1000) if durees else 0
    return comptes




@dataclass(frozen=True, slots=True)
class Variante:
    nom: str
    politique: PolitiqueRetry
    explication: str


VARIANTES: tuple[Variante, ...] = (
    Variante(
        "sans reprise",
        PolitiqueRetry(tentatives_max=1, timeout_s=15.0),
        "abandonne à la première erreur",
    ),
    Variante(
        "reprise immédiate",
        PolitiqueRetry(tentatives_max=5, delai_initial_s=0.0, facteur=1.0,
                       delai_max_s=0.0, gigue=0.0, timeout_s=15.0),
        "rejoue aussitôt, sans attendre",
    ),
    Variante(
        "backoff constant",
        PolitiqueRetry(tentatives_max=5, delai_initial_s=1.0, facteur=1.0,
                       delai_max_s=1.0, gigue=0.0, timeout_s=15.0),
        "attend 1 s entre chaque tentative",
    ),
    Variante(
        "backoff exponentiel",
        PolitiqueRetry(tentatives_max=5, delai_initial_s=1.0, facteur=2.0,
                       delai_max_s=16.0, gigue=0.1, timeout_s=15.0),
        "1 s, 2 s, 4 s, 8 s — la politique retenue",
    ),
)


def mesurer_backoff(port_depart: int = 8810, taille_page: int = 200) -> list[dict[str, object]]:
    resultats: list[dict[str, object]] = []

    for decalage, variante in enumerate(VARIANTES):
        port = port_depart + decalage
        with station_c(port):
            lecteur = LecteurAPI(
                f"http://127.0.0.1:{port}",
                taille_page=taille_page,
                politique=variante.politique,
            )
            debut = time.monotonic()
            releves = list(lecteur.lire())
            duree = time.monotonic() - debut

        stats = lecteur.statistiques
        resultats.append(
            {
                "variante": variante.nom,
                "explication": variante.explication,
                "duree_s": round(duree, 1),
                "releves": len(releves),
                "pages_lues": stats.pages,
                "pages_perdues": len(lecteur.pages_abandonnees),
                "reprises": stats.retentes,
                "doublons_ecartes": stats.dupliques,
            }
        )
        print(f"  {variante.nom:22s} {duree:6.1f}s  "
              f"{len(releves):5d} relevés  {len(lecteur.pages_abandonnees)} page(s) perdue(s)")

    return resultats




def mesurer_reprise(port: int = 8820, base: Path | None = None) -> dict[str, object]:
    base = base or RACINE / "mesures" / "reprise.db"
    base.unlink(missing_ok=True)

    politique = PolitiqueRetry(tentatives_max=3, delai_initial_s=0.3, facteur=2.0,
                               delai_max_s=2.0, timeout_s=5.0)
    mesure: dict[str, object] = {}

    with station_c(port) as processus:
        lecteur = LecteurAPI(f"http://127.0.0.1:{port}", taille_page=100, politique=politique)

        def couper() -> None:
            time.sleep(3.0)
            processus.terminate()

        tueur = Thread(target=couper, daemon=True)
        tueur.start()

        with Entrepot(base) as entrepot:
            with suppress(SourceIndisponible):
                entrepot.enregistrer(_jusqua_la_coupure(lecteur))
            partiel = entrepot.compter()

        tueur.join()

    mesure["releves_avant_coupure"] = partiel
    mesure["pages_abandonnees"] = len(lecteur.pages_abandonnees)
    print(f"  coupure : {partiel} relevés écrits, "
          f"{len(lecteur.pages_abandonnees)} page(s) mise(s) de côté")

    with station_c(port + 1):
        reprise = LecteurAPI(
            f"http://127.0.0.1:{port + 1}", taille_page=100, politique=politique
        )
        with Entrepot(base) as entrepot:
            entrepot.enregistrer(reprise.lire())
            total = entrepot.compter()
            doublons = entrepot.connexion.execute(
                "SELECT COUNT(*) - COUNT(DISTINCT releve_id) FROM releves"
            ).fetchone()[0]

    mesure["releves_apres_reprise"] = total
    mesure["doublons_en_base"] = int(doublons)
    mesure["attendu"] = 5200
    print(f"  reprise : {total} relevés en base, {doublons} doublon(s)")
    return mesure


def _jusqua_la_coupure(lecteur: LecteurAPI) -> Iterator[object]:
    try:
        yield from lecteur.lire()
    except requests.RequestException:
        return



def main(argv: list[str]) -> int:
    demandes = set(argv) or {"f1", "f3", "f4"}
    rapport: dict[str, object] = {}

    if "f1" in demandes:
        print("\nF1 — comportements de panne sur 200 appels")
        comptes = mesurer_pannes()
        appels = comptes["appels"]
        for nom, attendu in (
            ("503", "~20 %"),
            ("lente", "~10 %"),
            ("payload_tronque", "~8 %"),
            ("page_avec_doublons", "~15 %"),
        ):
            n = comptes[nom]
            print(f"  {nom:20s} {n:4d} / {appels}  = {100 * n / appels:5.1f} %  (annoncé {attendu})")
        print(f"  {'durée médiane':20s} {comptes['duree_mediane_ms']} ms")
        rapport["f1"] = dict(comptes)

    if "f4" in demandes:
        print("\nF4 — délai total selon la politique de reprise")
        rapport["f4"] = mesurer_backoff()

    if "f3" in demandes:
        print("\nF3 — reprise après coupure de l'API")
        rapport["f3"] = mesurer_reprise()

    sortie = RACINE / "mesures" / "resultats.json"
    sortie.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRésultats écrits dans {sortie.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
