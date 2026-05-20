from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.connection import get_db
from app.db.models import Candidate, CandidateEvaluation, EvaluationOverride, Recruitment, RecruitmentAccess, User
from app.routers.documents import _EXTRACT_STATUS
from app.routers.evaluations import _EVAL_STATUS  # noqa: F401 — also used in this module
from app.services.access_control import write_audit
from app.services.hash_service import compute_documents_hash
from app.templates_config import templates
from config import settings

router = APIRouter(prefix="/candidates", tags=["candidates"])

VALID_STATUSES = ("new", "active", "interview", "offer", "hired", "rejected")


@router.post("/recruitments/{recruitment_id}/create")
def create_candidate(
    recruitment_id: int,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    age: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_access(recruitment_id, current_user, db)
    candidate = Candidate(
        recruitment_id=recruitment_id,
        first_name=first_name.strip() or None,
        last_name=last_name.strip() or None,
        email=email.strip() or None,
        phone=phone.strip() or None,
        age=int(age) if age.strip() else None,
    )
    db.add(candidate)
    db.commit()
    write_audit(db, current_user.id, "create_candidate", "candidate", candidate.id)
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments/{recruitment_id}", status_code=302)


@router.get("/{candidate_id}/modal")
def candidate_modal(candidate_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    current_eval = next((e for e in candidate.evaluations if e.is_current), None)
    overrides = {}
    if current_eval:
        for ov in current_eval.overrides:
            overrides[ov.field_key] = ov.user_value
    skill_ratings = []
    if current_eval and current_eval.ai_output_json:
        try:
            ai_data = json.loads(current_eval.ai_output_json)
            skill_ratings = ai_data.get("skill_ratings", [])
        except Exception:
            pass
    docs = [d for d in candidate.documents if not d.is_deleted]

    active_docs = [d for d in candidate.documents if not d.is_deleted and d.extracted_text]
    docs_hash = compute_documents_hash([d.sha256_hash for d in active_docs]) if active_docs else ""
    eval_up_to_date = bool(current_eval and current_eval.documents_hash == docs_hash)

    skill_user_ratings: dict[str, float] = {}
    pi_rating: float | None = None
    pi_note: str | None = None
    if current_eval:
        for ov in current_eval.overrides:
            if ov.field_key.startswith("skill_rating:"):
                skill_name = ov.field_key[len("skill_rating:"):]
                try:
                    skill_user_ratings[skill_name] = float(ov.user_value)
                except ValueError:
                    pass
            elif ov.field_key == "personal_impression":
                try:
                    pi_rating = float(ov.user_value)
                    pi_note = ov.override_note
                except ValueError:
                    pass

    ai_skill_avg = (sum(sr["rating"] for sr in skill_ratings) / len(skill_ratings)) if skill_ratings else None
    all_user_vals = list(skill_user_ratings.values()) + ([pi_rating] if pi_rating else [])
    user_skill_avg = (sum(all_user_vals) / len(all_user_vals)) if all_user_vals else None

    is_eval_pending = _EVAL_STATUS.get(candidate_id) == "pending"

    return templates.TemplateResponse(
        request,
        "candidates/card_modal.html",
        {
            "candidate": candidate,
            "current_eval": current_eval,
            "overrides": overrides,
            "skill_ratings": skill_ratings,
            "docs": docs,
            "user": current_user,
            "statuses": VALID_STATUSES,
            "eval_up_to_date": eval_up_to_date,
            "is_eval_pending": is_eval_pending,
            "skill_user_ratings": skill_user_ratings,
            "ai_skill_avg": ai_skill_avg,
            "user_skill_avg": user_skill_avg,
            "pi_rating": pi_rating,
            "pi_note": pi_note,
        },
    )


@router.get("/{candidate_id}/card")
def candidate_card(candidate_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    current_eval = next((e for e in candidate.evaluations if e.is_current), None)
    is_pending = _EVAL_STATUS.get(candidate_id) == "pending"

    skill_user_ratings: dict[str, float] = {}
    pi_rating_card: float | None = None
    if current_eval:
        for ov in current_eval.overrides:
            if ov.field_key.startswith("skill_rating:"):
                skill_name = ov.field_key[len("skill_rating:"):]
                try:
                    skill_user_ratings[skill_name] = float(ov.user_value)
                except ValueError:
                    pass
            elif ov.field_key == "personal_impression":
                try:
                    pi_rating_card = float(ov.user_value)
                except ValueError:
                    pass
    all_user_vals = list(skill_user_ratings.values()) + ([pi_rating_card] if pi_rating_card else [])
    user_skill_avg = (sum(all_user_vals) / len(all_user_vals)) if all_user_vals else None

    return templates.TemplateResponse(
        request,
        "candidates/card.html",
        {
            "c": candidate,
            "current_eval": current_eval,
            "is_pending": is_pending,
            "user": current_user,
            "user_skill_avg": user_skill_avg,
        },
    )


@router.get("/{candidate_id}/extraction/status")
def extraction_status(candidate_id: int, current_user: User = Depends(get_current_user)):
    status = _EXTRACT_STATUS.get(candidate_id, "done")
    pfx = settings.proxy_prefix
    if status == "pending":
        return HTMLResponse(
            f'<div id="candidate-{candidate_id}"'
            f' hx-get="{pfx}/candidates/{candidate_id}/extraction/status"'
            f' hx-trigger="every 2s" hx-swap="outerHTML"'
            f' class="bg-gray-900 border border-sky-900 rounded-xl p-4 flex flex-col gap-3">'
            f'<div class="flex items-center gap-2">'
            f'<span class="text-xs text-sky-400 animate-pulse">⟳ Extracting CV data...</span>'
            f'</div>'
            f'<div class="h-2 bg-gray-800 rounded animate-pulse w-3/4 mt-1"></div>'
            f'<div class="h-2 bg-gray-800 rounded animate-pulse w-1/2 mt-1.5"></div>'
            f'<div class="h-2 bg-gray-800 rounded animate-pulse w-2/3 mt-1.5"></div>'
            f'</div>'
        )
    _EXTRACT_STATUS.pop(candidate_id, None)
    return HTMLResponse(
        f'<div id="candidate-{candidate_id}"'
        f' hx-get="{pfx}/candidates/{candidate_id}/card"'
        f' hx-trigger="load" hx-swap="outerHTML"></div>'
    )


@router.post("/{candidate_id}/status")
def update_status(
    candidate_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    if status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid status")
    old_status = candidate.status
    candidate.status = status
    db.commit()
    write_audit(db, current_user.id, "status_change", "candidate", candidate_id, f"{old_status}→{status}")
    return HTMLResponse(f'<span class="status-badge status-{status}">{_status_label(status)}</span>', status_code=200)


@router.post("/{candidate_id}/delete")
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    recruitment_id = candidate.recruitment_id
    db.delete(candidate)
    db.commit()
    write_audit(db, current_user.id, "delete_candidate", "candidate", candidate_id)
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments/{recruitment_id}", status_code=302)


def _get_candidate_or_404(candidate_id: int, db: Session) -> Candidate:
    candidate = db.query(Candidate).filter_by(id=candidate_id).first()
    if not candidate:
        raise HTTPException(404)
    return candidate


def _check_access(recruitment_id: int, user: User, db: Session) -> None:
    if user.role == "admin":
        return
    access = db.query(RecruitmentAccess).filter_by(recruitment_id=recruitment_id, user_id=user.id).first()
    if not access:
        raise HTTPException(403)


def _status_label(status: str) -> str:
    return {
        "new": "New",
        "active": "In Process",
        "interview": "Interview",
        "offer": "Offer",
        "hired": "Hired",
        "rejected": "Rejected",
    }.get(status, status)
