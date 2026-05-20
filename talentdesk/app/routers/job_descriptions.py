from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.db.connection import get_db
from app.db.models import JobDescription, User
from app.templates_config import templates
from config import settings

router = APIRouter(prefix="/job-descriptions", tags=["job-descriptions"])


@router.get("")
def list_jds(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    jds = db.query(JobDescription).filter_by(is_active=True).order_by(JobDescription.title).all()
    return templates.TemplateResponse(request, "job_descriptions/list.html", {"jds": jds, "user": current_user})


@router.get("/new")
def new_jd_form(request: Request, current_user: User = Depends(require_admin)):
    return templates.TemplateResponse(request, "job_descriptions/form.html", {"jd": None, "user": current_user})


@router.post("/new")
def create_jd(
    request: Request,
    title: str = Form(...),
    department: str = Form(""),
    content: str = Form(...),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    currency: str = Form("CZK"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    jd = JobDescription(
        title=title.strip(),
        department=department.strip() or None,
        content=content.strip(),
        salary_min=float(salary_min) if salary_min.strip() else None,
        salary_max=float(salary_max) if salary_max.strip() else None,
        currency=currency.strip(),
    )
    db.add(jd)
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/job-descriptions", status_code=302)


@router.get("/{jd_id}")
def get_jd(jd_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    jd = db.query(JobDescription).filter_by(id=jd_id).first()
    if not jd:
        from fastapi import HTTPException
        raise HTTPException(404)
    return templates.TemplateResponse(request, "job_descriptions/form.html", {"jd": jd, "user": current_user})


@router.post("/{jd_id}")
def update_jd(
    jd_id: int,
    request: Request,
    title: str = Form(...),
    department: str = Form(""),
    content: str = Form(...),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    currency: str = Form("CZK"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    jd = db.query(JobDescription).filter_by(id=jd_id).first()
    if not jd:
        from fastapi import HTTPException
        raise HTTPException(404)
    jd.title = title.strip()
    jd.department = department.strip() or None
    jd.content = content.strip()
    jd.salary_min = float(salary_min) if salary_min.strip() else None
    jd.salary_max = float(salary_max) if salary_max.strip() else None
    jd.currency = currency.strip()
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/job-descriptions", status_code=302)
