"""Cesty dokumentů a pravidla přístupu.

Model odpovídá databázi Claude artefaktu, na kterou je napsaný frontend:
dokument = sudý počet segmentů (``projects/p01``,
``data/users/<uid>/private/todos/<id>``), kolekce = lichý počet.

Pravidla (dříve ``capabilities.db.rules`` artefaktu):

* ``people``, ``settings``: číst smí každý, zapisuje jen správce,
* ``data/users/<uid>/...``: jen uživatel ``<uid>`` (ani správce ne, jako na platformě),
* ``notify``: interní stav notifikací, přes API nepřístupný,
* ostatní povolené kolekce: číst smí každý přihlášený, zapisuje role User nebo Admin.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import InvalidArgument, PermissionDenied
from ..principal import Principal

SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,200}$")
MAX_PATH_LEN = 450

SHARED_COLLECTIONS = frozenset({"projects", "tasks", "history", "history_archive"})
ADMIN_WRITE_COLLECTIONS = frozenset({"people", "settings"})
PRIVATE_ROOT = "data"
INTERNAL_COLLECTIONS = frozenset({"notify"})
ALLOWED_ROOTS = SHARED_COLLECTIONS | ADMIN_WRITE_COLLECTIONS | INTERNAL_COLLECTIONS | {PRIVATE_ROOT}


@dataclass(frozen=True)
class DocPath:
    path: str
    collection: str
    doc_id: str

    @property
    def root(self) -> str:
        return self.path.split("/", 1)[0]


def _segments(path: str) -> list[str]:
    path = (path or "").strip("/")
    if not path or len(path) > MAX_PATH_LEN:
        raise InvalidArgument("neplatná cesta")
    segs = path.split("/")
    for s in segs:
        if not SEGMENT_RE.match(s) or s in (".", ".."):
            raise InvalidArgument(f"neplatný segment cesty: {s!r}")
    if segs[0] not in ALLOWED_ROOTS:
        raise PermissionDenied(f"kolekce {segs[0]!r} není povolená")
    return segs


def parse_doc_path(path: str) -> DocPath:
    segs = _segments(path)
    if len(segs) % 2:
        raise InvalidArgument("cesta dokumentu musí mít sudý počet segmentů")
    return DocPath(path="/".join(segs), collection="/".join(segs[:-1]), doc_id=segs[-1])


def parse_collection_path(path: str) -> str:
    segs = _segments(path)
    if len(segs) % 2 == 0:
        raise InvalidArgument("cesta kolekce musí mít lichý počet segmentů")
    return "/".join(segs)


def _private_owner(path: str) -> str | None:
    """Vrátí uid vlastníka soukromého podstromu ``data/users/<uid>/...`` (jinak None)."""
    segs = path.split("/")
    if segs[0] != PRIVATE_ROOT:
        return None
    if len(segs) < 3 or segs[1] != "users":
        return ""  # jiný podstrom pod data/ nikomu nepatří
    return segs[2]


def check_read(principal: Principal, path: str) -> None:
    root = path.split("/", 1)[0]
    if root in INTERNAL_COLLECTIONS and principal.id != "system":
        raise PermissionDenied("interní kolekce")
    owner = _private_owner(path)
    if owner is not None and owner != principal.id:
        raise PermissionDenied("soukromá data jiného uživatele")


def check_write(principal: Principal, path: str) -> None:
    check_read(principal, path)
    if not principal.can_edit:
        raise PermissionDenied("účet má jen čtení")
    root = path.split("/", 1)[0]
    if root in ADMIN_WRITE_COLLECTIONS and not principal.is_admin:
        raise PermissionDenied(f"do {root} zapisuje jen správce aplikace")


def can_see_change(principal: Principal, path: str) -> bool:
    """Filtr živých změn: stejná pravidla jako čtení, bez výjimek."""
    try:
        check_read(principal, path)
        return True
    except PermissionDenied:
        return False
