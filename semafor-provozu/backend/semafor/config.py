"""Konfigurace aplikace.

Hodnoty se čtou z proměnných prostředí s prefixem ``SEMAFOR_`` nebo ze souboru
``.env`` vedle procesu (cestu lze změnit proměnnou ``SEMAFOR_ENV_FILE``).
Před ním se načte sdílený ``.env`` celého workspace (``C:\\jja\\.env``, cesta
v ``SEMAFOR_SHARED_ENV_FILE``) se společnými hodnotami, např. ``ENTRA_*``;
vlastní ``.env`` aplikace má přednost. Vzor všech hodnot je v ``deploy/env.example``.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["production", "test", "development"]
AuthMode = Literal["oidc", "ldap", "dev"]
MailTransport = Literal["log", "smtp", "graph"]

DEFAULT_DEV_USERS = {
    "alice": {"id": "dev-alice", "email": "alice@hranipex.com", "name": "Alice Testová", "roles": ["Semafor.Admin"]},
    "bob": {"id": "dev-bob", "email": "bob@hranipex.com", "name": "Bob Zkušební", "roles": ["Semafor.User"]},
    "cyril": {"id": "dev-cyril", "email": "cyril@hranipex.com", "name": "Cyril Čtenář", "roles": ["Semafor.Reader"]},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEMAFOR_",
        env_file=(
            os.environ.get("SEMAFOR_SHARED_ENV_FILE", str(Path(__file__).resolve().parents[3] / ".env")),
            os.environ.get("SEMAFOR_ENV_FILE", ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ---- prostředí a adresa ----
    environment: Environment = "development"
    # Veřejná adresa aplikace tak, jak ji vidí prohlížeč (včetně cesty, např. https://apps.hranipex.local/semafor).
    # Z její cesty se odvozuje base path; redirect URI pro Entra ID je public_url + "/auth/callback".
    public_url: str = "http://localhost:8000"

    # ---- databáze ----
    # SQL Server: mssql+pyodbc://@SERVER/DB?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&Encrypt=yes
    database_url: str = "sqlite:///./semafor.db"
    db_pool_size: int = 10
    db_echo: bool = False

    # ---- relace a přihlášení ----
    auth_mode: AuthMode = "oidc"
    session_secret: str = ""
    session_max_age_s: int = 10 * 3600
    # lax = běžné použití; none = jen pro vložení do rámu (záložka Teams), vyžaduje https
    session_same_site: Literal["lax", "strict", "none"] = "lax"
    # Entra ID: vlastní SEMAFOR_OIDC_* mají přednost před sdílenými ENTRA_* ze společného .env
    oidc_tenant_id: str = Field("", validation_alias=AliasChoices("SEMAFOR_OIDC_TENANT_ID", "ENTRA_TENANT_ID"))
    oidc_client_id: str = Field("", validation_alias=AliasChoices("SEMAFOR_OIDC_CLIENT_ID", "ENTRA_CLIENT_ID"))
    oidc_client_secret: str = Field("", validation_alias=AliasChoices("SEMAFOR_OIDC_CLIENT_SECRET", "ENTRA_CLIENT_SECRET"))
    # LDAP (Active Directory): přechodné přihlášení, dokud není registrace v Entra ID.
    # server: "hranipex.net" nebo "ldaps://hranipex.net"; domain: přípona UPN a základ hledání (DC=hranipex,DC=net)
    ldap_server: str = ""
    ldap_domain: str = ""
    # role podle uživatelského jména v AD (nebo e-mailu), seznam oddělený čárkou
    ldap_admins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ldap_users: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ldap_readers: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Výjimka pro provoz bez TLS (router zatím jen HTTP). Po nasazení certifikátu vypnout.
    allow_insecure_http: bool = False
    role_admin: str = "Semafor.Admin"
    role_user: str = "Semafor.User"
    role_reader: str = "Semafor.Reader"
    # Bez přiřazené role se uživatel nepustí dál (doporučeno i "Assignment required" v Entra ID).
    require_role: bool = True
    dev_users: dict[str, dict] = Field(default_factory=lambda: dict(DEFAULT_DEV_USERS))

    # ---- adresář lidí (našeptávač vlastníka) ----
    # True = hledání i v Entra ID přes Microsoft Graph (aplikační oprávnění User.ReadBasic.All).
    graph_directory_search: bool = False

    # ---- limity ----
    max_doc_bytes: int = 256 * 1024
    max_upload_bytes: int = 20 * 1024 * 1024
    max_svg_bytes: int = 2 * 1024 * 1024
    max_lease_ttl_ms: int = 5 * 60 * 1000

    # ---- prohlížeč ----
    # Kdo smí stránku vložit do rámu (Content-Security-Policy frame-ancestors). Pro záložku v Teams doplnit Teams domény.
    frame_ancestors: str = "'self'"
    allow_google_fonts: bool = True

    # ---- živé změny ----
    change_poll_interval_s: float = 1.0
    sse_heartbeat_s: float = 15.0
    # proud se po této době ukončí a prohlížeč se připojí znovu (proxy často ruší dlouhá spojení samy)
    sse_max_duration_s: float = 600.0

    # ---- notifikace (vypnuté, dokud se výslovně nezapnou) ----
    notify_enabled: bool = False
    notify_transport: MailTransport = "log"
    notify_from: str = ""
    # seznam adres oddělený čárkou (nebo JSON pole)
    notify_daily_summary_to: Annotated[list[str], NoDecode] = Field(default_factory=list)
    notify_copy_overdue_to: Annotated[list[str], NoDecode] = Field(default_factory=list)
    notify_max_mails_per_run: int = 25
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""

    # ---- logování ----
    log_level: str = "INFO"
    log_dir: str = ""

    @field_validator("dev_users", mode="before")
    @classmethod
    def _parse_dev_users(cls, v):
        return json.loads(v) if isinstance(v, str) and v.strip() else v

    @field_validator("notify_daily_summary_to", "notify_copy_overdue_to", "ldap_admins", "ldap_users", "ldap_readers",
                     mode="before")
    @classmethod
    def _parse_list(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("public_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @model_validator(mode="after")
    def _check_production(self):
        if self.auth_mode == "dev" and self.environment != "development":
            # vývojové přihlášení bez hesla nesmí běžet na žádném serveru dostupném z firemní sítě (ani TEST)
            raise ValueError("SEMAFOR_AUTH_MODE=dev je povolený jen se SEMAFOR_ENVIRONMENT=development")
        if self.session_same_site == "none" and not self.public_url.startswith("https://"):
            raise ValueError("SEMAFOR_SESSION_SAME_SITE=none vyžaduje https")
        if self.environment == "production":
            if len(self.session_secret) < 32:
                raise ValueError("SEMAFOR_SESSION_SECRET musí mít v produkci alespoň 32 znaků")
            if not self.public_url.startswith("https://") and not self.allow_insecure_http:
                raise ValueError("SEMAFOR_PUBLIC_URL musí být v produkci https:// (výjimka: SEMAFOR_ALLOW_INSECURE_HTTP=true)")
        if self.auth_mode == "ldap" and not (self.ldap_server and self.ldap_domain):
            raise ValueError("chybí konfigurace LDAP: SEMAFOR_LDAP_SERVER a SEMAFOR_LDAP_DOMAIN")
        if self.auth_mode == "oidc" and self.environment != "development":
            missing = [n for n in ("oidc_tenant_id", "oidc_client_id", "oidc_client_secret") if not getattr(self, n)]
            if missing:
                raise ValueError("chybí konfigurace Entra ID: " + ", ".join("SEMAFOR_" + m.upper() for m in missing))
        if not self.session_secret:
            # vývoj: náhodné tajemství na běh procesu (relace po restartu přestanou platit)
            self.session_secret = os.urandom(32).hex()
        return self

    @property
    def base_path(self) -> str:
        """Cesta, pod kterou aplikace běží ("" nebo např. "/semafor")."""
        return urlsplit(self.public_url).path.rstrip("/")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
