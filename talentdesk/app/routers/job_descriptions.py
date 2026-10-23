from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.db.connection import get_db
from app.db.models import Department, JobDescription, User
from app.templates_config import templates
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/job-descriptions", tags=["job-descriptions"])


def _all_departments(db: Session) -> list[Department]:
    return db.query(Department).order_by(Department.sort_order, Department.name).all()


def _sort_jds(jds: list, sort: str) -> list:
    if sort == "title_desc":
        return sorted(jds, key=lambda j: j.title.lower(), reverse=True)
    elif sort == "salary_asc":
        return sorted(jds, key=lambda j: float(j.salary_min or 0))
    elif sort == "salary_desc":
        return sorted(jds, key=lambda j: float(j.salary_max or 0), reverse=True)
    return sorted(jds, key=lambda j: j.title.lower())


@router.get("")
def list_jds(
    request: Request,
    q: str = "",
    sort: str = "title_asc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = q.strip()
    logger.info("list_jds: q=%r sort=%r user=%s role=%s", q, sort, current_user.username, current_user.role)

    if current_user.role == "admin":
        if q:
            search_results = _sort_jds(
                db.query(JobDescription)
                .filter(JobDescription.is_active == True, JobDescription.title.ilike(f"%{q}%"))  # noqa: E712
                .all(),
                sort,
            )
            return templates.TemplateResponse(
                request,
                "job_descriptions/list.html",
                {
                    "q": q,
                    "sort": sort,
                    "search_results": search_results,
                    "divisions": [],
                    "jds_by_dept": {},
                    "unassigned": [],
                    "user": current_user,
                },
            )

        divisions = (
            db.query(Department)
            .filter(Department.parent_id.is_(None))
            .order_by(Department.sort_order, Department.name)
            .all()
        )
        active_jds = db.query(JobDescription).filter_by(is_active=True).all()
        jds_by_dept: dict[int, list[JobDescription]] = {}
        unassigned: list[JobDescription] = []
        for jd in active_jds:
            if jd.department_id:
                jds_by_dept.setdefault(jd.department_id, []).append(jd)
            else:
                unassigned.append(jd)
        for dept_id in jds_by_dept:
            jds_by_dept[dept_id] = _sort_jds(jds_by_dept[dept_id], sort)
        unassigned = _sort_jds(unassigned, sort)
        return templates.TemplateResponse(
            request,
            "job_descriptions/list.html",
            {
                "q": q,
                "sort": sort,
                "search_results": None,
                "divisions": divisions,
                "jds_by_dept": jds_by_dept,
                "unassigned": unassigned,
                "user": current_user,
            },
        )

    # Non-admin: show only their department's JDs
    user_dept: Department | None = None
    jds: list[JobDescription] = []
    if current_user.department_id:
        user_dept = db.query(Department).filter_by(id=current_user.department_id).first()
        jds_query = db.query(JobDescription).filter_by(is_active=True, department_id=current_user.department_id)
        if q:
            jds_query = jds_query.filter(JobDescription.title.ilike(f"%{q}%"))
        jds = _sort_jds(jds_query.all(), sort)
    return templates.TemplateResponse(
        request,
        "job_descriptions/list.html",
        {
            "q": q,
            "sort": sort,
            "search_results": None,
            "divisions": [],
            "jds_by_dept": {},
            "unassigned": [],
            "user_dept": user_dept,
            "jds": jds,
            "user": current_user,
        },
    )


@router.get("/new")
def new_jd_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        request,
        "job_descriptions/form.html",
        {"jd": None, "departments": _all_departments(db), "user": current_user},
    )


@router.post("/new")
def create_jd(
    request: Request,
    title: str = Form(...),
    department_id: str = Form(""),
    content: str = Form(...),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    currency: str = Form("CZK"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dept_id = int(department_id) if department_id.strip() else None
    jd = JobDescription(
        title=title.strip(),
        department_id=dept_id,
        content=content.strip(),
        salary_min=float(salary_min) if salary_min.strip() else None,
        salary_max=float(salary_max) if salary_max.strip() else None,
        currency=currency.strip(),
    )
    db.add(jd)
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/job-descriptions", status_code=302)


@router.get("/{jd_id}")
def get_jd(
    jd_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    jd = db.query(JobDescription).filter_by(id=jd_id).first()
    if not jd:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "job_descriptions/form.html",
        {"jd": jd, "departments": _all_departments(db), "user": current_user},
    )


@router.post("/{jd_id}")
def update_jd(
    jd_id: int,
    request: Request,
    title: str = Form(...),
    department_id: str = Form(""),
    content: str = Form(...),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    currency: str = Form("CZK"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    jd = db.query(JobDescription).filter_by(id=jd_id).first()
    if not jd:
        raise HTTPException(404)
    jd.title = title.strip()
    jd.department_id = int(department_id) if department_id.strip() else None
    jd.content = content.strip()
    jd.salary_min = float(salary_min) if salary_min.strip() else None
    jd.salary_max = float(salary_max) if salary_max.strip() else None
    jd.currency = currency.strip()
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/job-descriptions", status_code=302)
