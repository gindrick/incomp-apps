from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import ldap_bind
from config import ROOT, settings
from xml_downloader import download_xml, validate_url


def _configure_logging() -> None:
    log_dir = ROOT / "logs"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(sh)
    try:
        log_dir.mkdir(exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except PermissionError:
        logging.getLogger(__name__).warning("Cannot write to logs/app.log — file logging disabled")
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Feeder", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)

templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.globals["prefix"] = settings.proxy_prefix

DATA_DIR = Path(settings.data_dir)


def _current_user(request: Request) -> str | None:
    if settings.dev_auth_bypass and settings.env != "prod":
        return settings.dev_auth_user
    return request.session.get("user")


@app.get("/health")
def health():
    return {"status": "ok", "service": "feeder"}


@app.get("/login")
def get_login(request: Request):
    if _current_user(request):
        return RedirectResponse(url=f"{settings.proxy_prefix}/", status_code=302)
    error = request.query_params.get("error")
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
def post_login(request: Request, username: str = Form(...), password: str = Form(...)):
    ok = ldap_bind(username, password)
    if not ok:
        logger.info("LOGIN_FAILED user=%s", username)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Neplatné přihlašovací údaje nebo nepovolený uživatel."},
            status_code=401,
        )
    request.session["user"] = username.strip().split("@")[0]
    logger.info("LOGIN_SUCCESS user=%s", username)
    return RedirectResponse(url=f"{settings.proxy_prefix}/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=f"{settings.proxy_prefix}/login", status_code=302)


@app.get("/")
def index(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse(url=f"{settings.proxy_prefix}/login", status_code=302)
    return templates.TemplateResponse(request, "index.html", {"user": user})


@app.post("/api/validate")
async def api_validate(request: Request):
    if not _current_user(request):
        return {"valid": False, "message": "Nejste přihlášen."}
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        return {"valid": False, "message": "Zadejte URL."}
    ok, msg = validate_url(url)
    return {"valid": ok, "message": msg}


@app.post("/api/run")
async def api_run(request: Request):
    if not _current_user(request):
        return {"success": False, "error": "Nejste přihlášen."}
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        return {"success": False, "error": "Zadejte URL."}
    try:
        file_path = download_xml(url, DATA_DIR)
        logger.info("DOWNLOAD_OK url=%s file=%s user=%s", url, file_path.name, _current_user(request))
        return {"success": True, "file": file_path.name}
    except Exception as e:
        logger.error("DOWNLOAD_FAILED url=%s error=%s", url, e)
        return {"success": False, "error": str(e)}


@app.get("/download/{filename}")
def download_file(filename: str, request: Request):
    if not _current_user(request):
        return RedirectResponse(url=f"{settings.proxy_prefix}/login", status_code=302)
    safe_name = Path(filename).name
    file_path = DATA_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        return RedirectResponse(url=f"{settings.proxy_prefix}/?error=Soubor+nenalezen", status_code=302)
    return FileResponse(path=str(file_path), filename=safe_name, media_type="application/xml")
