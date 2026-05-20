from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DocumentExtract(BaseModel):
    document_type: str
    candidate_name: Optional[str] = None
    age: Optional[int] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    skills: list[str] = []
    experience_summary: list[str] = []
    education: list[str] = []
    languages: list[str] = []
    current_salary: Optional[float] = None
    expected_salary: Optional[float] = None
    salary_currency: str = "CZK"
    cleaned_text: str
