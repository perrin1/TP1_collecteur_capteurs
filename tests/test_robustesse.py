

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Never

import pytest
import requests

from collecteur.domaine import Qualite
from collecteur.erreurs import ConfigurationInvalide, PayloadInvalide, SourceIndisponible
from collecteur.file_attente import FileHorsLigne, RequeteDifferee
from collecteur.journalisation import FormateurJSON
from collecteur.reseau import PolitiqueRetry, avec_retry
from collecteur.sources.api_c import RECUPERABLES, LecteurAPI
from collecteur.stockage import Entrepot
from tests.conftest import releve


def test_delais_suivent_une_progression_geometrique() -> None:
    politique = PolitiqueRetry(
        tentatives_max=5, delai_initial_s=1.0, facteur=2.0, delai_max_s=16.0, gigue=0.0
    )
    assert list(politique.delais()) == [1.0, 2.0, 4.0, 8.0]


def test_delais_plafonnes() -> None:
    politique = PolitiqueRetry(
        tentatives_max=6, delai_initial_s=1.0, facteur=10.0, delai_max_s=5.0, gigue=0.0
    )
    assert list(politique.delais()) == [1.0, 5.0, 5.0, 5.0, 5.0]


def test_gigue_desynchronise_sans_depasser_la_borne() -> None:
    politique = PolitiqueRetry(delai_initial_s=10.0, gigue=0.1, facteur=1.0, delai_max_s=10.0)
    delais = list(politique.delais(alea=random.Random(7)))
    assert all(9.0 <= d <= 11.0 for d in delais)
    assert len(set(delais)) > 1


@pytest.mark.parametrize(
    ("parametre", "valeur"),
    [("tentatives_max", 0), ("facteur", 0.5), ("gigue", 2.0), ("timeout_s", 0.0)],
)
def test_configuration_invalide_refusee(parametre: str, valeur: float) -> None:
    with pytest.raises(ConfigurationInvalide):
        PolitiqueRetry(**{parametre: valeur})  # type: ignore[arg-type]


def test_retry_rejoue_puis_reussit() -> None:
    appels = {"n": 0}
    dormi: list[float] = []

    def instable() -> str:
        appels["n"] += 1
        if appels["n"] < 3:
            raise PayloadInvalide("C", page=1, raison="JSON tronqué")
        return "ok"

    resultat = avec_retry(
        instable,
        politique=PolitiqueRetry(tentatives_max=5, delai_initial_s=1.0, gigue=0.0),
        source="C",
        description="/releves?page=1",
        recuperables=RECUPERABLES,
        dormir=dormi.append,
    )

    assert resultat == "ok"
    assert appels["n"] == 3
    assert dormi == [1.0, 2.0]  # a « attendu » sans attendre


def test_retry_abandonne_proprement() -> None:
    def toujours_ko() -> Never:
        raise requests.ConnectionError("injoignable")

    politique = PolitiqueRetry(tentatives_max=3, delai_initial_s=0.0, gigue=0.0)
    with pytest.raises(SourceIndisponible) as capture:
        avec_retry(
            toujours_ko,
            politique=politique,
            source="C",
            description="/releves?page=4",
            recuperables=RECUPERABLES,
            dormir=lambda _: None,
        )

    erreur = capture.value
    assert erreur.tentatives == 3
    assert erreur.source == "C"
    assert isinstance(erreur.cause, requests.ConnectionError)


def test_erreur_non_recuperable_remonte_immediatement() -> None:
    appels = {"n": 0}

    def bug() -> Never:
        appels["n"] += 1
        raise ZeroDivisionError

    with pytest.raises(ZeroDivisionError):
        avec_retry(
            bug,
            politique=PolitiqueRetry(tentatives_max=5),
            source="C",
            description="x",
            recuperables=RECUPERABLES,
            dormir=lambda _: None,
        )
    assert appels["n"] == 1  # aucune reprise sur un vrai défaut de programmation



class _ReponseFactice:
    def __init__(self, texte: str, code: int = 200) -> None:
        self.text = texte
        self.status_code = code
        self.content = texte.encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _SessionFactice:
    """Rejoue une liste de réponses préparées, dans l'ordre."""

    def __init__(self, reponses: list[_ReponseFactice]) -> None:
        self.reponses = reponses
        self.appels: list[dict[str, object]] = []

    def get(self, url: str, params: dict[str, object] | None = None, timeout: float = 0) -> _ReponseFactice:
        self.appels.append({"url": url, "params": params, "timeout": timeout})
        return self.reponses.pop(0) if self.reponses else _ReponseFactice("{}", 503)


