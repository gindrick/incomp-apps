"""Přílohy uložené v SQL Serveru (náhrada schopnosti ``assets`` platformy)."""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from .config import Settings
from .db import assets
from .docstore.store import now_ms
from .errors import NotFound, PermissionDenied, TooLarge, UnsupportedType
from .principal import Principal

# Stejný seznam jako TYPE_BY_EXT ve frontendu. Office soubory patří do SharePointu (odkaz).
ALLOWED_TYPES = {
    "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
    "video/mp4", "video/webm", "text/csv", "text/markdown", "application/json", "text/plain",
}
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Typy, které prohlížeč umí vykreslit jako aktivní obsah: posílají se ke stažení, ne k zobrazení.
DOWNLOAD_ONLY_TYPES = {"image/svg+xml"}


@dataclass
class StoredAsset:
    id: str
    filename: str
    content_type: str
    size_bytes: int
    data: bytes


class AssetStore:
    def __init__(self, engine: Engine, settings: Settings):
        self.engine = engine
        self.settings = settings

    def save(self, principal: Principal, filename: str, content_type: str, data: bytes) -> dict:
        if not principal.can_edit:
            raise PermissionDenied("not_granted")
        content_type = (content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_TYPES:
            raise UnsupportedType(f"typ {content_type!r} se nahrát nedá")
        limit = self.settings.max_svg_bytes if content_type == "image/svg+xml" else self.settings.max_upload_bytes
        if len(data) > limit:
            raise TooLarge(f"soubor je větší než {limit} B")
        asset_id = secrets.token_hex(16)
        with self.engine.begin() as conn:
            conn.execute(insert(assets).values(
                id=asset_id, filename=(filename or "soubor")[:260], content_type=content_type, size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), data=data, created_at=now_ms(), created_by=principal.email))
        return {"id": asset_id, "contentType": content_type, "sizeBytes": len(data)}

    def load(self, asset_id: str) -> StoredAsset:
        if not ASSET_ID_RE.match(asset_id or ""):
            raise NotFound("příloha neexistuje")
        with self.engine.connect() as conn:
            r = conn.execute(select(assets).where(assets.c.id == asset_id)).first()
        if not r:
            raise NotFound("příloha neexistuje")
        return StoredAsset(r.id, r.filename, r.content_type, r.size_bytes, bytes(r.data))

    def import_asset(self, asset_id: str, filename: str, content_type: str, data: bytes, created_by: str) -> None:
        """Migrace: zachová původní id přílohy z artefaktu, aby odkazy v datech platily dál."""
        if not ASSET_ID_RE.match(asset_id or ""):
            raise ValueError(f"neplatné id přílohy {asset_id!r}")
        with self.engine.begin() as conn:
            if conn.execute(select(assets.c.id).where(assets.c.id == asset_id)).first():
                return
            conn.execute(insert(assets).values(
                id=asset_id, filename=filename[:260], content_type=content_type, size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), data=data, created_at=now_ms(), created_by=created_by))
