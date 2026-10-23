from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from config import ROOT, settings

_AUTH_LOG_PATH = ROOT / "logs" / "auth.log"


def _setup_auth_logger() -> logging.Logger:
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("talentdesk.auth")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        _AUTH_LOG_PATH, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


AUTH_LOGGER = _setup_auth_logger()


def _allowed_users() -> set[str]:
    raw = settings.ldap_allowed_users
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def _is_user_allowed(username: str) -> bool:
    allowed = _allowed_users()
    if not allowed:
        return True
    norm = username.strip().lower()
    if norm in allowed:
        return True
    if "@" not in norm and settings.ldap_domain:
        return f"{norm}@{settings.ldap_domain.lower()}" in allowed
    return False


def ldap_bind(username: str, password: str) -> tuple[bool, list[str]]:
    if not username.strip() or not password:
        return False, []
    if not _is_user_allowed(username):
        return False, []
    if not settings.ldap_server or not settings.ldap_domain:
        return False, []

    bare = username.strip().split("@")[0]
    principal = bare if "@" in username.strip() else f"{bare}@{settings.ldap_domain}"

    try:
        from ldap3 import SIMPLE, Connection, Server

        server = Server(settings.ldap_server)
        conn = Connection(server, user=principal, password=password, authentication=SIMPLE)
        ok = conn.bind()
        if not ok:
            return False, []

        groups: list[str] = []
        try:
            search_base = ",".join(f"DC={p}" for p in settings.ldap_domain.split("."))
            conn.search(
                search_base=search_base,
                search_filter=f"(sAMAccountName={bare})",
                attributes=["memberOf"],
            )
            if conn.entries:
                for dn in conn.entries[0]["memberOf"].values:
                    first_part = str(dn).split(",")[0]
                    if first_part.upper().startswith("CN="):
                        groups.append(first_part[3:])
        except Exception:
            pass  # login still succeeds without group info

        conn.unbind()
        return True, groups
    except Exception:
        return False, []
