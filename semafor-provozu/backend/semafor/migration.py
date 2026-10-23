"""Import dat: migrace ze zálohy Claude artefaktu a obnova ze zálohy serveru.

Vstupní formáty (oba už v projektu existují):

* ``semafor-backup-*-plna.json``: ``{"docs": {"tasks/t001": {...}, ...}}``
  (stejný tvar vytváří i ``python -m semafor export``),
* složka ``<kolekce>/<id>.json`` (případně s obalem ``{id, data, version}``).

Co migrace dělá s identitami (účty claude.ai v datech):

* ``people/<staré id>`` se přenesou beze změny, takže historie a potvrzení
  dál ukazují jméno podle e-mailu (``authorLabel`` ve frontendu),
* ``ownerUserId`` se starým id se nahradí e-mailem v ``ownerEmail`` a vyprázdní;
  „Moje práce“ pak rozhoduje podle e-mailu firemního účtu,
* id, ke kterému není e-mail (ani v ``people``, ani v mapě ``--identity-map``),
  zůstane a je v protokolu jako NESPÁROVANÉ (ruční oprava po migraci).

Nic se nezapisuje tiše: bez ``--apply`` je to jen suchý běh s protokolem.
"""
from __future__ import annotations

import copy
import glob
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass, field

from sqlalchemy import false, func, select

from .assets import ALLOWED_TYPES, AssetStore
from .db import documents
from .docstore.paths import parse_doc_path
from .docstore.store import DocumentStore
from .principal import SYSTEM

IMPORT_ROOTS = ("projects", "tasks", "history", "history_archive", "people", "settings", "notify")
ITEM_COLLECTIONS = ("projects", "tasks")


@dataclass
class MigrationReport:
    source: str
    sha256: str
    counts_in: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    owner_rewritten: list[str] = field(default_factory=list)
    unpaired_ids: dict[str, list[str]] = field(default_factory=dict)
    attachments: list[dict] = field(default_factory=list)
    attachments_missing: list[str] = field(default_factory=list)
    attachments_imported: int = 0
    written: int = 0
    verified_equal: int = 0
    verify_mismatch: list[str] = field(default_factory=list)
    applied: bool = False

    def to_markdown(self) -> str:
        L = [f"# Protokol importu dat ({'ZAPSÁNO' if self.applied else 'SUCHÝ BĚH, nic nezapsáno'})", "",
             f"* zdroj: `{self.source}`", f"* sha256 zdroje: `{self.sha256}`",
             "* dokumentů ve zdroji: " + ", ".join(f"{k} {v}" for k, v in sorted(self.counts_in.items())),
             f"* přeskočeno (mimo povolené kolekce): {len(self.skipped)}"]
        L += [f"  * `{p}`" for p in self.skipped[:50]]
        L += [f"* vlastník převeden ze starého id na e-mail: {len(self.owner_rewritten)}"]
        L += [f"* NESPÁROVANÁ stará id (bez e-mailu): {len(self.unpaired_ids)}"]
        for uid, where in self.unpaired_ids.items():
            L.append(f"  * `{uid}`: {len(where)}× (např. {', '.join('`'+w+'`' for w in where[:5])})")
        L += [f"* přílohy (soubory) v datech: {len(self.attachments)}, naimportováno: {self.attachments_imported}, "
              f"CHYBÍ: {len(self.attachments_missing)}"]
        L += [f"  * `{a}`" for a in self.attachments_missing]
        if self.applied:
            L += [f"* zapsáno dokumentů: {self.written}",
                  f"* kontrola čtením zpět: shodných {self.verified_equal}, rozdílných {len(self.verify_mismatch)}"]
            L += [f"  * `{p}`" for p in self.verify_mismatch[:50]]
        L += ["", "Soukromé To Do (`data/users/...`) záloha artefaktu neobsahuje, platforma ho neexportuje."]
        return "\n".join(L) + "\n"


