
from __future__ import annotations

__all__ = [
    "CollecteError",
    "ConfigurationInvalide",
    "PayloadInvalide",
    "ReleveIncoherent",
    "SourceIndisponible",
]


class CollecteError(Exception):


    def __init__(self, message: str, **contexte: object) -> None:
        super().__init__(message)
        self.message: str = message
        self.contexte: dict[str, object] = {
            cle: valeur for cle, valeur in contexte.items() if valeur is not None
        }

    def __str__(self) -> str:
        if not self.contexte:
            return self.message
        details = " · ".join(f"{cle}={valeur!r}" for cle, valeur in self.contexte.items())
        return f"{self.message} [{details}]"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self!s})"


class SourceIndisponible(CollecteError):


    def __init__(
        self,
        source: str,
        *,
        url: str | None = None,
        tentatives: int = 0,
        delai_total_s: float = 0.0,
        code_http: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            f"Source {source} injoignable après {tentatives} tentative(s)",
            source=source,
            url=url,
            tentatives=tentatives,
            delai_total_s=round(delai_total_s, 3),
            code_http=code_http,
            cause=type(cause).__name__ if cause is not None else None,
        )
        self.source: str = source
        self.url: str | None = url
        self.tentatives: int = tentatives
        self.delai_total_s: float = delai_total_s
        self.code_http: int | None = code_http
        self.cause: BaseException | None = cause


class PayloadInvalide(CollecteError):


    LONGUEUR_APERCU: int = 200

    def __init__(
        self,
        source: str,
        *,
        page: int | None = None,
        octets_recus: int | None = None,
        apercu: str | None = None,
        raison: str | None = None,
    ) -> None:
        apercu_court = (
            apercu[: self.LONGUEUR_APERCU] + "…"
            if apercu is not None and len(apercu) > self.LONGUEUR_APERCU
            else apercu
        )
        super().__init__(
            f"Contenu invalide reçu de la source {source}",
            source=source,
            page=page,
            octets_recus=octets_recus,
            raison=raison,
            apercu=apercu_court,
        )
        self.source: str = source
        self.page: int | None = page
        self.octets_recus: int | None = octets_recus
        self.apercu: str | None = apercu_court
        self.raison: str | None = raison


class ReleveIncoherent(CollecteError):


    def __init__(
        self,
        raison: str,
        *,
        champ: str | None = None,
        valeur: object = None,
        releve_id: str | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(
            raison,
            champ=champ,
            valeur=valeur,
            releve_id=releve_id,
            source=source,
        )
        self.raison: str = raison
        self.champ: str | None = champ
        self.valeur: object = valeur
        self.releve_id: str | None = releve_id
        self.source: str | None = source


class ConfigurationInvalide(CollecteError):


    def __init__(
        self,
        parametre: str,
        *,
        valeur: object = None,
        attendu: str | None = None,
    ) -> None:
        super().__init__(
            f"Paramètre de configuration invalide : {parametre}",
            parametre=parametre,
            valeur=valeur,
            attendu=attendu,
        )
        self.parametre: str = parametre
        self.valeur: object = valeur
        self.attendu: str | None = attendu
