"""Přihlášení: Entra ID (OIDC, authorization code flow), LDAP (Active Directory) a vývojový režim.

Relace je podepsaná cookie (Starlette SessionMiddleware), server si stav
nedrží, takže může běžet víc workerů i víc serverů za balancerem.
"""
from __future__ import annotations

import logging
from urllib.parse import quote, urlsplit

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from ldap3.core.exceptions import LDAPException
from starlette.concurrency import run_in_threadpool

from . import ldap_auth
from .config import Settings
from .docstore.store import now_ms
from .errors import PermissionDenied, Unauthenticated
from .principal import Principal, has_any_role, principal_from_claims

log = logging.getLogger(__name__)
SESSION_KEY = "user"


def build_oauth(settings: Settings) -> OAuth | None:
    if settings.auth_mode != "oidc" or not settings.oidc_client_id:
        return None
    oauth = OAuth()
    oauth.register(
        "entra",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=f"https://login.microsoftonline.com/{settings.oidc_tenant_id}/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def current_principal(request: Request) -> Principal | None:
    s: Settings = request.app.state.settings
    data = request.session.get(SESSION_KEY)
    if not data:
        return None
    if now_ms() - int(data.get("at", 0)) > s.session_max_age_s * 1000:
        request.session.clear()
        return None
    if s.auth_mode == "ldap" and "username" in data:
        data = {**data, "roles": ldap_auth.roles_for(s, data["username"], data["email"])}
    return principal_from_claims(data, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader)


def require_principal(request: Request) -> Principal:
    p = current_principal(request)
    if not p:
        raise Unauthenticated("nepřihlášen nebo relace vypršela")
    s: Settings = request.app.state.settings
    if s.require_role and not has_any_role(p, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader):
        raise PermissionDenied("účet nemá přiřazenou roli v aplikaci Semafor Provozu")
    return p


def _safe_next(settings: Settings, nxt: str | None) -> str:
    """Návrat po přihlášení jen na vlastní cestu (ochrana proti open redirect)."""
    base = settings.base_path or ""
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and nxt.startswith(base + "/"):
        return nxt
    return base + "/"


def _start_session(request: Request, claims: dict) -> Principal:
    s: Settings = request.app.state.settings
    request.session.clear()
    request.session[SESSION_KEY] = {**claims, "at": now_ms()}
    p = principal_from_claims(claims, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader)
    if has_any_role(p, role_admin=s.role_admin, role_user=s.role_user, role_reader=s.role_reader) or not s.require_role:
        request.app.state.directory.record_login(p)
    log.info("přihlášení %s (%s) role=%s", p.email, p.id, ",".join(p.roles))
    return p


router = APIRouter(prefix="/auth")


@router.get("/login")
async def login(request: Request, next: str | None = None):
    s: Settings = request.app.state.settings
    if s.auth_mode == "dev":
        return HTMLResponse(_dev_login_page(s, _safe_next(s, next)))
    if s.auth_mode == "ldap":
        return HTMLResponse(_ldap_login_page(s, _safe_next(s, next)))
    oauth: OAuth = request.app.state.oauth
    request.session["next"] = _safe_next(s, next)
    return await oauth.entra.authorize_redirect(request, s.public_url + "/auth/callback")


@router.post("/login")
async def ldap_login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("")):
    s: Settings = request.app.state.settings
    if s.auth_mode != "ldap":
        return HTMLResponse("nedostupné", status_code=404)
    nxt = _safe_next(s, next)
    if not _origin_ok(request, s):
        return HTMLResponse(_ldap_login_page(s, nxt, error="Neplatný původ požadavku."), status_code=403)
    try:
        claims = await run_in_threadpool(ldap_auth.authenticate, s, username, password)
    except LDAPException as exc:
        log.error("LDAP nedostupný: %s", exc)
        return HTMLResponse(_ldap_login_page(s, nxt, username, "Přihlašovací server je nedostupný, zkus to za chvíli."),
                            status_code=503)
    if not claims:
        log.info("přihlášení LDAP zamítnuto: %s", ldap_auth.normalize_username(username))
        return HTMLResponse(_ldap_login_page(s, nxt, username, "Neplatné uživatelské jméno nebo heslo."), status_code=401)
    _start_session(request, {**claims, "roles": ldap_auth.roles_for(s, claims["username"], claims["email"])})
    return RedirectResponse(nxt, status_code=303)


@router.get("/callback")
async def callback(request: Request):
    s: Settings = request.app.state.settings
    oauth: OAuth = request.app.state.oauth
    try:
        token = await oauth.entra.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("přihlášení selhalo: %s", exc)
        return HTMLResponse(_message_page("Přihlášení se nepovedlo", str(exc.description or exc.error), s), status_code=401)
    claims = token.get("userinfo") or {}
    if claims.get("tid") != s.oidc_tenant_id:
        return HTMLResponse(_message_page("Přihlášení odmítnuto", "Účet není z tenantu Hranipex.", s), status_code=403)
    nxt = request.session.pop("next", None)
    _start_session(request, {
        "id": claims["oid"],
        "email": (claims.get("email") or claims.get("preferred_username") or "").lower(),
        "name": claims.get("name") or "",
        "roles": claims.get("roles") or [],
    })
    return RedirectResponse(_safe_next(s, nxt), status_code=303)


