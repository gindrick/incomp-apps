from __future__ import annotations

SALARY_FIELDS = {"current_salary", "expected_salary", "salary_currency", "ai_current_salary", "ai_expected_salary"}


def filter_sensitive(data: dict, role: str) -> dict:
    if role == "admin":
        return data
    return {k: v for k, v in data.items() if k not in SALARY_FIELDS}


def write_audit(db, user_id: int | None, action: str, entity_type: str | None = None, entity_id: int | None = None, detail: str | None = None) -> None:
    from app.db.models import AuditLog

    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
    )
    db.add(entry)
    db.commit()
