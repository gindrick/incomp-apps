"""Přihlášení přes Active Directory (LDAP), přechodně do registrace v Entra ID.

Heslo se ověří bindem pod účtem uživatele, potom se z AD přečte jeho e-mail
a jméno. Identitou (``id``) je firemní e-mail: na něj převádí vlastnictví
i migrace dat z artefaktu. Role se berou ze seznamů v konfiguraci při každém
požadavku, takže odebrání ze seznamu platí hned po restartu služby.
"""
from __future__ import annotations

import logging

from ldap3 import SIMPLE, SUBTREE, Connection, Server
from ldap3.utils.conv import escape_filter_chars

from .config import Settings

log = logging.getLogger(__name__)
TIMEOUT_S = 10


def normalize_username(raw: str) -> str:
    """``HRANIPEX\\jan.kratky``, ``jan.kratky@hranipex.net`` i ``Jan.Kratky`` → ``jan.kratky``."""
    return raw.strip().split("\\")[-1].split("@")[0].strip().lower()


def _search_base(domain: str) -> str:
    return ",".join(f"DC={part}" for part in domain.split("."))


def connect(settings: Settings, upn: str, password: str) -> Connection:
    server = Server(settings.ldap_server, connect_timeout=TIMEOUT_S)
    return Connection(server, user=upn, password=password, authentication=SIMPLE, receive_timeout=TIMEOUT_S)


def authenticate(settings: Settings, username: str, password: str) -> dict | None:
    """Vrátí claims pro relaci, nebo None při špatném jménu/hesle.

    Nedostupný server se nepřekládá na „špatné heslo“: ``LDAPException`` jde k volajícímu.
    """
    sam = normalize_username(username)
    if not sam or not password:  # prázdné heslo = anonymní bind, ten AD „ověří“ vždy
        return None
    conn = connect(settings, f"{sam}@{settings.ldap_domain}", password)
    try:
        if not conn.bind():
            return None
        conn.search(_search_base(settings.ldap_domain), f"(sAMAccountName={escape_filter_chars(sam)})",
                    SUBTREE, attributes=["mail", "displayName"])
        attrs = conn.entries[0].entry_attributes_as_dict if conn.entries else {}
    finally:
        if conn.bound:
            conn.unbind()
    email = str((attrs.get("mail") or [""])[0]).strip().lower()
    if not email:
        log.warning("LDAP: účet %s nemá v AD e-mail, přihlášení odmítnuto", sam)
        return None
    name = str((attrs.get("displayName") or [sam])[0])
    return {"id": email, "email": email, "name": name, "username": sam}


def roles_for(settings: Settings, username: str, email: str) -> list[str]:
    who = {username.lower(), email.lower()}
    grants = ((settings.ldap_admins, settings.role_admin),
              (settings.ldap_users, settings.role_user),
              (settings.ldap_readers, settings.role_reader))
    return [role for names, role in grants if who & {n.strip().lower() for n in names}]
