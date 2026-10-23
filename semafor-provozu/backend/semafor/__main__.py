"""Příkazová řádka Semafor Provozu.

  python -m semafor serve [--host 127.0.0.1] [--port 8000] [--workers 2]
  python -m semafor db-init
  python -m semafor import <záloha.json|složka> [--identity-map map.json] [--assets-dir DIR]
                          [--apply] [--allow-non-empty] [--report protokol.md]
  python -m semafor export <soubor.json> [--include-private]
  python -m semafor export <složka> --keep 30          (rotované zálohy)
  python -m semafor export <složka> --snapshot-dir     (snímek pro tools/pptx)
  python -m semafor notify {assigned|due|daily} [--force]
  python -m semafor purge-leases
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from .config import get_settings


def _services():
    from .assets import AssetStore
    from .db import init_schema, make_engine
    from .docstore.store import DocumentStore
    from .logging_setup import setup_logging

    s = get_settings()
    setup_logging(s)
    engine = make_engine(s.database_url, pool_size=2, echo=s.db_echo)
    init_schema(engine)
    store = DocumentStore(engine, max_doc_bytes=s.max_doc_bytes, max_lease_ttl_ms=s.max_lease_ttl_ms)
    return s, engine, store, AssetStore(engine, s)


def cmd_serve(a) -> int:
    import os

    import uvicorn

    if a.workers > 1 and not (os.environ.get("SEMAFOR_SESSION_SECRET") or _env_file_has("SEMAFOR_SESSION_SECRET")):
        print("Více workerů vyžaduje pevné SEMAFOR_SESSION_SECRET (jinak má každý proces jiné a relace neplatí).")
        return 2

    uvicorn.run("semafor.app:create_app", factory=True, host=a.host, port=a.port, workers=a.workers,
                proxy_headers=True, forwarded_allow_ips=a.forwarded_allow_ips, log_level="info",
                timeout_keep_alive=75)
    return 0


def _env_file_has(key: str) -> bool:
    import os

    path = os.environ.get("SEMAFOR_ENV_FILE", ".env")
    try:
        return any(ln.strip().startswith(key + "=") and ln.split("=", 1)[1].strip() for ln in open(path, encoding="utf-8"))
    except OSError:
        return False


def cmd_db_init(_a) -> int:
    _services()
    print("schéma je připravené")
    return 0


def cmd_import(a) -> int:
    from .migration import run_import

    _s, _e, store, assets = _services()
    identity = json.load(open(a.identity_map, encoding="utf-8")) if a.identity_map else {}
    rep = run_import(store, assets, a.source, identity_map=identity, assets_dir=a.assets_dir, apply=a.apply,
                     allow_non_empty=a.allow_non_empty)
    md = rep.to_markdown()
    if a.report:
        open(a.report, "w", encoding="utf-8").write(md)
    print(md)
    return 1 if (rep.applied and rep.verify_mismatch) else 0


def cmd_export(a) -> int:
    from .backup import export_all, export_snapshot_dir

    _s, _e, store, _assets = _services()
    if a.snapshot_dir:
        info = export_snapshot_dir(store, a.out)
    elif a.keep:
        # rotace: do složky a.out soubor semafor-backup-<datum_čas>.json, ponechá posledních N
        import glob
        import os
        os.makedirs(a.out, exist_ok=True)
        name = "semafor-backup-" + dt.datetime.now().strftime("%Y-%m-%d_%H%M") + ".json"
        info = export_all(store, os.path.join(a.out, name), include_private=a.include_private)
        old = sorted(glob.glob(os.path.join(a.out, "semafor-backup-*.json")))[:-a.keep]
        for f in old:
            os.remove(f)
        info["removed_old"] = len(old)
    else:
        info = export_all(store, a.out, include_private=a.include_private)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_notify(a) -> int:
    from .notify.runner import NotifyRunner

    s, _e, store, _assets = _services()
    today = dt.date.today()
    if today.weekday() >= 5 and not a.force:
        print("víkend: nic se neposílá (--force pro výjimku)")
        return 0
    runner = NotifyRunner(store, s, today=today)
    sent = {"assigned": runner.run_assigned, "due": runner.run_due, "daily": runner.run_daily}[a.job]()
    print(f"{a.job}: {'odesláno' if s.notify_enabled else 'jen do logu'} {sent} mailů")
    return 0


def cmd_purge_leases(_a) -> int:
    _s, _e, store, _assets = _services()
    print(f"smazáno prošlých zámků: {store.purge_expired_leases()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m semafor", description="Semafor Provozu")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="spustí webový server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--forwarded-allow-ips", default="127.0.0.1",
                    help="adresy reverse proxy, jejichž X-Forwarded-* hlavičkám se věří")
    sp.set_defaults(fn=cmd_serve)

    sub.add_parser("db-init", help="založí tabulky").set_defaults(fn=cmd_db_init)

    sp = sub.add_parser("import", help="import ze zálohy (bez --apply jen suchý běh)")
    sp.add_argument("source")
    sp.add_argument("--identity-map", help="JSON {staré_id: email} pro účty, které nejsou v people")
    sp.add_argument("--assets-dir", help="složka se soubory příloh pojmenovanými podle assetId")
    sp.add_argument("--apply", action="store_true")
    sp.add_argument("--allow-non-empty", action="store_true")
    sp.add_argument("--report", help="kam uložit protokol (markdown)")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("export", help="logická záloha do JSON")
    sp.add_argument("out")
    sp.add_argument("--include-private", action="store_true", help="včetně soukromých To Do (jen pro DBA)")
    sp.add_argument("--snapshot-dir", action="store_true", help="místo JSON souboru složka snímku pro tools/pptx")
    sp.add_argument("--keep", type=int, default=0, help="out je složka: soubor s datem a ponechat posledních N záloh")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("notify", help="e-mailové notifikace")
    sp.add_argument("job", choices=["assigned", "due", "daily"])
    sp.add_argument("--force", action="store_true", help="spustit i o víkendu")
    sp.set_defaults(fn=cmd_notify)

    sub.add_parser("purge-leases", help="smaže prošlé zámky").set_defaults(fn=cmd_purge_leases)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
