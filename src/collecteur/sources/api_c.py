

from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Final

import requests

from collecteur.domaine import Grandeur, Qualite, Releve
from collecteur.erreurs import PayloadInvalide, ReleveIncoherent, SourceIndisponible
from collecteur.normalisation import normaliser_unite, parser_horodatage
from collecteur.reseau import PolitiqueRetry, avec_retry
from collecteur.sources.base import SourceReleves, StatistiquesLecture

__all__ = ["RECUPERABLES", "LecteurAPI"]

_journal: Final = logging.getLogger(__name__)

RECUPERABLES: Final[tuple[type[BaseException], ...]] = (
    requests.RequestException,
    PayloadInvalide,
)

_TAILLE_MAX: Final[int] = 500
_CODES_RECUPERABLES: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})


class LecteurAPI:

    nom = "C"

    def __init__(
        self,
        url_base: str = "http://127.0.0.1:8777",
        *,
        taille_page: int = 100,
        politique: PolitiqueRetry | None = None,
        session: requests.Session | None = None,
        alea: random.Random | None = None,
        page_depart: int = 0,
    ) -> None:
        self.url_base: str = url_base.rstrip("/")
        self.taille_page: int = min(taille_page, _TAILLE_MAX)
        self.politique: PolitiqueRetry = politique or PolitiqueRetry()
        self.session: requests.Session = session or requests.Session()
        self.alea: random.Random | None = alea
        self.page_depart: int = page_depart
        self.statistiques: StatistiquesLecture = StatistiquesLecture(source=self.nom)
        self.pages_abandonnees: list[int] = []



    def lire(self) -> Iterator[Releve]:

        vus: set[str] = set()
        page = self.page_depart
        pages_total: int | None = None

        while pages_total is None or page < pages_total:
            try:
                charge = self._lire_page(page)
            except SourceIndisponible as erreur:
                self.statistiques.rejeter("page_abandonnee")
                self.pages_abandonnees.append(page)
                _journal.error("page %d abandonnée : %s", page, erreur)
                page += 1
                continue

            self.statistiques.pages += 1
            if pages_total is None:
                pages_total = _entier(charge.get("pages_total"))
                if pages_total is None:
                    raise PayloadInvalide(
                        self.nom, page=page, raison="Champ pages_total absent"
                    )

            yield from self._releves_de_page(charge, page, vus)
            page += 1

    def lire_pages(self, numeros: Iterable[int]) -> Iterator[Releve]:

        vus: set[str] = set()
        for page in numeros:
            try:
                charge = self._lire_page(page)
            except SourceIndisponible as erreur:
                self.statistiques.rejeter("page_abandonnee")
                self.pages_abandonnees.append(page)
                _journal.error("page %d toujours indisponible : %s", page, erreur)
                continue
            self.statistiques.pages += 1
            yield from self._releves_de_page(charge, page, vus)

    def _releves_de_page(
        self,
        charge: Mapping[str, object],
        page: int,
        vus: set[str],
    ) -> Iterator[Releve]:
        releves = charge.get("releves")
        if not isinstance(releves, list):
            raise PayloadInvalide(
                self.nom, page=page, raison="Champ releves absent ou mal typé"
            )

        for brut in releves:
            self.statistiques.lus += 1
            if not isinstance(brut, Mapping):
                self.statistiques.rejeter("enregistrement_non_objet")
                continue

            identifiant = str(brut.get("releve_id", "")).strip()
            if identifiant in vus:
                self.statistiques.dupliques += 1
                continue

            try:
                releve = self._construire(brut)
            except ReleveIncoherent as erreur:
                self.statistiques.rejeter(erreur.raison)
                _journal.debug("relevé rejeté : %s", erreur)
                continue
            except (KeyError, TypeError, ValueError) as erreur:
                self.statistiques.rejeter(type(erreur).__name__)
                continue

            vus.add(releve.releve_id)
            self.statistiques.emis += 1
            yield releve

    def stations(self) -> list[dict[str, object]]:
        charge = self._requete_json("/stations", {})
        stations = charge.get("stations")
        if not isinstance(stations, list):
            raise PayloadInvalide(self.nom, raison="Champ stations absent")
        return [s for s in stations if isinstance(s, dict)]

    def sante(self) -> Mapping[str, object]:
        return self._requete_json("/health", {})


    def _lire_page(self, page: int) -> Mapping[str, object]:
        def tenter() -> Mapping[str, object]:
            return self._requete_json(
                "/releves", {"page": page, "taille": self.taille_page}, page=page
            )

        def compter(tentative: int, erreur: BaseException) -> None:
            del tentative, erreur
            self.statistiques.retentes += 1

        return avec_retry(
            tenter,
            politique=self.politique,
            source=self.nom,
            description=f"{self.url_base}/releves?page={page}",
            recuperables=RECUPERABLES,
            alea=self.alea,
            au_reessai=compter,
        )

    def _requete_json(
        self,
        chemin: str,
        parametres: Mapping[str, str | int],
        *,
        page: int | None = None,
    ) -> Mapping[str, object]:
        reponse = self.session.get(
            f"{self.url_base}{chemin}",
            params=dict(parametres),
            timeout=self.politique.timeout_s,
        )

        if reponse.status_code in _CODES_RECUPERABLES:
            raise PayloadInvalide(
                self.nom,
                page=page,
                raison=f"HTTP {reponse.status_code}",
                octets_recus=len(reponse.content),
            )
        reponse.raise_for_status()

        try:
            charge = json.loads(reponse.text)
        except json.JSONDecodeError as erreur:
            raise PayloadInvalide(
                self.nom,
                page=page,
                octets_recus=len(reponse.content),
                apercu=reponse.text[-120:],
                raison=f"JSON tronqué ({erreur.msg} en position {erreur.pos})",
            ) from None

        if not isinstance(charge, dict):
            raise PayloadInvalide(self.nom, page=page, raison="Réponse non objet")
        return charge

    def _construire(self, brut: Mapping[str, object]) -> Releve:
        releve_id = str(brut["releve_id"]).strip()

        horodatage = parser_horodatage(
            str(brut["horodatage_utc"]),
            releve_id=releve_id,
            source=self.nom,
        )

        unite_brute = str(brut["unite"])
        valeur, unite = normaliser_unite(
            float(str(brut["valeur"])),
            unite_brute,
            releve_id=releve_id,
            source=self.nom,
        )
        if unite != unite_brute.strip():
            self.statistiques.unites_converties += 1

        degrade = str(brut.get("qualite_capteur", "ok")).strip().lower() == "degrade"

        return Releve.creer(
            releve_id=releve_id,
            station=str(brut["station_code"]),
            horodatage=horodatage,
            grandeur=Grandeur.depuis_texte(str(brut["grandeur"]), source=self.nom),
            valeur=valeur,
            unite=unite,
            qualite=Qualite.SUSPECTE if degrade else Qualite.VALIDE,
            source=self.nom,
        )

    def __repr__(self) -> str:
        return f"LecteurAPI({self.url_base!r}, taille_page={self.taille_page})"


def _entier(valeur: object) -> int | None:
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else None


if TYPE_CHECKING:

    def _conforme(lecteur: LecteurAPI) -> SourceReleves:
        return lecteur
