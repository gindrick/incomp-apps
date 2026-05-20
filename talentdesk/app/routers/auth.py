from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.ldap import AUTH_LOGGER, ldap_bind
from app.templates_config import templates
from config import settings

router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/login", include_in_schema=False)
def get_login(request: Request):
    if settings.dev_auth_bypass and settings.env != "prod":
        return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments", status_code=302)
    if request.session.get("user"):
        return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments", status_code=302)
    error = request.query_params.get("error")
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login", include_in_schema=False)
def post_login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = _client_ip(request)

    if not ldap_bind(username, password):
        AUTH_LOGGER.info("LOGIN_FAILED user=%s ip=%s", username.strip(), ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Neplatné přihlašovací údaje nebo nepovolený uživatel."},
            status_code=401,
        )

    norm = username.strip().lower()
    email = norm if "@" in norm else f"{norm}@{settings.ldap_domain.lower()}"
    bare = norm.split("@")[0]
    request.session["user"] = {"name": bare, "email": email, "auth_provider": "ldap"}
    AUTH_LOGGER.info("LOGIN_SUCCESS user=%s email=%s ip=%s", username.strip(), email, ip)
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments", status_code=302)


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=f"{settings.proxy_prefix}/login", status_code=302)
