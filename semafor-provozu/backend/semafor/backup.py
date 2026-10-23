"""Logická záloha dat do JSON (stejný formát jako dosavadní ``semafor-backup-*-plna.json``).

Doplňuje zálohu databáze (BACKUP DATABASE): JSON je čitelný, porovnatelný
diffem a jde z něj obnovit do prázdné databáze (``python -m semafor import``).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from sqlalchemy import false, select

from .db import documents
from .docstore.store import DocumentStore


def export_all(store: DocumentStore, out_path: str, *, include_private: bool = False) -> dict:
    with store.engine.connect() as conn:
        seq = store.current_seq()
        rows = conn.execute(select(documents.c.path, documents.c.data, documents.c.version)
                            .where(documents.c.deleted == false()).order_by(documents.c.path)).all()
    docs, versions = {}, {}
    for r in rows:
        if not include_private and r.path.startswith("data/"):
            continue
        docs[r.path] = json.loads(r.data)
        versions[r.path] = r.version
    body = {"exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": "semafor-server",
            "seq": seq, "note": "plná záloha" + (" vč. soukromých To Do" if include_private else " bez soukromých To Do"),
            "docs": docs, "versions": versions}
    raw = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=False).encode("utf-8")
    with open(out_path, "wb") as f:
        f.write(raw)
    counts: dict[str, int] = {}
    for p in docs:
        counts[p.split("/", 1)[0]] = counts.get(p.split("/", 1)[0], 0) + 1
    return {"file": out_path, "documents": len(docs), "counts": counts, "seq": seq, "sha256": hashlib.sha256(raw).hexdigest()}


def export_snapshot_dir(store: DocumentStore, out_dir: str) -> dict:
    """Snímek pro nástroje mimo aplikaci (tools/pptx): ``<kolekce>/<id>.json``, jeden soubor = jeden dokument."""
    counts: dict[str, int] = {}
    with store.engine.connect() as conn:
        rows = conn.execute(
            select(documents.c.collection, documents.c.doc_id, documents.c.data)
            .where(documents.c.deleted == false(), documents.c.collection.in_(("projects", "tasks", "history")))
        ).all()
    for r in rows:
        os.makedirs(os.path.join(out_dir, r.collection), exist_ok=True)
        with open(os.path.join(out_dir, r.collection, r.doc_id + ".json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(json.loads(r.data), ensure_ascii=False, indent=1))
        counts[r.collection] = counts.get(r.collection, 0) + 1
    return {"dir": out_dir, "counts": counts}