@router.get("/dev-login")
async def dev_login(request: Request, u: str, next: str | None = None):
    s: Settings = request.app.state.settings
    if s.auth_mode != "dev" or s.environment == "production":
        return HTMLResponse("nedostupné", status_code=404)
    user = s.dev_users.get(u)
    if not user:
        return HTMLResponse("neznámý vývojový uživatel", status_code=404)
    _start_session(request, dict(user))
    return RedirectResponse(_safe_next(s, next), status_code=303)


@router.get("/logout")
async def logout(request: Request):
    s: Settings = request.app.state.settings
    request.session.clear()
    if s.auth_mode == "oidc" and s.oidc_tenant_id:
        target = (f"https://login.microsoftonline.com/{s.oidc_tenant_id}/oauth2/v2.0/logout"
                  f"?post_logout_redirect_uri={quote(s.public_url + '/', safe='')}")
        return RedirectResponse(target, status_code=303)
    return RedirectResponse((s.base_path or "") + "/", status_code=303)


def login_redirect(request: Request) -> RedirectResponse:
    s: Settings = request.app.state.settings
    here = (s.base_path or "") + request.url.path
    if request.url.query:
        here += "?" + request.url.query
    return RedirectResponse(f"{s.base_path}/auth/login?next={quote(here, safe='')}", status_code=303)


def icon_link(s: Settings) -> str:
    from html import escape

    return f'<link rel="icon" type="image/svg+xml" href="{escape(s.base_path)}/favicon.svg">'


def _message_page(title: str, text: str, s: Settings) -> str:
    from html import escape

    return (f"<!doctype html><html lang='cs'><meta charset='utf-8'>{icon_link(s)}<title>{escape(title)}</title>"
            f"<body style='font-family:Arial,sans-serif;max-width:560px;margin:80px auto;color:#2b2b2b'>"
            f"<h2 style='color:#ed1b34'>{escape(title)}</h2><p>{escape(text)}</p>"
            f"<p><a href='{escape(s.base_path)}/auth/login'>Přihlásit znovu</a></p></body></html>")


def no_role_page(p: Principal, s: Settings) -> str:
    return _message_page("Nemáš přístup", f"Účet {p.email} nemá v aplikaci Semafor Provozu přiřazenou roli. "
                                          "Požádej správce aplikace o přidání.", s)


def _dev_login_page(s: Settings, nxt: str) -> str:
    from html import escape

    links = "".join(
        f"<li><a href='{escape(s.base_path)}/auth/dev-login?u={escape(k)}&next={quote(nxt, safe='')}'>"
        f"{escape(v.get('name', k))}</a> <small>{escape(', '.join(v.get('roles', [])))}</small></li>"
        for k, v in s.dev_users.items())
    return (f"<!doctype html><html lang='cs'><meta charset='utf-8'>{icon_link(s)}<title>Vývojové přihlášení</title>"
            f"<body style='font-family:Arial,sans-serif;max-width:560px;margin:80px auto'>"
            f"<h2>Vývojové přihlášení</h2><p>Jen pro vývoj a testy (SEMAFOR_AUTH_MODE=dev).</p><ul>{links}</ul></body></html>")


def _ldap_login_page(s: Settings, nxt: str, username: str = "", error: str = "") -> str:
    from html import escape

    error_html = f"<p style='color:#ed1b34'>{escape(error)}</p>" if error else ""
    field = "display:block;width:100%;box-sizing:border-box;padding:8px;margin:4px 0 14px;font-size:15px"
    return (f"<!doctype html><html lang='cs'><meta charset='utf-8'>{icon_link(s)}"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>Přihlášení · Semafor Provozu</title>"
            f"<body style='font-family:Arial,sans-serif;max-width:360px;margin:80px auto;padding:0 16px;color:#2b2b2b'>"
            f"<h2 style='color:#ed1b34'>Semafor Provozu</h2><p>Přihlas se firemním účtem (jako do Windows).</p>{error_html}"
            f"<form method='post' action='{escape(s.base_path)}/auth/login'>"
            f"<input type='hidden' name='next' value='{escape(nxt)}'>"
            f"<label>Uživatelské jméno<input name='username' value='{escape(username)}' placeholder='jmeno.prijmeni' "
            f"autocomplete='username' required autofocus style='{field}'></label>"
            f"<label>Heslo<input name='password' type='password' autocomplete='current-password' required "
            f"style='{field}'></label>"
            f"<button type='submit' style='padding:9px 18px;font-size:15px;background:#ed1b34;color:#fff;border:0;"
            f"border-radius:4px;cursor:pointer'>Přihlásit</button></form></body></html>")


def _origin_ok(request: Request, settings: Settings) -> bool:
    """Shoda hlavičky Origin s veřejnou adresou aplikace, pokud ji prohlížeč poslal."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    pu = urlsplit(settings.public_url)
    return origin.rstrip("/") == f"{pu.scheme}://{pu.netloc}"


def same_origin_ok(request: Request, settings: Settings) -> bool:
    """Ochrana proti CSRF u zápisů: vlastní hlavička + shoda Origin, pokud ji prohlížeč poslal."""
    if request.headers.get("x-semafor-request") != "1":
        return False
    return _origin_ok(request, settings)
