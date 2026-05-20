from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.connection import get_db
from app.db.models import Candidate, CandidateDocument, CandidateEvaluation, EvaluationOverride, RecruitmentAccess, User
from app.services.access_control import write_audit
from app.services.hash_service import compute_documents_hash
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evaluations"])

# candidate_id → evaluation status for polling
_EVAL_STATUS: dict[int, Literal["pending", "done", "error"]] = {}


@router.post("/candidates/{candidate_id}/evaluate")
def trigger_evaluation(
    candidate_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)

    active_docs = [d for d in candidate.documents if not d.is_deleted and d.extracted_text]
    if not active_docs:
        raise HTTPException(400, "No documents with extracted text available for evaluation")

    docs_hash = compute_documents_hash([d.sha256_hash for d in active_docs])
    current_eval = db.query(CandidateEvaluation).filter_by(candidate_id=candidate_id, is_current=True).first()
    if current_eval and current_eval.documents_hash == docs_hash:
        return HTMLResponse('<div class="text-sm text-gray-400">Evaluation is up to date.</div>')

    _EVAL_STATUS[candidate_id] = "pending"
    jd = candidate.recruitment.job_description
    jd_text = jd.content
    from app.services.llm_service import _format_document
    docs_text = "\n\n---\n\n".join(
        _format_document(d.original_name, d.file_type, d.extracted_json, d.extracted_text or "")
        for d in active_docs
    )
    jd_requirements = None
    if jd.requirements_json:
        from app.schemas.llm_output import JDRequirements
        try:
            jd_requirements = JDRequirements.model_validate_json(jd.requirements_json)
        except Exception:
            logger.warning("Failed to parse requirements_json for jd_id=%s, falling back to raw JD text", jd.id)

    override_data = {}
    if current_eval:
        for ov in current_eval.overrides:
            override_data[ov.field_key] = {"ai_value": ov.ai_value, "user_value": ov.user_value, "note": ov.override_note}

    background_tasks.add_task(
        _run_evaluation,
        candidate_id=candidate_id,
        jd_id=jd.id,
        jd_text=jd_text,
        docs_text=docs_text,
        docs_hash=docs_hash,
        jd_snapshot=jd_text,
        jd_requirements=jd_requirements,
        previous_overrides=override_data,
        db_session_factory=db.__class__,
        bind=db.get_bind(),
        user_id=current_user.id,
    )
    write_audit(db, current_user.id, "trigger_evaluate", "candidate", candidate_id)
    pfx = settings.proxy_prefix
    return HTMLResponse(
        f'<div hx-get="{pfx}/candidates/{candidate_id}/evaluation/status" hx-trigger="every 2s" hx-swap="outerHTML"'
        f' class="flex items-center gap-2 text-sm text-yellow-400 py-1">'
        f'<span class="animate-spin inline-block">&#9851;</span>'
        f'<span>AI evaluation in progress...</span>'
        f'</div>'
    )


@router.get("/candidates/{candidate_id}/evaluation/status")
def evaluation_status(candidate_id: int, current_user: User = Depends(get_current_user)):
    status = _EVAL_STATUS.get(candidate_id, "done")
    pfx = settings.proxy_prefix
    if status == "pending":
        return HTMLResponse(
            f'<div hx-get="{pfx}/candidates/{candidate_id}/evaluation/status" hx-trigger="every 2s" hx-swap="outerHTML"'
            f' class="flex items-center gap-2 text-sm text-yellow-400 py-1">'
            f'<span class="animate-spin inline-block">&#9851;</span>'
            f'<span>AI evaluation in progress...</span>'
            f'</div>'
        )
    if status == "error":
        _EVAL_STATUS.pop(candidate_id, None)
        return HTMLResponse('<div class="text-sm text-red-400">Evaluation failed. Please try again.</div>')
    _EVAL_STATUS.pop(candidate_id, None)
    return HTMLResponse(
        f'<div hx-get="{pfx}/candidates/{candidate_id}/modal" hx-trigger="load" hx-target="#modal-content"></div>'
        f'<div id="candidate-{candidate_id}" hx-swap-oob="true"'
        f' hx-get="{pfx}/candidates/{candidate_id}/card" hx-trigger="load" hx-swap="outerHTML"></div>'
    )


