from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.db.connection import get_db
from app.db.models import Department, User
from app.templates_config import templates
from config import settings

router = APIRouter(prefix="/departments", tags=["departments"])


def _divisions(db: Session) -> list[Department]:
    return (
        db.query(Department)
        .filter(Department.parent_id.is_(None))
        .order_by(Department.sort_order, Department.name)
        .all()
    )


@router.get("")
def list_departments(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        request,
        "departments/list.html",
        {"divisions": _divisions(db), "user": current_user},
    )


@router.get("/new")
def new_department_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        request,
        "departments/form.html",
        {"dept": None, "divisions": _divisions(db), "user": current_user},
    )


@router.post("/new")
def create_department(
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    parent_id: str = Form(""),
    head_name: str = Form(""),
    headcount: str = Form(""),
    description: str = Form(""),
    sort_order: str = Form("0"),
    ldap_group: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dept = Department(
        name=name.strip(),
        icon=icon.strip() or None,
        parent_id=int(parent_id) if parent_id.strip() else None,
        head_name=head_name.strip() or None,
        headcount=int(headcount) if headcount.strip() else None,
        description=description.strip() or None,
        sort_order=int(sort_order) if sort_order.strip() else 0,
        ldap_group=ldap_group.strip() or None,
    )
    db.add(dept)
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/departments", status_code=302)


@router.get("/{dept_id}/edit")
def edit_department_form(
    dept_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dept = db.query(Department).filter_by(id=dept_id).first()
    if not dept:
        raise HTTPException(404)
    # Exclude self from parent choices to avoid cycles
    divisions = (
        db.query(Department)
        .filter(Department.parent_id.is_(None))
        .filter(Department.id != dept_id)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "departments/form.html",
        {"dept": dept, "divisions": divisions, "user": current_user},
    )


@router.post("/{dept_id}/edit")
def update_department(
    dept_id: int,
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    parent_id: str = Form(""),
    head_name: str = Form(""),
    headcount: str = Form(""),
    description: str = Form(""),
    sort_order: str = Form("0"),
    ldap_group: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dept = db.query(Department).filter_by(id=dept_id).first()
    if not dept:
        raise HTTPException(404)
    dept.name = name.strip()
    dept.icon = icon.strip() or None
    dept.parent_id = int(parent_id) if parent_id.strip() else None
    dept.head_name = head_name.strip() or None
    dept.headcount = int(headcount) if headcount.strip() else None
    dept.description = description.strip() or None
    dept.sort_order = int(sort_order) if sort_order.strip() else 0
    dept.ldap_group = ldap_group.strip() or None
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/departments", status_code=302)


@router.post("/{dept_id}/delete")
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dept = db.query(Department).filter_by(id=dept_id).first()
    if not dept:
        raise HTTPException(404)
    if dept.job_descriptions:
        raise HTTPException(400, "Oddělení má přiřazené pozice. Nejprve je přesuňte nebo odstraňte.")
    if dept.children:
        raise HTTPException(400, "Divize má podřízená oddělení. Nejprve je odstraňte.")
    for u in dept.users:
        u.department_id = None
    db.delete(dept)
    db.commit()
    return RedirectResponse(url=f"{settings.proxy_prefix}/departments", status_code=302)
