"""Přihlášený uživatel (identita ověřená serverem, nikdy ne údaj z formuláře)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    id: str
    email: str
    name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    is_admin: bool = False
    can_edit: bool = False

    @property
    def can_read(self) -> bool:
        return True

    def to_session(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "roles": list(self.roles)}


def principal_from_claims(claims: dict, *, role_admin: str, role_user: str, role_reader: str) -> Principal:
    """Sestaví identitu z claimů (Entra ID token nebo uložená relace)."""
    roles = tuple(str(r) for r in (claims.get("roles") or []))
    is_admin = role_admin in roles
    can_edit = is_admin or role_user in roles
    return Principal(
        id=str(claims["id"]),
        email=str(claims.get("email") or "").strip().lower(),
        name=str(claims.get("name") or ""),
        roles=roles,
        is_admin=is_admin,
        can_edit=can_edit,
    )


def has_any_role(p: Principal, *, role_admin: str, role_user: str, role_reader: str) -> bool:
    return any(r in p.roles for r in (role_admin, role_user, role_reader))


# Systémová identita pro CLI (import, notifikace). Do dat se zapisuje jako "system".
SYSTEM = Principal(id="system", email="system", name="Systém", roles=("system",), is_admin=True, can_edit=True)
