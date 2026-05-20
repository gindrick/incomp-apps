from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.dependencies import RedirectException
from app.db.connection import Base, engine
from app.routers import auth, candidates, documents, evaluations, job_descriptions, recruitments
from config import ROOT, settings


class _FaultTolerantRotatingHandler(logging.handlers.RotatingFileHandler):
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            pass  # another process holds the file; keep writing to current file


def _configure_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = _FaultTolerantRotatingHandler(
        log_dir / "backend.out.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(sh)
    for noisy in ("httpx", "httpcore", "uvicorn.access", "litellm", "pdfminer", "openai", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_configure_logging()

app = FastAPI(title="TalentDesk", version="1.0.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)

from app.templates_config import templates  # noqa: F401 — registers filters/globals as side effect

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.exception_handler(RedirectException)
async def redirect_exception_handler(request: Request, exc: RedirectException):
    return RedirectResponse(url=exc.url, status_code=302)


@app.on_event("startup")
def on_startup() -> None:
    from sqlalchemy import text

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            for _col_sql in [
                "ALTER TABLE candidate_documents ADD extracted_json NVARCHAR(MAX) NULL",
                "ALTER TABLE candidate_evaluations ADD ai_recommendation NVARCHAR(20) NULL",
                "ALTER TABLE candidate_evaluations ADD ai_red_flags NVARCHAR(MAX) NULL",
                "ALTER TABLE candidate_evaluations ADD ai_current_role NVARCHAR(200) NULL",
                "ALTER TABLE job_descriptions ADD requirements_json NVARCHAR(MAX) NULL",
            ]:
                try:
                    conn.execute(text(_col_sql))
                    conn.commit()
                except Exception:
                    pass  # column already exists


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments", status_code=302)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "talentdesk", "env": settings.env}


app.include_router(auth.router)
app.include_router(job_descriptions.router)
app.include_router(recruitments.router)
app.include_router(candidates.router)
app.include_router(documents.router)
app.include_router(evaluations.router)
