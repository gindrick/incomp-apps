from __future__ import annotations

from config import settings


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


def ldap_bind(username: str, password: str) -> bool:
    if not username.strip() or not password:
        return False
    if not _is_user_allowed(username):
        return False
    if not settings.ldap_server or not settings.ldap_domain:
        return False

    bare = username.strip().split("@")[0]
    principal = bare if "@" in username.strip() else f"{bare}@{settings.ldap_domain}"

    try:
        from ldap3 import SIMPLE, Connection, Server

        server = Server(settings.ldap_server)
        conn = Connection(server, user=principal, password=password, authentication=SIMPLE)
        ok = conn.bind()
        if ok:
            conn.unbind()
        return ok
    except Exception:
        return False
