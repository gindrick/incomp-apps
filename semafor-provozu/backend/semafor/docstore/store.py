"""Dokumentové úložiště nad SQL (náhrada databáze Claude artefaktu).

Sémantika operací je stejná jako u platformy, na kterou je napsaný frontend:

* ``set``     zapíše celý dokument (založí, nebo přepíše),
* ``update``  rekurzivně sloučí vnořené objekty; pole a skaláry nahradí celé,
              ``None`` hodnotu klíče nastaví na ``null``; neexistující dokument = ``not_found``,
* ``delete``  dokument odstraní (v SQL jako náhrobek, kvůli živým změnám),
* ``acquire`` kooperativní lease: získá, nebo prodlouží, pokud ho nedrží někdo jiný.

Navíc proti platformě: každý zápis je atomický na serveru (zámek řádku), nese
verzi a volitelně ``if_version`` (podmíněný zápis pro import a obnovu).
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import and_, delete as sa_delete, false, insert, select, update as sa_update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from ..db import COUNTER_DOCS, MSSQL_LOCK_HINT, audit_log, counters, documents, leases
from ..errors import InvalidArgument, NotFound, TooLarge, VersionConflict
from ..principal import Principal
from .paths import DocPath, can_see_change, check_read, check_write, parse_collection_path, parse_doc_path


def now_ms() -> int:
    return int(time.time() * 1000)


def deep_merge(target: dict, patch: dict) -> dict:
    """Sloučení jako u platformy: objekty rekurzivně, vše ostatní (pole, skaláry, None) nahradí."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


@dataclass
class Doc:
    path: str
    collection: str
    id: str
    data: dict | None
    version: int
    seq: int
    deleted: bool = False

    @property
    def exists(self) -> bool:
        return not self.deleted and self.data is not None

    def to_api(self) -> dict:
        return {"id": self.id, "path": self.path, "exists": self.exists, "data": self.data if self.exists else None,
                "version": self.version if self.exists else 0}

    def to_change(self) -> dict:
        return {"path": self.path, "collection": self.collection, "id": self.id, "deleted": not self.exists,
                "data": self.data if self.exists else None, "version": self.version, "seq": self.seq}


def _row_to_doc(row) -> Doc:
    return Doc(path=row.path, collection=row.collection, id=row.doc_id,
               data=None if row.deleted else json.loads(row.data), version=row.version,
               seq=row.seq, deleted=bool(row.deleted))


