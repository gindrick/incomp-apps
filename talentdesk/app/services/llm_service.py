from __future__ import annotations

import json
import logging
from typing import Optional

import litellm

from app.schemas.document_extract import DocumentExtract
from app.schemas.llm_output import EvaluationOutput, JDRequirements
from config import settings

logger = logging.getLogger(__name__)


def _build_system_prompt(has_structured_requirements: bool = False) -> str:
    schema = EvaluationOutput.model_json_schema()

    if has_structured_requirements:
        skill_ratings_rule = """skill_ratings — CRITICAL RULE:
  The job requirements have been pre-extracted into must-have and nice-to-have lists.
  For EACH requirement in both lists, produce exactly one entry in skill_ratings:
    - "skill": the requirement text exactly as provided in the list
    - "rating": 0–10 match score based solely on evidence found in the candidate documents
    - "evidence": one sentence citing the specific evidence (or stating what is missing)
  Include ALL requirements — even those the candidate does not meet (use rating 0–3 and explain the gap).
  Do NOT invent criteria not present in the provided lists."""
    else:
        skill_ratings_rule = """skill_ratings — CRITICAL RULE:
  Step 1: Extract EVERY explicit requirement from the job description. Cover all categories present:
    technical skills (languages, frameworks, tools, platforms), years of experience, education/degree,
    domain knowledge, certifications, languages (human languages), soft skills, other stated requirements.
  Step 2: For EACH extracted requirement, produce exactly one entry in skill_ratings:
    - "skill": concise label of the requirement as stated in the JD (e.g. "Python 5+ years", "SQL", "Angličtina B2", "Vedení týmu")
    - "rating": 0–10 match score based solely on evidence found in the candidate documents
    - "evidence": one sentence citing the specific evidence (or stating what is missing)
  Step 3: Include ALL requirements — even those the candidate does not meet (use rating 0–3 and explain the gap).
  Do NOT invent criteria that are not in the JD. Do NOT include generic skills unless the JD explicitly requires them."""

    return f"""You are an expert HR assistant. You evaluate candidates based on provided documents and a job description.
Respond EXCLUSIVELY in JSON format matching this exact schema. No text outside the JSON. All required fields must be present.

JSON Schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Rules:
- Use correct diacritics for first and last names
- Ratings are 0–10
- contact_email: candidate's email address extracted from the documents — null if not found
- contact_phone: candidate's phone number extracted from the documents — null if not found
- current_role: candidate's current job title and employer, e.g. "Senior Developer @ Acme s.r.o." — null if not found
- red_flags: serious blockers only (max 3); empty [] if none; do NOT duplicate weaknesses here
- recommendation: exactly one of "DOPORUCIT" (strong JD fit, overall_rating >= 7), "ZVAZIT" (partial fit, 4–6.9), "NEDOPORUCIT" (poor fit, < 4)

{skill_ratings_rule}
"""


def _format_document(name: str, file_type: str, extracted_json: Optional[str], extracted_text: str) -> str:
    header = f"[Document: {name} | Type: {file_type.upper()}]"
    if not extracted_json:
        return f"{header}\n{extracted_text}"
    try:
        ex = DocumentExtract(**json.loads(extracted_json))
        structured_header = f"{header}\n"
        if ex.candidate_name:
            structured_header += f"Name: {ex.candidate_name}"
            if ex.age:
                structured_header += f" | Age: {ex.age}"
            structured_header += "\n"
        if ex.skills:
            structured_header += f"Skills: {', '.join(ex.skills)}\n"
        if ex.experience_summary:
            structured_header += f"Experience: {' | '.join(ex.experience_summary)}\n"
        if ex.education:
            structured_header += f"Education: {' | '.join(ex.education)}\n"
        if ex.languages:
            structured_header += f"Languages: {', '.join(ex.languages)}\n"
        if ex.current_salary or ex.expected_salary:
            sal_parts = []
            if ex.current_salary:
                sal_parts.append(f"current {int(ex.current_salary)} {ex.salary_currency}")
            if ex.expected_salary:
                sal_parts.append(f"expected {int(ex.expected_salary)} {ex.salary_currency}")
            structured_header += f"Salary: {', '.join(sal_parts)}\n"
        return f"{structured_header}---\n{ex.cleaned_text}"
    except Exception:
        return f"{header}\n{extracted_text}"


def extract_jd_requirements(jd_text: str) -> JDRequirements:
    schema = JDRequirements.model_json_schema()
    system_prompt = f"""Extract must-have and nice-to-have requirements from the job description.
Return JSON matching this schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Rules:
- must_have: requirements that are explicitly required/mandatory or clearly essential for the role
- nice_to_have: requirements marked as optional, preferred, or "výhodou"
- Each item is a concise string (e.g. "Python 5+ let", "SQL", "Angličtina B2", "Vedení týmu 3+ roky")
- Cover ALL categories: technical skills, experience, education, certifications, languages, soft skills
- Do NOT invent requirements not present in the JD"""

    litellm.api_base = settings.litellm_base_url
    litellm.api_key = settings.litellm_api_key

    logger.info("LLM call | extract_jd_requirements | model=%s jd_chars=%d", settings.litellm_model, len(jd_text))
    try:
        response = litellm.completion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Job Description:\n{jd_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2000,
        )
        usage = getattr(response, "usage", None)
        logger.info("LLM done | extract_jd_requirements | tokens_in=%s tokens_out=%s",
                    getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
        raw = response.choices[0].message.content
        data = json.loads(raw)
        result = JDRequirements(**data)
        logger.info("LLM result | extract_jd_requirements | must_have=%d nice_to_have=%d", len(result.must_have), len(result.nice_to_have))
        return result
    except Exception as exc:
        logger.error("LLM error | extract_jd_requirements | %s", exc)
        raise


def evaluate_candidate(jd_text: str, documents_text: str, jd_requirements: Optional[JDRequirements] = None) -> EvaluationOutput:
    if jd_requirements:
        must_have_block = "\n".join(f"- {r}" for r in jd_requirements.must_have)
        nice_to_have_block = "\n".join(f"- {r}" for r in jd_requirements.nice_to_have)
        jd_block = f"## Job Requirements\n**Must-Have:**\n{must_have_block}\n\n**Nice-to-Have:**\n{nice_to_have_block}"
    else:
        jd_block = f"## Job Description\n{jd_text}"

    user_prompt = f"{jd_block}\n\n## Candidate Documents\n{documents_text}\n\nReturn the evaluation as JSON exactly matching the schema. All required fields must be present."

    litellm.api_base = settings.litellm_base_url
    litellm.api_key = settings.litellm_api_key

    logger.info("LLM call | evaluate_candidate | model=%s docs_chars=%d use_requirements=%s",
                settings.litellm_model, len(documents_text), jd_requirements is not None)
    try:
        response = litellm.completion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": _build_system_prompt(has_structured_requirements=jd_requirements is not None)},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=settings.litellm_max_tokens,
        )
        usage = getattr(response, "usage", None)
        logger.info("LLM done | evaluate_candidate | tokens_in=%s tokens_out=%s",
                    getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
        raw = response.choices[0].message.content
        data = json.loads(raw)
        result = EvaluationOutput(**data)
        logger.info("LLM result | evaluate_candidate | rating=%s recommendation=%s", result.overall_rating, result.recommendation)
        return result
    except Exception as exc:
        logger.error("LLM error | evaluate_candidate | %s", exc)
        raise