@router.post("/candidates/{candidate_id}/evaluation/override")
def save_override(
    candidate_id: int,
    field_key: str = Form(...),
    user_value: str = Form(...),
    override_note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    current_eval = db.query(CandidateEvaluation).filter_by(candidate_id=candidate_id, is_current=True).first()
    if not current_eval:
        raise HTTPException(404, "No current evaluation")

    existing = db.query(EvaluationOverride).filter_by(evaluation_id=current_eval.id, field_key=field_key).first()
    ai_value = None
    if current_eval.ai_output_json:
        try:
            ai_data = json.loads(current_eval.ai_output_json)
            ai_value = str(ai_data.get(field_key, ""))
        except Exception:
            pass

    if existing:
        existing.user_value = user_value
        existing.override_note = override_note or None
        existing.overridden_by = current_user.id
    else:
        db.add(EvaluationOverride(
            evaluation_id=current_eval.id,
            field_key=field_key,
            ai_value=ai_value,
            user_value=user_value,
            override_note=override_note or None,
            overridden_by=current_user.id,
        ))
    db.commit()
    write_audit(db, current_user.id, "override", "evaluation", current_eval.id, f"field={field_key}")
    return HTMLResponse(f'<span class="text-green-400 text-xs">Saved</span>', status_code=200)


def _get_candidate_or_404(candidate_id: int, db: Session) -> Candidate:
    c = db.query(Candidate).filter_by(id=candidate_id).first()
    if not c:
        raise HTTPException(404)
    return c


def _check_access(recruitment_id: int, user: User, db: Session) -> None:
    if user.role == "admin":
        return
    if not db.query(RecruitmentAccess).filter_by(recruitment_id=recruitment_id, user_id=user.id).first():
        raise HTTPException(403)


def _run_evaluation(
    candidate_id: int,
    jd_id: int,
    jd_text: str,
    docs_text: str,
    docs_hash: str,
    jd_snapshot: str,
    previous_overrides: dict,
    db_session_factory,
    bind,
    user_id: int,
    jd_requirements=None,
) -> None:
    from app.services.llm_service import evaluate_candidate

    db = db_session_factory(bind=bind)
    try:
        result = evaluate_candidate(jd_text, docs_text, jd_requirements=jd_requirements)

        db.query(CandidateEvaluation).filter_by(candidate_id=candidate_id, is_current=True).update({"is_current": False})
        db.commit()

        ai_json = result.model_dump_json()
        eval_row = CandidateEvaluation(
            candidate_id=candidate_id,
            documents_hash=docs_hash,
            jd_snapshot=jd_snapshot,
            ai_output_json=ai_json,
            ai_summary=result.summary,
            ai_strengths=json.dumps(result.strengths, ensure_ascii=False),
            ai_weaknesses=json.dumps(result.weaknesses, ensure_ascii=False),
            ai_jd_match=result.jd_match_analysis,
            ai_skill_tags=json.dumps(result.skill_tags, ensure_ascii=False),
            ai_missing_tags=json.dumps(result.missing_skill_tags, ensure_ascii=False),
            ai_questions=json.dumps(result.recommended_questions, ensure_ascii=False),
            ai_current_salary=result.current_salary,
            ai_expected_salary=result.expected_salary,
            ai_rating=result.overall_rating,
            ai_recommendation=result.recommendation,
            ai_red_flags=json.dumps(result.red_flags, ensure_ascii=False),
            ai_current_role=result.current_role,
            is_current=True,
        )
        db.add(eval_row)
        db.commit()
        db.refresh(eval_row)

        # Carry forward overrides from previous evaluation
        for field_key, ov_data in previous_overrides.items():
            db.add(EvaluationOverride(
                evaluation_id=eval_row.id,
                field_key=field_key,
                ai_value=ov_data.get("ai_value"),
                user_value=ov_data["user_value"],
                override_note=ov_data.get("note"),
                overridden_by=user_id,
            ))
        db.commit()

        candidate = db.query(Candidate).filter_by(id=candidate_id).first()
        if candidate:
            candidate.needs_reevaluation = False
            if result.first_name:
                candidate.first_name = result.first_name
            if result.last_name:
                candidate.last_name = result.last_name
            if result.age:
                candidate.age = result.age
            if result.contact_email and not candidate.email:
                candidate.email = result.contact_email
            if result.contact_phone and not candidate.phone:
                candidate.phone = result.contact_phone
            db.commit()

        _EVAL_STATUS[candidate_id] = "done"
    except Exception as exc:
        logger.error("Evaluation failed for candidate %s: %s", candidate_id, exc)
        _EVAL_STATUS[candidate_id] = "error"
    finally:
        db.close()
