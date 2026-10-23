#!/usr/bin/env python3
"""Sestaví stránku aplikace ze zdroje.

  python frontend/build.py            -> backend/semafor/static/index.html  (pro server; TEST/ostrou řídí konfigurace)
  python frontend/build.py --offline [--seed zaloha.json]
                                      -> frontend/dist/semafor-offline.html (testshim místo serveru, pro proklikání
                                         a pro dosavadní testy test_t*.cjs; data jen v localStorage prohlížeče,
                                         --seed vloží výchozí data ze zálohy ve formátu {"docs": {...}})

Zdroj ``src/semafor-provozu.src.html`` je fragment stránky (jako u artefaktu); build doplní kostru
dokumentu, loga, knihovny pro PDF (``vendor/``) a platformní adaptér (``src/platform.js``).
Každý ``<script>`` dostane atribut ``nonce`` se zástupným znakem, který server při doručení stránky
nahradí náhodnou hodnotou (Content-Security-Policy bez 'unsafe-inline' pro skripty).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "src" / "semafor-provozu.src.html"
PLATFORM = HERE / "src" / "platform.js"
TESTSHIM = HERE / "src" / "testshim.js"
VENDOR = HERE / "vendor"
ASSETS = HERE / "assets"
OUT_SERVER = ROOT / "backend" / "semafor" / "static" / "index.html"
OUT_OFFLINE = HERE / "dist" / "semafor-offline.html"

NONCE = "__CSP_NONCE__"
VENDOR_LIBS = ("html2canvas.min.js", "jspdf.umd.min.js")
APP_START = '<div class="app" id="app">'


def script(body: str, label: str, nonce: bool) -> str:
    attr = f' nonce="{NONCE}"' if nonce else ""
    if "</script" in body.lower():
        raise ValueError(f"{label}: obsah skriptu nesmí obsahovat </script>")
    return f"<script{attr}>/* {label} */\n{body}\n</script>\n"


def replace_once(html: str, marker: str, value: str) -> str:
    if html.count(marker) != 1:
        raise ValueError(f"značka {marker!r} musí být ve zdroji právě jednou (je {html.count(marker)}×)")
    return html.replace(marker, value)


def replace_all(html: str, marker: str, value: str) -> str:
    if marker not in html:
        raise ValueError(f"značka {marker!r} ve zdroji chybí")
    return html.replace(marker, value)


def build(offline: bool, seed: Path | None = None) -> Path:
    html = SRC.read_text(encoding="utf-8")
    html = replace_all(html, "__LOGO_RED__", (ASSETS / "logo_red.txt").read_text().strip())
    html = replace_all(html, "__LOGO_WHITE__", (ASSETS / "logo_white.txt").read_text().strip())

    nonce = not offline
    libs = "".join(script((VENDOR / n).read_text(encoding="utf-8"), n, nonce) for n in VENDOR_LIBS)
    html = replace_once(html, "<!--VENDOR_PDF-->", libs)
    if offline:
        html = replace_once(html, "<!--SP_CONFIG-->", "")
        seed_js = ""
        if seed:
            docs = json.loads(seed.read_text(encoding="utf-8"))["docs"]
            seed_js = script("window.__SEED=" + json.dumps(docs, ensure_ascii=False).replace("<", "\\u003c") + ";", "seed", False)
        html = replace_once(html, "<!--PLATFORM-->", seed_js + script(TESTSHIM.read_text(encoding="utf-8"), "testshim.js", False))
    else:
        html = replace_once(html, "<!--PLATFORM-->", script(PLATFORM.read_text(encoding="utf-8"), "platform.js", True))
        # hlavní skript aplikace: jediný řádek "<script>" na nejvyšší úrovni zdroje
        lines = html.split("\n")
        idx = [i for i, ln in enumerate(lines) if ln == "<script>"]
        if len(idx) != 1:
            raise ValueError(f"čekám právě jeden řádek '<script>' ve zdroji, je jich {len(idx)}")
        lines[idx[0]] = f'<script nonce="{NONCE}">'
        html = "\n".join(lines)

    if APP_START not in html:
        raise ValueError("ve zdroji chybí začátek aplikace " + APP_START)
    head, body = html.split(APP_START, 1)
    doc = ("<!doctype html>\n<html lang=\"cs\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
           f"{head.strip()}\n</head>\n<body>\n{APP_START}{body.rstrip()}\n</body>\n</html>\n")
    out = OUT_OFFLINE if offline else OUT_SERVER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8", newline="\n")  # stejný výstup na Windows i Linuxu
    digest = hashlib.sha256(doc.encode("utf-8")).hexdigest()[:16]
    print(f"{out.relative_to(ROOT)}: {len(doc):,} znaků, sha256 {digest}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--seed", type=Path, help="jen s --offline: výchozí data ze zálohy")
    args = ap.parse_args()
    build(args.offline, args.seed)
