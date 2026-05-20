from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class JDRequirements(BaseModel):
    must_have: List[str]
    nice_to_have: List[str]


class SkillRating(BaseModel):
    skill: str
    rating: float = Field(ge=0, le=10)
    evidence: str


class EvaluationOutput(BaseModel):
    last_name: str
    first_name: str
    age: Optional[int] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    current_role: Optional[str] = None
    summary: str
    strengths: List[str]
    weaknesses: List[str]
    red_flags: List[str] = []
    jd_match_analysis: str
    jd_match_score: float = Field(ge=0, le=10)
    skill_tags: List[str]
    missing_skill_tags: List[str]
    skill_ratings: List[SkillRating]
    recommended_questions: List[str]
    current_salary: Optional[float] = None
    expected_salary: Optional[float] = None
    salary_currency: str = "CZK"
    overall_rating: float = Field(ge=0, le=10)
    evaluation_rationale: str
    recommendation: Literal["DOPORUCIT", "ZVAZIT", "NEDOPORUCIT"] = "ZVAZIT"
