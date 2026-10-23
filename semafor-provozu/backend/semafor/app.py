"""Sestavení aplikace FastAPI.

Spuštění (vývoj):  uvicorn semafor.app:create_app --factory --port 8000
Spuštění (server): python -m semafor serve   (viz deploy/windows)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .api import router as api_router
from .assets import AssetStore
from .auth import build_oauth, router as auth_router
from .config import Settings, get_settings
from .db import init_schema, make_engine
from .directory import Directory
from .docstore.store import DocumentStore
from .errors import AppError
from .logging_setup import setup_logging
from .realtime import ChangeBroker
from .web import load_index_template, router as web_router

log = logging.getLogger(__name__)


class StripBasePath:
    """Přijme požadavek s base path i bez ní.

    Směrování před aplikací (IIS, reverse proxy) může prefix ``/semafor``
    předat dál, nebo odříznout; aplikace funguje v obou případech.
    """

    def __init__(self, app: ASGIApp, base_path: str):
        self.app = app
        self.base = base_path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if self.base and scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.base or path.startswith(self.base + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.base):] or "/"
                scope["raw_path"] = scope["path"].encode("utf-8")
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for k, v in ((b"x-content-type-options", b"nosniff"),
                             (b"referrer-policy", b"same-origin"),
                             (b"x-frame-options", b"SAMEORIGIN")):
                    if not any(h[0] == k for h in headers):
                        headers.append((k, v))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings)
    engine = make_engine(settings.database_url, pool_size=settings.db_pool_size, echo=settings.db_echo)
    init_schema(engine)

    broker_ref: dict = {}
    store = DocumentStore(engine, max_doc_bytes=settings.max_doc_bytes, max_lease_ttl_ms=settings.max_lease_ttl_ms,
                          on_change=lambda: broker_ref["b"].notify_threadsafe() if "b" in broker_ref else None)
    broker = ChangeBroker(store.current_seq, settings.change_poll_interval_s)
    broker_ref["b"] = broker

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await broker.start()
        log.info("Semafor Provozu %s běží (%s, base path %r)", __version__, settings.environment, settings.base_path)
        yield
        await broker.stop()
        engine.dispose()

    app = FastAPI(title="Semafor Provozu", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs" if settings.environment != "production" else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if settings.environment != "production" else None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store
    app.state.broker = broker
    app.state.directory = Directory(engine, store, settings)
    app.state.assets = AssetStore(engine, settings)
    app.state.oauth = build_oauth(settings)
    app.state.index_template = load_index_template()

    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError):
        return JSONResponse(exc.to_dict(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError):
        return JSONResponse({"code": "invalid_argument", "message": "neplatný požadavek", "detail": exc.errors()[:5]},
                            status_code=400)

    app.include_router(api_router)
    app.include_router(auth_router)
    app.include_router(web_router)

    # pořadí: vnější obal je poslední přidaný
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="semafor_session",
        max_age=settings.session_max_age_s,
        path=(settings.base_path or "/"),
        same_site=settings.session_same_site,
        https_only=settings.secure_cookies,
    )
    app.add_middleware(SecurityHeaders)
    app.add_middleware(StripBasePath, base_path=settings.base_path)
    return app