def _page(numero: int, identifiants: list[str], pages_total: int = 1) -> str:
    return json.dumps(
        {
            "page": numero,
            "taille": 100,
            "total": len(identifiants),
            "pages_total": pages_total,
            "releves": [
                {
                    "releve_id": i,
                    "station_code": "STC-21",
                    "horodatage_utc": "2026-03-01T00:00:00Z",
                    "grandeur": "temperature",
                    "valeur": 27.4,
                    "unite": "C",
                    "qualite_capteur": "ok",
                }
                for i in identifiants
            ],
        }
    )


def test_api_dedoublonne_dans_une_page() -> None:
    session = _SessionFactice([_ReponseFactice(_page(0, ["C-1", "C-2", "C-1", "C-2"]))])
    lecteur = LecteurAPI("http://test", session=session)  # type: ignore[arg-type]

    releves = list(lecteur.lire())

    assert [r.releve_id for r in releves] == ["C-1", "C-2"]
    assert lecteur.statistiques.dupliques == 2
    assert lecteur.statistiques.lus == 4


def test_api_rejoue_un_payload_tronque() -> None:
    tronque = _page(0, ["C-1"])[: len(_page(0, ["C-1"])) // 2]
    session = _SessionFactice(
        [_ReponseFactice(tronque), _ReponseFactice(_page(0, ["C-1"]))]
    )
    lecteur = LecteurAPI(
        "http://test",
        session=session,  # type: ignore[arg-type]
        politique=PolitiqueRetry(tentatives_max=3, delai_initial_s=0.0, gigue=0.0),
    )

    releves = list(lecteur.lire())

    assert len(releves) == 1
    assert lecteur.statistiques.retentes == 1


def test_api_abandonne_une_page_sans_arreter_la_collecte() -> None:
    session = _SessionFactice(
        [
            _ReponseFactice(_page(0, ["C-1"], pages_total=2)),
            *[_ReponseFactice("{}", 503) for _ in range(3)],
        ]
    )
    lecteur = LecteurAPI(
        "http://test",
        session=session,  # type: ignore[arg-type]
        politique=PolitiqueRetry(tentatives_max=3, delai_initial_s=0.0, gigue=0.0),
    )

    releves = list(lecteur.lire())

    assert len(releves) == 1
    assert lecteur.pages_abandonnees == [1]


def test_capteur_degrade_marque_suspect() -> None:
    charge = json.loads(_page(0, ["C-1"]))
    charge["releves"][0]["qualite_capteur"] = "degrade"
    session = _SessionFactice([_ReponseFactice(json.dumps(charge))])
    lecteur = LecteurAPI("http://test", session=session)  # type: ignore[arg-type]

    (releve_lu,) = list(lecteur.lire())
    assert releve_lu.qualite is Qualite.SUSPECTE




def test_deux_ecritures_identiques_ne_dupliquent_pas(tmp_path: Path) -> None:
    """La preuve F2, en test : deux exécutions, même compte de lignes."""
    releves = [releve(f"A-{i}", heure=i % 24, jour=1 + i // 24) for i in range(50)]

    with Entrepot(tmp_path / "collecte.db") as entrepot:
        premier = entrepot.enregistrer(releves)
        compte_apres_un = entrepot.compter()

        second = entrepot.enregistrer(releves)
        compte_apres_deux = entrepot.compter()

    assert premier.inseres == 50
    assert compte_apres_un == 50
    assert second.inseres == 0
    assert second.deja_vus == 50
    assert compte_apres_deux == 50


def test_valeur_corrigee_met_a_jour_sans_dupliquer(tmp_path: Path) -> None:
    with Entrepot(tmp_path / "collecte.db") as entrepot:
        entrepot.enregistrer([releve("A-1", valeur=25.0)])
        resultat = entrepot.enregistrer([releve("A-1", valeur=26.0)])

        assert entrepot.compter() == 1
        assert resultat.inseres == 0
        assert resultat.mis_a_jour == 1
        (relu,) = list(entrepot.releves())
        assert relu.valeur == pytest.approx(26.0)


def test_reprise_apres_interruption_ne_perd_rien(tmp_path: Path) -> None:
    tous = [releve(f"A-{i}", heure=i % 24, jour=1 + i // 24) for i in range(30)]

    def flux_qui_casse() -> object:
        for indice, r in enumerate(tous):
            if indice == 20:
                raise requests.ConnectionError("coupure réseau")
            yield r

    with Entrepot(tmp_path / "collecte.db") as entrepot:
        with pytest.raises(requests.ConnectionError):
            entrepot.enregistrer(flux_qui_casse())  # type: ignore[arg-type]

        assert entrepot.compter() == 0

        entrepot.enregistrer(tous)
        assert entrepot.compter() == 30


def test_comptes_par_source_et_qualite(tmp_path: Path) -> None:
    with Entrepot(tmp_path / "collecte.db") as entrepot:
        entrepot.enregistrer(
            [
                releve("A-1", source="A"),
                releve("B-1", source="B", station="STB-11"),
                releve("B-2", source="B", station="STB-11", qualite=Qualite.SUSPECTE),
            ]
        )
        assert entrepot.comptes_par_source() == {"A": 1, "B": 2}
        assert entrepot.comptes_par_qualite() == {"suspecte": 1, "valide": 2}
        assert entrepot.compter(qualite=Qualite.SUSPECTE) == 1


def test_series_bloquees_en_sql(tmp_path: Path) -> None:
    with Entrepot(tmp_path / "collecte.db") as entrepot:
        entrepot.enregistrer(
            [releve(f"A-{i}", heure=i % 24, jour=1 + i // 24, valeur=21.0) for i in range(15)]
        )
        series = entrepot.series_bloquees_sql(longueur_min=12)
        assert len(series) == 1
        assert series[0][2] == 15



def test_file_survit_au_redemarrage(tmp_path: Path) -> None:
    chemin = tmp_path / "file" / "requetes.jsonl"
    FileHorsLigne(chemin).empiler(
        RequeteDifferee(source="C", cible="/releves", parametres={"page": 17})
    )

    relue = list(FileHorsLigne(chemin))
    assert len(relue) == 1
    assert relue[0].parametres == {"page": 17}


def test_file_ne_duplique_pas_la_meme_requete(tmp_path: Path) -> None:
    file = FileHorsLigne(tmp_path / "requetes.jsonl")
    requete = RequeteDifferee(source="C", cible="/releves", parametres={"page": 3})

    assert file.empiler(requete) is True
    assert file.empiler(requete) is False
    assert len(file) == 1


def test_ligne_tronquee_ignoree_sans_perdre_les_autres(tmp_path: Path) -> None:
    chemin = tmp_path / "requetes.jsonl"
    file = FileHorsLigne(chemin)
    file.empiler(RequeteDifferee(source="C", cible="/releves", parametres={"page": 1}))
    with chemin.open("a", encoding="utf-8") as fichier:
        fichier.write('{"source": "C", "cible": "/rele')

    requetes = list(file)
    assert len(requetes) == 1
    assert file.lignes_corrompues == 1


def test_rejeu_vide_la_file(tmp_path: Path) -> None:
    file = FileHorsLigne(tmp_path / "requetes.jsonl")
    file.empiler(RequeteDifferee(source="C", cible="/releves", parametres={"page": 1}))
    file.empiler(RequeteDifferee(source="C", cible="/releves", parametres={"page": 2}))

    rejouees = list(file.rejouer())

    assert len(rejouees) == 2
    assert len(file) == 0


def test_remplacement_atomique(tmp_path: Path) -> None:
    file = FileHorsLigne(tmp_path / "requetes.jsonl")
    file.empiler(RequeteDifferee(source="C", cible="/releves", parametres={"page": 1}))
    file.remplacer([RequeteDifferee(source="C", cible="/releves", parametres={"page": 9})])

    (restante,) = list(file)
    assert restante.parametres == {"page": 9}
    assert not list(tmp_path.glob(".file-*.tmp"))  # aucun provisoire oublié




def test_journal_json_expose_le_contexte() -> None:
    enregistrement = logging.LogRecord(
        name="collecteur.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="collecte terminée",
        args=(),
        exc_info=None,
    )
    enregistrement.source = "C"
    enregistrement.retentes = 28

    charge = json.loads(FormateurJSON().format(enregistrement))

    assert charge["message"] == "collecte terminée"
    assert charge["source"] == "C"
    assert charge["retentes"] == 28
    assert charge["niveau"] == "INFO"
