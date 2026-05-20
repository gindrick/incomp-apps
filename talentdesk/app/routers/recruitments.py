from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin, require_recruitment_access
from app.db.connection import get_db
from app.db.models import JobDescription, Recruitment, RecruitmentAccess, User
from app.routers.evaluations import _EVAL_STATUS
from app.services.access_control import write_audit
from app.templates_config import templates
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recruitments", tags=["recruitments"])


@router.get("")
def list_recruitments(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        recruitments = db.query(Recruitment).order_by(Recruitment.created_at.desc()).all()
    else:
        access_ids = db.query(RecruitmentAccess.recruitment_id).filter_by(user_id=current_user.id).subquery()
        recruitments = db.query(Recruitment).filter(Recruitment.id.in_(access_ids)).order_by(Recruitment.created_at.desc()).all()
    return templates.TemplateResponse(request, "recruitments/list.html", {"recruitments": recruitments, "user": current_user})


@router.get("/new")
def new_recruitment_form(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    jds = db.query(JobDescription).filter_by(is_active=True).order_by(JobDescription.title).all()
    return templates.TemplateResponse(request, "recruitments/create.html", {"jds": jds, "user": current_user})


@router.post("/new")
def create_recruitment(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    jd_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rec = Recruitment(title=title.strip(), jd_id=jd_id, created_by=current_user.id)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    write_audit(db, current_user.id, "create_recruitment", "recruitment", rec.id)

    jd = db.query(JobDescription).filter_by(id=jd_id).first()
    if jd and not jd.requirements_json:
        background_tasks.add_task(
            _extract_jd_requirements,
            jd_id=jd_id,
            db_session_factory=db.__class__,
            bind=db.get_bind(),
        )

    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments/{rec.id}", status_code=302)


@router.get("/{recruitment_id}")
def get_recruitment(
    recruitment_id: int,
    request: Request,
    sort: str = "created_at_desc",
    status_filter: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_access(recruitment_id, current_user, db)
    rec = db.query(Recruitment).filter_by(id=recruitment_id).first()
    if not rec:
        raise HTTPException(404)
    candidates = _sorted_candidates(rec.candidates, sort, status_filter)
    all_users = db.query(User).filter_by(is_active=True).order_by(User.username).all() if current_user.role == "admin" else []
    access_user_ids = {a.user_id for a in rec.access}
    return templates.TemplateResponse(
        request,
        "recruitments/detail.html",
        {
            "rec": rec,
            "candidates": candidates,
            "user": current_user,
            "all_users": all_users,
            "access_user_ids": access_user_ids,
            "sort": sort,
            "status_filter": status_filter,
            "pending_ids": {cid for cid, st in _EVAL_STATUS.items() if st == "pending"},
        },
    )


@router.post("/{recruitment_id}/access")
def grant_access(
    recruitment_id: int,
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = db.query(RecruitmentAccess).filter_by(recruitment_id=recruitment_id, user_id=user_id).first()
    if not existing:
        entry = RecruitmentAccess(recruitment_id=recruitment_id, user_id=user_id, granted_by=current_user.id)
        db.add(entry)
        db.commit()
        write_audit(db, current_user.id, "grant_access", "recruitment", recruitment_id, f"user_id={user_id}")
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments/{recruitment_id}", status_code=302)


@router.post("/{recruitment_id}/access/{user_id}/delete")
def revoke_access(
    recruitment_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    db.query(RecruitmentAccess).filter_by(recruitment_id=recruitment_id, user_id=user_id).delete()
    db.commit()
    write_audit(db, current_user.id, "revoke_access", "recruitment", recruitment_id, f"user_id={user_id}")
    return RedirectResponse(url=f"{settings.proxy_prefix}/recruitments/{recruitment_id}", status_code=302)


def _check_access(recruitment_id: int, user: User, db: Session) -> None:
    if user.role == "admin":
        return
    access = db.query(RecruitmentAccess).filter_by(recruitment_id=recruitment_id, user_id=user.id).first()
    if not access:
        raise HTTPException(403)


def _sorted_candidates(candidates, sort: str, status_filter: str):
    if status_filter:
        candidates = [c for c in candidates if c.status == status_filter]
    if sort == "last_name_asc":
        candidates = sorted(candidates, key=lambda c: (c.last_name or ""))
    elif sort == "last_name_desc":
        candidates = sorted(candidates, key=lambda c: (c.last_name or ""), reverse=True)
    elif sort == "rating_desc":
        candidates = sorted(candidates, key=lambda c: _candidate_rating(c), reverse=True)
    elif sort == "rating_asc":
        candidates = sorted(candidates, key=lambda c: _candidate_rating(c))
    elif sort == "status":
        candidates = sorted(candidates, key=lambda c: c.status)
    else:
        candidates = sorted(candidates, key=lambda c: c.created_at, reverse=True)
    return candidates


def _candidate_rating(c) -> float:
    current_eval = next((e for e in c.evaluations if e.is_current), None)
    return float(current_eval.ai_rating or 0) if current_eval else 0.0


def _extract_jd_requirements(jd_id: int, db_session_factory, bind) -> None:
    from app.services.llm_service import extract_jd_requirements

    db = db_session_factory(bind=bind)
    try:
        jd = db.query(JobDescription).filter_by(id=jd_id).first()
        if not jd or jd.requirements_json:
            return
        requirements = extract_jd_requirements(jd.content)
        jd.requirements_json = requirements.model_dump_json()
        db.commit()
        logger.info("Extracted JD requirements for jd_id=%s", jd_id)
    except Exception as exc:
        logger.error("Failed to extract JD requirements for jd_id=%s: %s", jd_id, exc)
    finally:
        db.close()
