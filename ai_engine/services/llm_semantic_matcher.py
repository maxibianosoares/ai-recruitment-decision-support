import json
import re

import requests

from ai_engine.services.llm_candidate_profile import (
    MULTILINGUAL_INSTRUCTION
)
from ai_engine.services.model_config import (
    MODEL_NAME,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT_SECONDS
)

# NOTE: switched from the `ollama` Python package's client to raw
# `requests` against Ollama's REST API directly. The `ollama` client
# was failing to connect ("Failed to connect to Ollama") in at least
# one real deployment even though this exact same HTTP endpoint,
# called via `requests` elsewhere in this codebase (llm_service.py),
# worked fine on that same machine at the same time -- so this
# avoids depending on the extra client package entirely.
#
# BASELINE NOTE (Phase 20): this module's semantic_match() function
# is the Phase 1-19 baseline (used alone, as a separate LLM call).
# The live pipeline now uses llm_reasoning.generate_recruitment_
# assessment() instead, which fuses this dimension-scoring step with
# the explainable-decision step into one call. This function is kept
# functional and importable so the baseline behavior can still be
# run and compared against (e.g. for the Phase 20 before/after
# benchmark), not because it is still on the live path.

DEFAULT_RESULT = {
    "overall_score": 0,
    "dimension_scores": {
        "education": 0,
        "experience": 0,
        "technical_skills": 0,
        "soft_skills": 0,
        "certifications": 0,
        "languages": 0
    },
    "strengths": [],
    "weaknesses": [],
    "reasoning": {},
    "recommendation": ""
}


def extract_json(text):

    text = text.strip()

    text = re.sub(
        r"^```json",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```",
        "",
        text
    )

    text = re.sub(
        r"```$",
        "",
        text
    )

    return json.loads(text.strip())


def clamp_score(value):
    """Guarantee a 0-100 number regardless of what the LLM returns."""

    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0

    return round(max(0, min(100, value)), 2)


def normalize_result(raw_result):
    """
    Defense-in-depth: the prompt instructs the LLM to keep every
    score a 0-100 integer, but nothing enforces that on the model's
    output. Clamp overall_score and every dimension score here so a
    malformed/out-of-range value from the LLM can never reach the
    database or blow past 100% in a progress-bar width.
    """

    result = dict(raw_result) if isinstance(raw_result, dict) else {}

    result["overall_score"] = clamp_score(
        result.get("overall_score", 0)
    )

    raw_dimensions = result.get("dimension_scores") or {}

    clamped_dimensions = {}

    for key in DEFAULT_RESULT["dimension_scores"]:

        clamped_dimensions[key] = clamp_score(
            raw_dimensions.get(key, 0)
        )

    result["dimension_scores"] = clamped_dimensions

    result.setdefault("strengths", [])
    result.setdefault("weaknesses", [])
    result.setdefault("reasoning", {})
    result.setdefault("recommendation", "")

    return result


def semantic_match(
    candidate_profile,
    job_profile
):
    """
    Evaluates candidate-to-job fit per dimension using the LLM,
    so it can reason about synonyms/ontology (e.g. "Database
    Management" ~ "PostgreSQL Administration") instead of pure
    vector similarity.

    Both arguments are plain dicts (candidate profile / AI-extracted
    job profile), consistent with the rest of the pipeline.
    """

    prompt = f"""You are an expert recruitment analyst. Score how well the candidate matches the job, dimension by dimension.

{MULTILINGUAL_INSTRUCTION}

Treat synonymous or related terms as matching (e.g. "Database Management" and "PostgreSQL Administration" should be scored as related skills, not unrelated ones).

All numeric scores are integers from 0 to 100. Keep "reasoning" values to one short sentence each. Return ONLY this JSON, no markdown, no extra text:

{{
    "overall_score": 0,
    "dimension_scores": {{
        "education": 0,
        "experience": 0,
        "technical_skills": 0,
        "soft_skills": 0,
        "certifications": 0,
        "languages": 0
    }},
    "strengths": [],
    "weaknesses": [],
    "reasoning": {{
        "education": "",
        "experience": "",
        "technical_skills": "",
        "soft_skills": "",
        "certifications": "",
        "languages": ""
    }},
    "recommendation": ""
}}

Candidate Profile
{json.dumps(candidate_profile, indent=2)}

Job Profile
{json.dumps(job_profile, indent=2)}
"""

    try:

        response = requests.post(
            OLLAMA_GENERATE_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=OLLAMA_TIMEOUT_SECONDS
        )

        response.raise_for_status()

        data = response.json()

        content = data.get("response", "")

        if not content:
            raise ValueError("Empty response from Ollama.")

        return normalize_result(extract_json(content))

    except Exception as e:

        print("Semantic Matching Error:", str(e))

        result = DEFAULT_RESULT.copy()
        result["dimension_scores"] = DEFAULT_RESULT["dimension_scores"].copy()
        result["recommendation"] = f"Semantic matching unavailable: {e}"

        return result