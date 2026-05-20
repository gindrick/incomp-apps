from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.connection import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    recruitments_created: Mapped[list[Recruitment]] = relationship(
        back_populates="creator", foreign_keys="Recruitment.created_by"
    )
    access_grants: Mapped[list[RecruitmentAccess]] = relationship(
        back_populates="user", foreign_keys="RecruitmentAccess.user_id"
    )


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    salary_min: Mapped[float | None] = mapped_column(Numeric(10, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(10), default="CZK")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    requirements_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    recruitments: Mapped[list[Recruitment]] = relationship(back_populates="job_description")


class Recruitment(Base):
    __tablename__ = "recruitments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jd_id: Mapped[int] = mapped_column(Integer, ForeignKey("job_descriptions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    job_description: Mapped[JobDescription] = relationship(back_populates="recruitments")
    creator: Mapped[User | None] = relationship(back_populates="recruitments_created", foreign_keys=[created_by])
    access: Mapped[list[RecruitmentAccess]] = relationship(back_populates="recruitment", cascade="all, delete-orphan")
    candidates: Mapped[list[Candidate]] = relationship(back_populates="recruitment", cascade="all, delete-orphan")


class RecruitmentAccess(Base):
    __tablename__ = "recruitment_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recruitment_id: Mapped[int] = mapped_column(Integer, ForeignKey("recruitments.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    recruitment: Mapped[Recruitment] = relationship(back_populates="access")
    user: Mapped[User] = relationship(back_populates="access_grants", foreign_keys=[user_id])


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recruitment_id: Mapped[int] = mapped_column(Integer, ForeignKey("recruitments.id", ondelete="CASCADE"), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    age: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="new")
    current_salary: Mapped[float | None] = mapped_column(Numeric(10, 2))
    expected_salary: Mapped[float | None] = mapped_column(Numeric(10, 2))
    salary_currency: Mapped[str] = mapped_column(String(10), default="CZK")
    needs_reevaluation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    recruitment: Mapped[Recruitment] = relationship(back_populates="candidates")
    documents: Mapped[list[CandidateDocument]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    evaluations: Mapped[list[CandidateEvaluation]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_kb: Mapped[int | None] = mapped_column(Integer)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(50), default="cv")
    uploaded_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    candidate: Mapped[Candidate] = relationship(back_populates="documents")


class CandidateEvaluation(Base):
    __tablename__ = "candidate_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    documents_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jd_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    ai_output_json: Mapped[str] = mapped_column(Text, nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_strengths: Mapped[str | None] = mapped_column(Text)
    ai_weaknesses: Mapped[str | None] = mapped_column(Text)
    ai_jd_match: Mapped[str | None] = mapped_column(Text)
    ai_skill_tags: Mapped[str | None] = mapped_column(Text)
    ai_missing_tags: Mapped[str | None] = mapped_column(Text)
    ai_questions: Mapped[str | None] = mapped_column(Text)
    ai_current_salary: Mapped[float | None] = mapped_column(Numeric(10, 2))
    ai_expected_salary: Mapped[float | None] = mapped_column(Numeric(10, 2))
    ai_rating: Mapped[float | None] = mapped_column(Numeric(4, 2))
    ai_recommendation: Mapped[str | None] = mapped_column(String(20))
    ai_red_flags: Mapped[str | None] = mapped_column(Text)
    ai_current_role: Mapped[str | None] = mapped_column(String(200))
    model_used: Mapped[str | None] = mapped_column(String(100))
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    candidate: Mapped[Candidate] = relationship(back_populates="evaluations")
    overrides: Mapped[list[EvaluationOverride]] = relationship(back_populates="evaluation", cascade="all, delete-orphan")


class EvaluationOverride(Base):
    __tablename__ = "evaluation_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(Integer, ForeignKey("candidate_evaluations.id", ondelete="CASCADE"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_value: Mapped[str | None] = mapped_column(Text)
    user_value: Mapped[str] = mapped_column(Text, nullable=False)
    override_note: Mapped[str | None] = mapped_column(String(500))
    overridden_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    overridden_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    evaluation: Mapped[CandidateEvaluation] = relationship(back_populates="overrides")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