def load_source(path: str) -> dict[str, dict]:
    if os.path.isdir(path):
        docs: dict[str, dict] = {}
        for f in glob.glob(os.path.join(path, "**", "*.json"), recursive=True):
            rel = os.path.relpath(f, path).replace(os.sep, "/")
            if rel.count("/") < 1 or rel.endswith("versions.json"):
                continue
            body = json.load(open(f, encoding="utf-8"))
            if isinstance(body, dict) and "data" in body and "version" in body:
                body = body["data"]
            if isinstance(body, dict):
                body.pop("id", None)
                docs[rel[:-5]] = body
        return docs
    body = json.load(open(path, encoding="utf-8"))
    if isinstance(body.get("docs"), dict):
        return {p: {k: v for k, v in d.items() if k != "id"} for p, d in body["docs"].items() if isinstance(d, dict)}
    raise ValueError("neznámý formát zálohy (čekám {'docs': {...}} nebo složku)")


def _sha256_of(path: str) -> str:
    if os.path.isdir(path):
        return "(složka)"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def transform(docs: dict[str, dict], identity_map: dict[str, str], report: MigrationReport) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p, d in docs.items():
        root = p.split("/", 1)[0]
        report.counts_in[root] = report.counts_in.get(root, 0) + 1
        if root not in IMPORT_ROOTS:
            report.skipped.append(p)
            continue
        parse_doc_path(p)  # validace tvaru cesty
        out[p] = copy.deepcopy(d)

    legacy = {k.split("/", 1)[1]: (v.get("email") or "").strip().lower()
              for k, v in out.items() if k.startswith("people/") and v.get("email")}
    for uid, email in identity_map.items():
        email = email.strip().lower()
        legacy.setdefault(uid, email)
        if f"people/{uid}" not in out:
            out[f"people/{uid}"] = {"email": email, "pairedAt": 0, "pairedBy": "migrace", "pairedById": ""}

    for p, d in out.items():
        if p.split("/", 1)[0] not in ITEM_COLLECTIONS:
            continue
        uid = d.get("ownerUserId") or ""
        if uid:
            email = legacy.get(uid)
            if email:
                if not (d.get("ownerEmail") or "").strip():
                    d["ownerEmail"] = email
                d["ownerUserId"] = ""
                report.owner_rewritten.append(p)
            else:
                report.unpaired_ids.setdefault(uid, []).append(p)
        for a in d.get("attachments") or []:
            if isinstance(a, dict) and a.get("assetId"):
                report.attachments.append({"path": p, **a})
    return out


def _load_assets_dir(assets_dir: str | None) -> dict[str, str]:
    """Soubory příloh pojmenované podle id (``<assetId>.<přípona>`` nebo jen ``<assetId>``)."""
    found: dict[str, str] = {}
    if assets_dir and os.path.isdir(assets_dir):
        for f in os.listdir(assets_dir):
            found[os.path.splitext(f)[0]] = os.path.join(assets_dir, f)
    return found


def run_import(store: DocumentStore, asset_store: AssetStore, source: str, *, identity_map: dict[str, str] | None = None,
               assets_dir: str | None = None, apply: bool = False, allow_non_empty: bool = False) -> MigrationReport:
    report = MigrationReport(source=source, sha256=_sha256_of(source))
    docs = transform(load_source(source), identity_map or {}, report)
    files = _load_assets_dir(assets_dir)
    for a in report.attachments:
        if a["assetId"] not in files:
            report.attachments_missing.append(f"{a['assetId']} ({a.get('name', '')}) v {a['path']}")
    if not apply:
        return report

    with store.engine.connect() as conn:
        existing = conn.execute(select(func.count()).select_from(documents).where(documents.c.deleted == false())).scalar_one()
    if existing and not allow_non_empty:
        raise RuntimeError(f"cílová databáze už obsahuje {existing} dokumentů; pro přepis použij --allow-non-empty")

    report.written = store.bulk_set(SYSTEM, sorted(docs.items()))
    for a in report.attachments:
        fp = files.get(a["assetId"])
        if not fp:
            continue
        ctype = a.get("contentType") or mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if ctype not in ALLOWED_TYPES:
            report.attachments_missing.append(f"{a['assetId']} (nepovolený typ {ctype})")
            continue
        asset_store.import_asset(a["assetId"], a.get("name") or os.path.basename(fp), ctype,
                                 open(fp, "rb").read(), a.get("addedBy") or "migrace")
        report.attachments_imported += 1

    for p, d in docs.items():  # kontrola čtením zpět
        got = store.get(SYSTEM, p)
        if got.exists and json.dumps(got.data, sort_keys=True) == json.dumps(d, sort_keys=True):
            report.verified_equal += 1
        else:
            report.verify_mismatch.append(p)
    report.applied = True
    return report
