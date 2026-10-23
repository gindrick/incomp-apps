from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

UPSTREAM_TIMEOUT = httpx.Timeout(60.0)

logger = logging.getLogger(__name__)

ROUTER_ROOT = Path(__file__).resolve().parent
APPS_CONFIG = ROUTER_ROOT / "apps.json"

app = FastAPI(title="Router", version="1.0.0")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/auth/login", include_in_schema=False)
async def auth_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ai_framework/auth/login", status_code=307)


@app.post("/auth/login", include_in_schema=False)
async def auth_login_post_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ai_framework/auth/login", status_code=307)


@app.get("/auth/logout", include_in_schema=False)
async def auth_logout_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ai_framework/auth/logout", status_code=307)


@app.get("/auth/callback", include_in_schema=False)
async def auth_callback_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ai_framework/auth/callback", status_code=307)


def _load_apps() -> list[dict]:
    if not APPS_CONFIG.exists():
        return []
    text = APPS_CONFIG.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    return json.loads(text)


def _find_entry(path: str) -> tuple[dict, str] | None:
    for entry in _load_apps():
        prefix = "/" + entry["path"].strip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return entry, prefix
    return None


def _rewrite_location_header(location: str, target: str, prefix: str, strip_prefix: bool) -> str:
    if not location:
        return location

    split = urlsplit(location)

    # Internal absolute URL from upstream (e.g. http://localhost:8001/...) -> public relative path.
    if split.scheme and split.netloc and location.startswith(target):
        upstream_path = split.path or "/"
        if strip_prefix:
            public_path = prefix + (upstream_path if upstream_path.startswith("/") else f"/{upstream_path}")
        else:
            public_path = upstream_path
        return urlunsplit(("", "", public_path, split.query, split.fragment))

    # Relative upstream redirect when prefix is stripped: re-add the public app prefix.
    if location.startswith("/") and strip_prefix:
        if location == prefix or location.startswith(prefix + "/"):
            return location
        return prefix + location

    return location


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy(request: Request, full_path: str):
    path = "/" + full_path
    result = _find_entry(path)

    if result is None:
        return Response(
            content=(
                "<h2>Router — Hranipex</h2>"
                "<p>Požadovaná aplikace nebyla nalezena.</p>"
                "<p>Zkontrolujte URL adresu.</p>"
            ),
            status_code=404,
            media_type="text/html",
        )

    entry, prefix = result
    # An app served only over HTTPS: plain-HTTP requests (old :8000 links) are sent to its https_url.
    https_url = entry.get("https_url")
    if https_url and request.url.scheme == "http":
        location = https_url.rstrip("/") + path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(url=location, status_code=307)

    target = entry["target"].rstrip("/")
    strip_prefix = bool(entry.get("strip_prefix", True))
    stripped_path = path[len(prefix):] or "/"
    forward_path = stripped_path if strip_prefix else path
    target_url = target + forward_path
    if request.url.query:
        target_url += "?" + request.url.query

    headers = dict(request.headers)
    headers.pop("host", None)
    # The router is the edge: what the client claims about itself is replaced,
    # never passed on, so an app can trust these for rate limits and links.
    headers["x-forwarded-for"] = request.client.host if request.client else ""
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-prefix"] = prefix

    body = await request.body()

    if entry.get("stream"):
        return await _proxy_streaming(request.method, target_url, headers, body, target, prefix, strip_prefix)

    async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, follow_redirects=False) as client:
        response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    return _client_response(response, iter([response.content]), target, prefix, strip_prefix)


async def _proxy_streaming(method: str, url: str, headers: dict, body: bytes,
                           target: str, prefix: str, strip_prefix: bool) -> StreamingResponse:
    """Pass the upstream body on as it arrives, so Server-Sent Events are not held back."""
    client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, follow_redirects=False)
    try:
        upstream = await client.send(client.build_request(method, url, headers=headers, content=body), stream=True)
    except BaseException:
        await client.aclose()
        raise

    async def chunks():
        # Runs to the end also when the browser disconnects (the task is cancelled
        # inside this loop), so the upstream connection never leaks.
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return _client_response(upstream, chunks(), target, prefix, strip_prefix)


def _client_response(response: httpx.Response, content, target: str, prefix: str, strip_prefix: bool) -> StreamingResponse:
    # Set-Cookie may repeat and must not be folded into one comma-joined header
    # (a browser then reads only the first cookie); it is re-added one by one below.
    response_headers = {k: v for k, v in response.headers.items() if k != "set-cookie"}
    response_headers.pop("transfer-encoding", None)

    if "location" in response_headers:
        response_headers["location"] = _rewrite_location_header(
            response_headers["location"],
            target,
            prefix,
            strip_prefix,
        )

    proxied = StreamingResponse(
        content=content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )
    for cookie in response.headers.get_list("set-cookie"):
        proxied.headers.append("set-cookie", cookie)
    return proxied