class DocumentStore:
    def __init__(self, engine: Engine, *, max_doc_bytes: int, max_lease_ttl_ms: int, on_change=None):
        self.engine = engine
        self.max_doc_bytes = max_doc_bytes
        self.max_lease_ttl_ms = max_lease_ttl_ms
        self._on_change = on_change or (lambda: None)

    # ------------------------------------------------------------------ čtení
    def get(self, principal: Principal, path: str) -> Doc:
        dp = parse_doc_path(path)
        check_read(principal, dp.path)
        with self.engine.connect() as conn:
            row = conn.execute(select(documents).where(documents.c.path == dp.path)).first()
        if not row:
            return Doc(path=dp.path, collection=dp.collection, id=dp.doc_id, data=None, version=0, seq=0, deleted=True)
        return _row_to_doc(row)

    def list_collection(self, principal: Principal, collection_path: str) -> tuple[list[Doc], int]:
        col = parse_collection_path(collection_path)
        check_read(principal, col + "/_")
        with self.engine.connect() as conn:
            seq = self._current_seq(conn)
            rows = conn.execute(
                select(documents)
                .where(and_(documents.c.collection == col, documents.c.deleted == false()))
                .order_by(documents.c.doc_id)
            ).all()
        return [_row_to_doc(r) for r in rows], seq

    def changes_since(self, principal: Principal, since: int, limit: int = 2000) -> tuple[list[dict], int]:
        """Změny se seq > since, které uživatel smí vidět. Vrací (změny, nejvyšší prohlédnuté seq)."""
        with self.engine.connect() as conn:
            head = self._current_seq(conn)
            rows = conn.execute(
                select(documents).where(documents.c.seq > since).order_by(documents.c.seq).limit(limit)
            ).all()
        out, last = [], since
        for r in rows:
            last = max(last, r.seq)
            if can_see_change(principal, r.path):
                out.append(_row_to_doc(r).to_change())
        if len(rows) < limit:
            last = max(last, head)
        return out, last

    def current_seq(self) -> int:
        with self.engine.connect() as conn:
            return self._current_seq(conn)

    # ------------------------------------------------------------------ zápis
    def _in_tx(self, work, *, notify: bool = True):
        """Spustí ``work(conn)`` v transakci. Souběžné založení téže cesty (IntegrityError) a oběť
        deadlocku se zopakují; všechny operace jsou idempotentní vůči opakování celé transakce."""
        attempts = 3
        for attempt in range(attempts):
            try:
                with self.engine.begin() as conn:
                    result = work(conn)
                break
            except IntegrityError:
                if attempt == attempts - 1:
                    raise
            except DBAPIError as exc:
                if attempt == attempts - 1 or not is_retryable(exc):
                    raise
                time.sleep(0.05 * (attempt + 1))
        if notify:
            self._on_change()
        return result

    def set(self, principal: Principal, path: str, data: Any, *, if_version: int | None = None) -> Doc:
        dp = parse_doc_path(path)
        check_write(principal, dp.path)
        payload = self._validate_data(data)

        def work(conn):
            row = self._lock_row(conn, dp.path)
            self._check_version(row, if_version)
            return self._write(conn, principal, dp, row, payload, op="set")
        return self._in_tx(work)

    def update(self, principal: Principal, path: str, patch: Any, *, if_version: int | None = None) -> Doc:
        dp = parse_doc_path(path)
        check_write(principal, dp.path)
        if not isinstance(patch, dict):
            raise InvalidArgument("update očekává objekt")

        def work(conn):
            row = self._lock_row(conn, dp.path)
            if not row or row.deleted:
                raise NotFound("dokument neexistuje")
            self._check_version(row, if_version)
            payload = self._validate_data(deep_merge(json.loads(row.data), patch))
            return self._write(conn, principal, dp, row, payload, op="update")
        return self._in_tx(work)

    def delete(self, principal: Principal, path: str, *, if_version: int | None = None) -> None:
        dp = parse_doc_path(path)
        check_write(principal, dp.path)

        def work(conn):
            row = self._lock_row(conn, dp.path)
            self._check_version(row, if_version)
            if not row or row.deleted:
                return False
            seq = self._next_seq(conn)
            conn.execute(sa_update(documents).where(documents.c.path == dp.path).values(
                deleted=True, version=row.version + 1, seq=seq, updated_at=now_ms(), updated_by=principal.email))
            self._audit(conn, principal, "delete", dp.path, row.version + 1, None)
            return True
        self._in_tx(work)

    def bulk_set(self, principal: Principal, docs: Iterable[tuple[str, Any]]) -> int:
        """Import: zapíše mnoho dokumentů v jedné transakci (vše, nebo nic). Spouštět při zastavené aplikaci."""
        prepared = []
        for path, data in docs:
            dp = parse_doc_path(path)
            check_write(principal, dp.path)
            prepared.append((dp, self._validate_data(data)))

        def work(conn):
            for dp, payload in prepared:
                self._write(conn, principal, dp, self._lock_row(conn, dp.path), payload, op="import")
            return len(prepared)
        return self._in_tx(work)

    # ------------------------------------------------------------------ lease
    def acquire(self, principal: Principal, path: str, holder: str, ttl_ms: int) -> dict:
        dp = parse_doc_path(path)
        check_write(principal, dp.path)
        holder = str(holder or "")[:200]
        if not holder:
            raise InvalidArgument("chybí holder")
        ttl = max(1, min(int(ttl_ms or 30000), self.max_lease_ttl_ms))
        return self._in_tx(lambda conn: self._acquire_tx(conn, dp.path, holder, ttl), notify=False)

    def _acquire_tx(self, conn: Connection, path: str, holder: str, ttl: int) -> dict:
        now = now_ms()
        cur = conn.execute(_locking(select(leases).where(leases.c.path == path), leases)).first()
        if cur and cur.expires_at > now and cur.holder != holder:
            return {"acquired": False, "holder": cur.holder, "expiresAt": _iso(cur.expires_at)}
        exp = now + ttl
        if cur:
            conn.execute(sa_update(leases).where(leases.c.path == path).values(holder=holder, expires_at=exp))
        else:
            conn.execute(insert(leases).values(path=path, holder=holder, expires_at=exp))
        return {"acquired": True, "holder": holder, "expiresAt": _iso(exp)}

    def purge_expired_leases(self) -> int:
        with self.engine.begin() as conn:
            return conn.execute(sa_delete(leases).where(leases.c.expires_at < now_ms() - 3600_000)).rowcount or 0

    # ------------------------------------------------------------------ interní
    def _validate_data(self, data: Any) -> str:
        if not isinstance(data, dict):
            raise InvalidArgument("dokument musí být objekt")
        try:
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidArgument(f"dokument není platný JSON: {exc}") from exc
        if len(payload.encode("utf-8")) > self.max_doc_bytes:
            raise TooLarge(f"dokument je větší než {self.max_doc_bytes} B")
        return payload

    @staticmethod
    def _lock_row(conn: Connection, path: str):
        return conn.execute(_locking(select(documents).where(documents.c.path == path), documents)).first()

    @staticmethod
    def _check_version(row, if_version: int | None) -> None:
        if if_version is None:
            return
        current = 0 if (not row or row.deleted) else row.version
        if current != if_version:
            raise VersionConflict(f"verze dokumentu je {current}, očekávána {if_version}", currentVersion=current)

    def _write(self, conn: Connection, principal: Principal, dp: DocPath, row, payload: str, *, op: str) -> Doc:
        now = now_ms()
        seq = self._next_seq(conn)
        version = (row.version + 1) if row else 1
        values = dict(collection=dp.collection, doc_id=dp.doc_id, data=payload, version=version, seq=seq,
                      deleted=False, updated_at=now, updated_by=principal.email)
        if row:
            conn.execute(sa_update(documents).where(documents.c.path == dp.path).values(**values))
        else:
            conn.execute(insert(documents).values(path=dp.path, created_at=now, **values))
        self._audit(conn, principal, op, dp.path, version, len(payload))
        return Doc(path=dp.path, collection=dp.collection, id=dp.doc_id, data=json.loads(payload), version=version, seq=seq)

    @staticmethod
    def _next_seq(conn: Connection) -> int:
        conn.execute(sa_update(counters).where(counters.c.name == COUNTER_DOCS).values(value=counters.c.value + 1))
        return int(conn.execute(select(counters.c.value).where(counters.c.name == COUNTER_DOCS)).scalar_one())

    @staticmethod
    def _current_seq(conn: Connection) -> int:
        return int(conn.execute(select(counters.c.value).where(counters.c.name == COUNTER_DOCS)).scalar_one())

    @staticmethod
    def _audit(conn: Connection, principal: Principal, op: str, path: str, version: int | None, size: int | None) -> None:
        conn.execute(insert(audit_log).values(at=now_ms(), user_id=principal.id, user_email=principal.email,
                                              op=op, path=path, version=version, bytes=size))


def _locking(stmt, table):
    """SELECT se zámkem řádku: SQL Server přes tabulkovou nápovědu, ostatní přes FOR UPDATE."""
    return stmt.with_hint(table, MSSQL_LOCK_HINT, dialect_name="mssql").with_for_update()


def is_retryable(exc: Exception) -> bool:
    """Oběť deadlocku (SQL Server 1205) nebo zamčená SQLite: operaci lze bezpečně zopakovat."""
    text = str(getattr(exc, "orig", exc)).lower()
    return "1205" in text or "deadlock" in text or "database is locked" in text


def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + f".{ms % 1000:03d}Z"
