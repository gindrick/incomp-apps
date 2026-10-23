"""REST API pro frontendový adaptér ``platform.js``.

Všechny cesty vyžadují přihlášení. Zápisy navíc vyžadují hlavičku
``X-Semafor-Request: 1`` (ochrana proti CSRF; formulář z cizí stránky ji poslat neumí).
"""
from __future__ import annotations

import json
from typing import Any

import anyio
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth import require_principal, same_origin_ok
from .config import Settings
from .docstore.store import now_ms
from .errors import PermissionDenied, TooLarge
from .principal import Principal

router = APIRouter(prefix="/api")


def _store(request: Request):
    return request.app.state.store


def writer(request: Request, p: Principal = Depends(require_principal)) -> Principal:
    if not same_origin_ok(request, request.app.state.settings):
        raise PermissionDenied("chybí ochranná hlavička požadavku")
    return p


# ---------------------------------------------------------------------- identita
@router.get("/me")
def me(request: Request, p: Principal = Depends(require_principal)):
    s: Settings = request.app.state.settings
    return {"id": p.id, "name": p.name, "email": p.email, "avatarUrl": "", "color": "#888888",
            "isOwner": p.is_admin, "canEdit": p.can_edit, "roles": list(p.roles), "environment": s.environment}


class ProfilesBody(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=500)


@router.post("/users/profiles")
def profiles(body: ProfilesBody, request: Request, p: Principal = Depends(require_principal)):
    return request.app.state.directory.profiles(body.ids, p)


@router.get("/users/search")
def search(request: Request, q: str = Query("", max_length=100), p: Principal = Depends(require_principal)):
    return request.app.state.directory.search(q, p)


# ---------------------------------------------------------------------- dokumenty
class SetBody(BaseModel):
    data: dict[str, Any]
    ifVersion: int | None = None


class UpdateBody(BaseModel):
    patch: dict[str, Any]
    ifVersion: int | None = None


class LeaseBody(BaseModel):
    holder: str = Field(min_length=1, max_length=200)
    ttlMs: int = 30000


@router.get("/docs/{path:path}")
def get_doc(path: str, request: Request, p: Principal = Depends(require_principal)):
    return _store(request).get(p, path).to_api()


@router.put("/docs/{path:path}")
def set_doc(path: str, body: SetBody, request: Request, p: Principal = Depends(writer)):
    d = _store(request).set(p, path, body.data, if_version=body.ifVersion)
    return {"version": d.version, "seq": d.seq}


@router.patch("/docs/{path:path}")
def update_doc(path: str, body: UpdateBody, request: Request, p: Principal = Depends(writer)):
    d = _store(request).update(p, path, body.patch, if_version=body.ifVersion)
    return {"version": d.version, "seq": d.seq}


@router.delete("/docs/{path:path}")
def delete_doc(path: str, request: Request, ifVersion: int | None = None, p: Principal = Depends(writer)):
    _store(request).delete(p, path, if_version=ifVersion)
    return {"ok": True}


@router.post("/leases/{path:path}")
def acquire(path: str, body: LeaseBody, request: Request, p: Principal = Depends(writer)):
    return _store(request).acquire(p, path, body.holder, body.ttlMs)


@router.get("/collections/{path:path}")
def list_collection(path: str, request: Request, p: Principal = Depends(require_principal)):
    docs, seq = _store(request).list_collection(p, path)
    return {"seq": seq, "docs": [d.to_api() for d in docs]}


# ---------------------------------------------------------------------- živé změny
@router.get("/changes")
def changes(request: Request, since: int = Query(0, ge=0), p: Principal = Depends(require_principal)):
    items, seq = _store(request).changes_since(p, since)
    return {"seq": seq, "changes": items}


@router.get("/stream")
async def stream(request: Request, since: int = Query(0, ge=0), p: Principal = Depends(require_principal)):
    """Server-Sent Events: posílá dávky změn od ``since``. Prohlížeč se po výpadku připojí sám."""
    s: Settings = request.app.state.settings
    store, broker = _store(request), request.app.state.broker

    # proud skončí nejpozději s relací (odebraná role / odhlášení se projeví nejpozději s koncem relace)
    session_at = int((request.session.get("user") or {}).get("at", 0))
    session_left_s = max(0.0, (session_at + s.session_max_age_s * 1000 - now_ms()) / 1000)

    async def gen():
        last = since
        deadline = anyio.current_time() + min(s.sse_max_duration_s, session_left_s)
        yield "retry: 3000\n\n"
        while anyio.current_time() < deadline:
            if await request.is_disconnected():
                return
            ticket = broker.ticket()   # před čtením: změna během čtení probudí hned další kolo
            items, seq = await anyio.to_thread.run_sync(store.changes_since, p, last)
            if items or seq != last:
                last = seq
                yield f"id: {seq}\nevent: changes\ndata: {json.dumps({'seq': seq, 'changes': items}, ensure_ascii=False)}\n\n"
            changed = await broker.wait(ticket, s.sse_heartbeat_s)
            if not changed:
                yield ": ping\n\n"

    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------- přílohy
@router.post("/assets")
async def upload(request: Request, file: UploadFile = File(...), type: str = Form(""), p: Principal = Depends(writer)):
    s: Settings = request.app.state.settings
    data = await file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise TooLarge("soubor je nad limit")
    return await anyio.to_thread.run_sync(
        request.app.state.assets.save, p, file.filename or "soubor", type or file.content_type or "", data)
