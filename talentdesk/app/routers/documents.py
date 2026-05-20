from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.auth.dependencies import get_current_user
from app.db.connection import get_db
from app.db.models import Candidate, CandidateDocument, CandidateEvaluation, JobDescription, Recruitment, RecruitmentAccess, User
from app.services.access_control import write_audit
from app.services.document_extractor import extract_text
from app.services.hash_service import compute_documents_hash, sha256_file
from config import settings

router = APIRouter(tags=["documents"])

# candidate_id → extraction+evaluation status
_EXTRACT_STATUS: dict[int, Literal["pending", "done"]] = {}

ALLOWED_TYPES = {"pdf", "doc", "docx", "txt", "md"}
MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


@router.post("/candidates/{candidate_id}/documents")
async def upload_document(
    candidate_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form("cv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb} MB limit")

    file_hash = _hash_bytes(content)

    existing = (
        db.query(CandidateDocument)
        .filter_by(candidate_id=candidate_id, sha256_hash=file_hash, is_deleted=False)
        .first()
    )
    if existing:
        raise HTTPException(409, "This file has already been uploaded for this candidate")

    upload_dir = Path(settings.upload_dir) / str(candidate.recruitment_id) / str(candidate_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_name = f"{uuid.uuid4().hex}_{file.filename}"
    save_path = upload_dir / save_name
    save_path.write_bytes(content)

    doc = CandidateDocument(
        candidate_id=candidate_id,
        original_name=file.filename,
        file_path=str(save_path.relative_to(Path(settings.upload_dir).parent)),
        file_type=ext,
        file_size_kb=len(content) // 1024,
        sha256_hash=file_hash,
        doc_type=doc_type,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    write_audit(db, current_user.id, "upload_doc", "document", doc.id, file.filename)

    from app.routers.evaluations import _EVAL_STATUS
    _EVAL_STATUS[candidate_id] = "pending"
    background_tasks.add_task(
        _extract_and_evaluate,
        doc_id=doc.id,
        file_path=str(save_path),
        file_type=ext,
        candidate_id=candidate_id,
        db_session_factory=db.__class__,
        bind=db.get_bind(),
    )

    pfx = settings.proxy_prefix
    return HTMLResponse(
        f'<div hx-get="{pfx}/candidates/{candidate_id}/evaluation/status" hx-trigger="every 2s" hx-swap="outerHTML"'
        f' class="flex items-center gap-2 text-sm text-yellow-400 py-1">'
        f'<span class="animate-spin inline-block">&#9851;</span>'
        f'<span>AI evaluation in progress...</span>'
        f'</div>',
        status_code=200,
    )


@router.get("/candidates/{candidate_id}/documents")
def list_documents(candidate_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidate = _get_candidate_or_404(candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)
    docs = [d for d in candidate.documents if not d.is_deleted]
    return {"documents": [{"id": d.id, "name": d.original_name, "type": d.file_type, "doc_type": d.doc_type} for d in docs]}


@router.get("/documents/{doc_id}/view")
def view_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(CandidateDocument).filter_by(id=doc_id, is_deleted=False).first()
    if not doc:
        raise HTTPException(404)
    candidate = _get_candidate_or_404(doc.candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)

    full_path = Path(settings.upload_dir).parent / doc.file_path
    if not full_path.exists():
        raise HTTPException(404, "File not found on disk")

    media_types = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain", "md": "text/markdown"}
    return FileResponse(str(full_path), media_type=media_types.get(doc.file_type, "application/octet-stream"), filename=doc.original_name)


@router.post("/documents/{doc_id}/delete")
def delete_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(CandidateDocument).filter_by(id=doc_id, is_deleted=False).first()
    if not doc:
        raise HTTPException(404)
    candidate = _get_candidate_or_404(doc.candidate_id, db)
    _check_access(candidate.recruitment_id, current_user, db)

    doc.is_deleted = True
    db.commit()
    _recompute_hash(doc.candidate_id, db)
    write_audit(db, current_user.id, "delete_doc", "document", doc_id)
    return HTMLResponse("", status_code=200)


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


def _hash_bytes(content: bytes) -> str:
    import hashlib
    return hashlib.sha256(content).hexdigest()


def _recompute_hash(candidate_id: int, db: Session) -> None:
    active_docs = db.query(CandidateDocument).filter_by(candidate_id=candidate_id, is_deleted=False).all()
    candidate = db.query(Candidate).filter_by(id=candidate_id).first()
    if not candidate:
        return
    if not active_docs:
        candidate.needs_reevaluation = False
        db.commit()
        return
    new_hash = compute_documents_hash([d.sha256_hash for d in active_docs])
    current_eval = db.query(CandidateEvaluation).filter_by(candidate_id=candidate_id, is_current=True).first()
    if current_eval is None or current_eval.documents_hash != new_hash:
        candidate.needs_reevaluation = True
    db.commit()


def _extract_and_evaluate(doc_id: int, file_path: str, file_type: str, candidate_id: int, db_session_factory, bind) -> None:
    """Extract text from a single doc, then run a combined evaluation for the candidate."""
    from app.routers.evaluations import _EVAL_STATUS

    logger.info("extract+eval start | doc_id=%s candidate_id=%s", doc_id, candidate_id)
    raw_text = extract_text(file_path, file_type)
    logger.info("extract+eval text | doc_id=%s chars=%d", doc_id, len(raw_text))

    session = db_session_factory(bind=bind)
    try:
        doc = session.query(CandidateDocument).filter_by(id=doc_id).first()
        if doc:
            doc.extracted_text = raw_text
            doc.extracted_json = None
            session.commit()
    finally:
        session.close()

    try:
        _run_and_save_evaluation(candidate_id, db_session_factory, bind)
        _EVAL_STATUS[candidate_id] = "done"
        logger.info("extract+eval done | candidate_id=%s", candidate_id)
    except Exception as exc:
        logger.error("extract+eval failed | candidate_id=%s: %s", candidate_id, exc)
        _EVAL_STATUS[candidate_id] = "error"


def _run_and_save_evaluation(candidate_id: int, db_session_factory, bind) -> None:
    """Run one LLM evaluation call for all active docs and persist the result."""
    from app.services.llm_service import evaluate_candidate, _format_document
    from app.schemas.llm_output import JDRequirements

    session = db_session_factory(bind=bind)
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return

        jd = candidate.recruitment.job_description
        jd_text = jd.content

        active_docs = [d for d in candidate.documents if not d.is_deleted and d.extracted_text]
        if not active_docs:
            logger.warning("run_and_save_evaluation | candidate=%s no active docs", candidate_id)
            return

        docs_hash = compute_documents_hash([d.sha256_hash for d in active_docs])
        docs_text = "\n\n---\n\n".join(
            _format_document(d.original_name, d.file_type, d.extracted_json, d.extracted_text or "")
            for d in active_docs
        )

        jd_requirements = None
        if jd.requirements_json:
            try:
                jd_requirements = JDRequirements.model_validate_json(jd.requirements_json)
            except Exception:
                pass

        result = evaluate_candidate(jd_text, docs_text, jd_requirements=jd_requirements)

        session.query(CandidateEvaluation).filter_by(candidate_id=candidate_id, is_current=True).update({"is_current": False})
        session.commit()

        eval_row = CandidateEvaluation(
            candidate_id=candidate_id,
            documents_hash=docs_hash,
            jd_snapshot=jd_text,
            ai_output_json=result.model_dump_json(),
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
        session.add(eval_row)
        session.commit()

        if result.first_name and not candidate.first_name:
            candidate.first_name = result.first_name
        if result.last_name and not candidate.last_name:
            candidate.last_name = result.last_name
        if result.age and not candidate.age:
            candidate.age = result.age
        if result.contact_email and not candidate.email:
            candidate.email = result.contact_email
        if result.contact_phone and not candidate.phone:
            candidate.phone = result.contact_phone
        candidate.needs_reevaluation = False
        session.commit()

        logger.info("run_and_save_evaluation | candidate=%s rating=%s recommendation=%s", candidate_id, result.overall_rating, result.recommendation)
    finally:
        session.close()


@router.post("/candidates/recruitments/{recruitment_id}/upload-create")
async def upload_create_candidate(
    recruitment_id: int,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.query(Recruitment).filter_by(id=recruitment_id).first()
    if not rec:
        raise HTTPException(404)
    _check_access(recruitment_id, current_user, db)

    if not files:
        raise HTTPException(400, "No files provided")

    candidate = Candidate(recruitment_id=recruitment_id)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    upload_dir = Path(settings.upload_dir) / str(recruitment_id) / str(candidate.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    docs_info: list[tuple[int, str, str]] = []
    for file in files:
        ext = Path(file.filename).suffix.lstrip(".").lower()
        if ext not in ALLOWED_TYPES:
            logger.warning("upload-create | skipping unsupported file type .%s (%s)", ext, file.filename)
            continue
        content = await file.read()
        if len(content) > MAX_BYTES:
            logger.warning("upload-create | skipping oversized file %s (%d bytes)", file.filename, len(content))
            continue
        file_hash = _hash_bytes(content)
        save_name = f"{uuid.uuid4().hex}_{file.filename}"
        save_path = upload_dir / save_name
        save_path.write_bytes(content)
        doc = CandidateDocument(
            candidate_id=candidate.id,
            original_name=file.filename,
            file_path=str(save_path.relative_to(Path(settings.upload_dir).parent)),
            file_type=ext,
            file_size_kb=len(content) // 1024,
            sha256_hash=file_hash,
            doc_type="cv",
            uploaded_by=current_user.id,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        docs_info.append((doc.id, str(save_path), ext))
        logger.info("upload-create | saved doc_id=%s file=%s candidate_id=%s", doc.id, file.filename, candidate.id)

    if not docs_info:
        db.delete(candidate)
        db.commit()
        raise HTTPException(400, "No valid files could be processed")

    _EXTRACT_STATUS[candidate.id] = "pending"
    background_tasks.add_task(
        _extract_all_and_evaluate,
        docs_info=docs_info,
        candidate_id=candidate.id,
        db_session_factory=db.__class__,
        bind=db.get_bind(),
    )
    write_audit(db, current_user.id, "create_candidate_from_doc", "candidate", candidate.id)
    logger.info("upload-create | candidate_id=%s docs=%d extraction+eval queued", candidate.id, len(docs_info))

    pfx = settings.proxy_prefix
    return HTMLResponse(
        f'<div id="candidate-{candidate.id}"'
        f' hx-get="{pfx}/candidates/{candidate.id}/extraction/status"'
        f' hx-trigger="every 2s" hx-swap="outerHTML"'
        f' class="bg-gray-900 border border-sky-900 rounded-xl p-4 flex flex-col gap-3">'
        f'<div class="flex items-center gap-2">'
        f'<span class="text-xs text-sky-400 animate-pulse">⟳ Evaluating candidate... ({len(docs_info)} file(s))</span>'
        f'</div>'
        f'<div class="h-2 bg-gray-800 rounded animate-pulse w-3/4 mt-1"></div>'
        f'<div class="h-2 bg-gray-800 rounded animate-pulse w-1/2 mt-1.5"></div>'
        f'<div class="h-2 bg-gray-800 rounded animate-pulse w-2/3 mt-1.5"></div>'
        f'</div>',
        status_code=200,
    )


def _extract_all_and_evaluate(
    docs_info: list[tuple[int, str, str]],
    candidate_id: int,
    db_session_factory,
    bind,
) -> None:
    logger.info("extract-all start | candidate_id=%s docs=%d", candidate_id, len(docs_info))

    # Extract text for all docs first
    for doc_id, file_path, file_type in docs_info:
        try:
            raw_text = extract_text(file_path, file_type)
            session = db_session_factory(bind=bind)
            try:
                doc = session.query(CandidateDocument).filter_by(id=doc_id).first()
                if doc:
                    doc.extracted_text = raw_text
                    doc.extracted_json = None
                    session.commit()
                    logger.info("extract-all text | doc_id=%s chars=%d", doc_id, len(raw_text))
            finally:
                session.close()
        except Exception as exc:
            logger.error("extract-all | doc_id=%s extraction failed: %s", doc_id, exc)

    # Run one combined evaluation after all docs are ready
    try:
        _run_and_save_evaluation(candidate_id, db_session_factory, bind)
    except Exception as exc:
        logger.error("extract-all eval | candidate_id=%s: %s", candidate_id, exc)

    _EXTRACT_STATUS[candidate_id] = "done"
    logger.info("extract-all done | candidate_id=%s", candidate_id)
