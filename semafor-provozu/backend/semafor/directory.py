"""Adresář lidí: kdo se přihlásil, jména pro zobrazení, našeptávač vlastníka.

Náhrada schopnosti ``user`` platformy (``me``, ``profiles``, ``search``).
Volitelně hledá i v Entra ID přes Microsoft Graph (aplikační oprávnění
``User.ReadBasic.All``), aby šlo přiřadit i kolegu, který se ještě nepřihlásil.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import httpx
from sqlalchemy import false, func, insert, or_, select, update
from sqlalchemy.engine import Engine

from .config import Settings
from .db import documents, users
from .docstore.store import DocumentStore, now_ms
from .principal import SYSTEM, Principal

log = logging.getLogger(__name__)

AVATAR_COLOR = "#888888"


def _profile(uid: str, name: str, email: str | None, me: Principal | None) -> dict:
    return {"id": uid, "name": name or "", "email": email or None, "avatarUrl": "", "color": AVATAR_COLOR,
            "isMe": bool(me and uid == me.id)}


class Directory:
    def __init__(self, engine: Engine, store: DocumentStore, settings: Settings):
        self.engine = engine
        self.store = store
        self.settings = settings
        self._graph = GraphClient(settings) if settings.graph_directory_search else None

    # ---- přihlášení ----
    def record_login(self, p: Principal) -> None:
        """Zapíše/aktualizuje uživatele a jeho spárování ``people/<id>`` (dřív ruční krok správce)."""
        now = now_ms()
        roles = ",".join(p.roles)
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == p.id)).first()
            if row:
                conn.execute(update(users).where(users.c.id == p.id).values(
                    email=p.email, name=p.name, roles=roles, last_seen=now))
            else:
                conn.execute(insert(users).values(id=p.id, email=p.email, name=p.name, roles=roles,
                                                  first_seen=now, last_seen=now))
        people = self.store.get(SYSTEM, f"people/{p.id}")
        if not people.exists or (people.data or {}).get("email") != p.email:
            self.store.set(SYSTEM, f"people/{p.id}", {
                "email": p.email, "pairedAt": now, "pairedBy": "sso", "pairedById": "",
            })

    # ---- profily ----
    def profiles(self, ids: list[str], me: Principal) -> dict[str, dict]:
        ids = [str(i) for i in ids if i][:500]
        out: dict[str, dict] = {}
        if not ids:
            return out
        with self.engine.connect() as conn:
            rows = {r.id: r for r in conn.execute(select(users).where(users.c.id.in_(ids)))}
            missing = [i for i in ids if i not in rows]
            # historická ID (účty claude.ai) se dohledají přes spárování people/<id> → e-mail → uživatel
            legacy_emails: dict[str, str] = {}
            if missing:
                paths = [f"people/{i}" for i in missing]
                for r in conn.execute(select(documents.c.doc_id, documents.c.data).where(
                        documents.c.path.in_(paths), documents.c.deleted == false())):
                    email = (json.loads(r.data).get("email") or "").lower()
                    if email:
                        legacy_emails[r.doc_id] = email
            by_email = {}
            if legacy_emails:
                by_email = {r.email: r for r in conn.execute(
                    select(users).where(users.c.email.in_(list(set(legacy_emails.values())))))}
        for i in ids:
            if i in rows:
                out[i] = _profile(i, rows[i].name, rows[i].email, me)
            elif i in legacy_emails:
                u = by_email.get(legacy_emails[i])
                out[i] = _profile(i, u.name if u else "", legacy_emails[i], me)
            else:
                out[i] = _profile(i, "", None, me)
        return out

    # ---- hledání ----
    def search(self, q: str, me: Principal, limit: int = 20) -> list[dict]:
        q = (q or "").strip().lower()[:100]
        with self.engine.connect() as conn:
            stmt = select(users).order_by(users.c.name).limit(limit)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(or_(func.lower(users.c.name).like(like), func.lower(users.c.email).like(like)))
            local = [_profile(r.id, r.name, r.email, me) for r in conn.execute(stmt)]
        if not self._graph or len(q) < 2:
            return local
        seen = {p["email"] for p in local if p["email"]}
        try:
            for hit in self._graph.search_users(q, limit):
                if hit["email"] and hit["email"] not in seen:
                    local.append(_profile(hit["id"], hit["name"], hit["email"], me))
                    seen.add(hit["email"])
        except Exception:
            log.warning("hledání v Entra ID selhalo, vracím jen známé uživatele", exc_info=True)
        return local[:limit]


class GraphClient:
    """Minimální klient Microsoft Graph (client credentials) jen pro hledání lidí."""

    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_exp = 0.0
        self._lock = threading.Lock()

    def _get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            r = httpx.post(
                f"https://login.microsoftonline.com/{self.s.oidc_tenant_id}/oauth2/v2.0/token",
                data={"client_id": self.s.oidc_client_id, "client_secret": self.s.oidc_client_secret,
                      "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
                timeout=10,
            )
            r.raise_for_status()
            body = r.json()
            self._token, self._token_exp = body["access_token"], time.time() + int(body.get("expires_in", 3600))
            return self._token

    def search_users(self, q: str, limit: int) -> list[dict]:
        safe = q.replace('"', "")
        r = httpx.get(
            "https://graph.microsoft.com/v1.0/users",
            params={"$search": f'"displayName:{safe}" OR "mail:{safe}"', "$select": "id,displayName,mail,userPrincipalName",
                    "$top": str(limit), "$filter": "accountEnabled eq true"},
            headers={"Authorization": f"Bearer {self._get_token()}", "ConsistencyLevel": "eventual"},
            timeout=10,
        )
        r.raise_for_status()
        return [{"id": u["id"], "name": u.get("displayName") or "",
                 "email": (u.get("mail") or u.get("userPrincipalName") or "").lower()} for u in r.json().get("value", [])]
