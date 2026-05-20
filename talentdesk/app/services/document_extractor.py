from __future__ import annotations

import json
import logging
from typing import Optional

import litellm

from app.schemas.document_extract import DocumentExtract
from config import settings

logger = logging.getLogger(__name__)

_STRUCTURE_SYSTEM = (
    "You are a document parser for an HR recruitment system. "
    "Extract candidate information from the document text. "
    "Return ONLY valid JSON matching the schema — no text outside JSON. "
    "If a field is absent, use null. "
    "Skill names must be in English. "
    "cleaned_text must contain the full document text, cleaned of formatting noise."
)

_STRUCTURE_SCHEMA = """\
{
  "document_type": "cv|interview_notes|reference|other",
  "candidate_name": "string or null",
  "age": "integer or null",
  "contact_email": "string or null",
  "contact_phone": "string or null",
  "skills": ["skill1", "skill2"],
  "experience_summary": ["3 years at Acme as Developer", ...],
  "education": ["VŠE Praha, Informatika", ...],
  "languages": ["Czech (native)", "English (B2)"],
  "current_salary": "number or null",
  "expected_salary": "number or null",
  "salary_currency": "CZK",
  "cleaned_text": "full normalized document text"
}"""


def structure_document(raw_text: str, doc_type: str) -> Optional[DocumentExtract]:
    if not raw_text or not raw_text.strip():
        logger.warning("LLM call | structure_document | skipped — empty text")
        return None
    logger.info("LLM call | structure_document | model=%s doc_type=%s text_chars=%d", settings.litellm_model, doc_type, len(raw_text))
    try:
        litellm.api_base = settings.litellm_base_url
        litellm.api_key = settings.litellm_api_key
        response = litellm.completion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": _STRUCTURE_SYSTEM},
                {"role": "user", "content": (
                    f"Document type hint: {doc_type}\n\nReturn JSON matching this schema:\n"
                    f"{_STRUCTURE_SCHEMA}\n\nDocument text:\n{raw_text}"
                )},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1500,
        )
        usage = getattr(response, "usage", None)
        logger.info("LLM done | structure_document | tokens_in=%s tokens_out=%s",
                    getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
        data = json.loads(response.choices[0].message.content)
        result = DocumentExtract(**data)
        logger.info("LLM result | structure_document | candidate_name=%r skills=%d doc_type=%s",
                    result.candidate_name, len(result.skills), result.document_type)
        return result
    except Exception as exc:
        logger.error("LLM error | structure_document | %s", exc)
        return None


def extract_text(file_path: str, file_type: str) -> str:
    try:
        if file_type == "pdf":
            return _extract_pdf(file_path)
        if file_type == "docx":
            return _extract_docx(file_path)
        if file_type == "doc":
            return _extract_doc(file_path)
        if file_type in ("txt", "md"):
            return _extract_plaintext(file_path)
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", file_path, exc)
    return ""


def _extract_doc(path: str) -> str:
    import os
    import tempfile

    import win32com.client

    abs_path = os.path.abspath(path)
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    tmp_path = None
    try:
        doc = word.Documents.Open(abs_path)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt")
        os.close(tmp_fd)
        doc.SaveAs(tmp_path, FileFormat=2)  # wdFormatText
        doc.Close(False)
        with open(tmp_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    finally:
        word.Quit()
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _extract_pdf(path: str) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_plaintext(path: str) -> str:
    from charset_normalizer import from_path

    result = from_path(path).best()
    return str(result) if result else ""
