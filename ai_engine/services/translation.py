"""
Tetum -> English Translation -- TASK D (2026-09-30)

Reuses the EXISTING LLM call abstraction (llm_service.generate_json --
the same function analyze_cv/generate_recruitment_assessment already
use) -- no new API, no new provider. Works with both online_gemma
(production) and Ollama (local dev) automatically, since that choice
already lives inside generate_json().

Called ONLY when language_detection.detect_language() says Tetum is
significant (see recruitment_pipeline.py) -- never for
English/Portuguese/Indonesian documents, per TASK D's explicit "no
LLM call for non-Tetum" requirement.
"""

from .llm_service import generate_json


TRANSLATION_PROMPT_TEMPLATE = """You are translating a Timor-Leste job candidate's CV/document from Tetum to English for a recruitment system.

STRICT RULES:
- Preserve ALL of the following EXACTLY as written, never translate or alter them: person names, organization names, place names, dates, email addresses, phone numbers, technical terms and tool/technology names (e.g. Python, PostgreSQL, Linux, Cisco), certification names, numbers.
- Translate only the natural-language descriptive text (job duties, summaries, education descriptions, etc).
- Do not add, remove, or summarize information. Translate faithfully, keeping the same structure.
- Output ONLY valid JSON in this exact shape: {{"translated_text": "..."}}

Tetum document:
---
{text}
---
"""

JOB_TRANSLATION_PROMPT_TEMPLATE = """You are translating a JOB DESCRIPTION from Tetum to English for a recruitment system.

STRICT RULES:
- Keep EVERY requirement exactly as strong as written. "Minimum 2 years" must stay "minimum 2 years"; a required item must NOT become preferred, and a preferred item must NOT become required. Keep all numbers exactly.
- Preserve EXACTLY, never translate or alter: organization names, place names, dates, technical terms and tool/technology names (e.g. HTML, CSS, JavaScript, PHP, Python, MySQL, PostgreSQL, Git, REST API), certification names, degree field names that are already in English.
- Keep education requirements, years of experience, required skills, preferred skills, language requirements, responsibilities, qualifications, certifications and selection criteria. Do not add, remove, summarize or reinterpret anything.
- Keep the same structure (headings, line breaks, lists).
- Output ONLY valid JSON in this exact shape: {{"translated_text": "..."}}

Tetum job description:
---
{text}
---
"""

TRANSLATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {"translated_text": {"type": "string"}},
    "required": ["translated_text"],
}


def translate_tetum_to_english(text, document_type="cv"):
    """
    Never raises -- on any failure, returns the ORIGINAL text with
    success=False, so the caller can fall back safely (per TASK D:
    "jangan membuat Apply Job crash tanpa informasi", "jangan
    silently pretend translation succeeded").

    Returns:
        {
            "success": bool,
            "translated_text": str,  -- original text if translation failed
            "error": str or None,
        }
    """

    if document_type == "job":
        # TASK E: job descriptions use the job-specific prompt, and the
        # schema-enforced format so Gemma cannot return an empty "{}"
        # (the same early-stop fixed in llm_job_parser). Still ONE call.
        prompt = JOB_TRANSLATION_PROMPT_TEMPLATE.format(text=text)
        result = generate_json(
            prompt,
            default={},
            json_schema=TRANSLATION_JSON_SCHEMA
        )
    else:
        prompt = TRANSLATION_PROMPT_TEMPLATE.format(text=text)

        result = generate_json(
            prompt,
            default={}
        )

    translated_text = result.get("translated_text", "") if isinstance(result, dict) else ""

    if not translated_text or not translated_text.strip():
        return {
            "success": False,
            "translated_text": text,
            "error": "Translation returned empty or invalid result -- using original text.",
        }

    return {
        "success": True,
        "translated_text": translated_text,
        "error": None,
    }