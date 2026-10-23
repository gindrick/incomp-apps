"""Stránka aplikace, přílohy a kontrola stavu."""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import text

from .assets import DOWNLOAD_ONLY_TYPES
from .auth import current_principal, icon_link, login_redirect, no_role_page
from .config import Settings
from .errors import AppError
from .principal import has_any_role

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
FAVICON_FILE = STATIC_DIR / "favicon.svg"
NONCE_PLACEHOLDER = "__CSP_NONCE__"
CONFIG_PLACEHOLDER = "<!--SP_CONFIG-->"
ICON_PLACEHOLDER = "<!--SP_ICON-->"
BLOB_CSP = "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'"
# PDF dostane jen nosniff: vestavěný prohlížeč PDF v Chromiu se v sandboxu nevykreslí a skripty stránky PDF spustit neumí.
NO_CSP_TYPES = {"application/pdf"}
GOOGLE_FONTS_RE = re.compile(r'<link rel="(?:preconnect|stylesheet)" href="https://fonts\.googleapis\.com[^"]*">\n?')

router = APIRouter()


def load_index_template() -> str:
    if not INDEX_FILE.exists():
        return ("<!doctype html><meta charset='utf-8'><title>Semafor Provozu</title>"
                "<p>Chybí sestavená stránka. Spusť <code>python frontend/build.py</code>.</p>")
    html = INDEX_FILE.read_text(encoding="utf-8")
    if CONFIG_PLACEHOLDER not in html:
        raise RuntimeError("index.html neobsahuje značku <!--SP_CONFIG--> (sestav ho přes frontend/build.py)")
    return html


def content_security_policy(s: Settings, nonce: str) -> str:
    fonts_css = " https://fonts.googleapis.com" if s.allow_google_fonts else ""
    fonts = " https://fonts.gstatic.com" if s.allow_google_fonts else ""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'nonce-{nonce}'",
        f"style-src 'self' 'unsafe-inline'{fonts_css}",
        f"font-src 'self' data:{fonts}",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        f"frame-ancestors {s.frame_ancestors}",
    ])


@router.get("/", include_in_schema=False)
def index(request: Request):
    s: Settings = request.app.state.settings
    p = current_principal(request)
    if not p:
        return login_redirect(request)
    if s.require_role and not has_any_role(p, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader):
        return HTMLResponse(no_role_page(p, s), status_code=403)
    nonce = secrets.token_urlsafe(18)
    cfg = {"basePath": s.base_path, "appUrl": s.public_url + "/", "environment": s.environment,
           "isTest": s.is_test, "logoutUrl": f"{s.base_path}/auth/logout"}
    cfg_js = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c")
    html = request.app.state.index_template
    if not s.allow_google_fonts:
        html = GOOGLE_FONTS_RE.sub("", html)
    html = (html
            .replace(CONFIG_PLACEHOLDER, f'<script nonce="{nonce}">window.SP_CONFIG={cfg_js};</script>', 1)
            .replace(ICON_PLACEHOLDER, icon_link(s), 1)
            .replace(NONCE_PLACEHOLDER, nonce))
    return HTMLResponse(html, headers={
        "Content-Security-Policy": content_security_policy(s, nonce),
        "Cache-Control": "no-store",
    })


@router.get("/_blob/{asset_id}", include_in_schema=False)
async def blob(asset_id: str, request: Request):
    s: Settings = request.app.state.settings
    p = current_principal(request)
    if not p:
        return login_redirect(request)
    if s.require_role and not has_any_role(p, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader):
        return HTMLResponse(no_role_page(p, s), status_code=403)
    try:
        a = await anyio.to_thread.run_sync(request.app.state.assets.load, asset_id)
    except AppError as exc:
        return JSONResponse(exc.to_dict(), status_code=exc.status)
    disposition = "attachment" if a.content_type in DOWNLOAD_ONLY_TYPES else "inline"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(a.filename)}",
        "Cache-Control": "private, max-age=86400, immutable",
    }
    if a.content_type not in NO_CSP_TYPES:
        headers["Content-Security-Policy"] = BLOB_CSP
    return Response(a.data, media_type=a.content_type, headers=headers)


@router.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(FAVICON_FILE, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request):
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "seq": request.app.state.store.current_seq()}
    except Exception as exc:  # noqa: BLE001 - kontrola stavu musí vrátit odpověď vždy
        return JSONResponse({"status": "error", "detail": type(exc).__name__}, status_code=503)
