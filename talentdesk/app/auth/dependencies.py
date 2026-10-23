from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.connection import get_db
from app.db.models import Candidate, Department, RecruitmentAccess, User
from config import settings


def _sync_user(
    db: Session,
    username: str,
    email: str,
    default_role: str = "user",
    groups: list[str] | None = None,
) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(username=username, email=email, role=default_role, display_name=username)
        db.add(user)
    else:
        user.email = email
    user.last_login = datetime.utcnow()

    if groups is not None and user.role != "admin":
        lower_groups = [g.lower() for g in groups]
        depts = db.query(Department).filter(Department.ldap_group.isnot(None)).all()
        matched = next(
            (d for d in depts if d.ldap_group and d.ldap_group.lower() in lower_groups),
            None,
        )
        user.department_id = matched.id if matched else None

    db.commit()
    db.refresh(user)
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if settings.dev_auth_bypass and settings.env != "prod":
        return _sync_user(
            db,
            username=settings.dev_auth_user_email.split("@")[0],
            email=settings.dev_auth_user_email,
            default_role=settings.dev_auth_role,
        )

    session_user = request.session.get("user")
    if not session_user:
        raise RedirectException(url=f"{settings.proxy_prefix}/login")

    return _sync_user(
        db,
        username=session_user["name"],
        email=session_user["email"],
    )


class RedirectException(Exception):
    def __init__(self, url: str) -> None:
        self.url = url


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def require_recruitment_access(
    recruitment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if current_user.role == "admin":
        return current_user
    access = (
        db.query(RecruitmentAccess)
        .filter_by(recruitment_id=recruitment_id, user_id=current_user.id)
        .first()
    )
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return current_user
