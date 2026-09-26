import json
import logging

from .llm_service import generate_json
# from .local_llm import generate_json
from .llm_candidate_profile import MULTILINGUAL_INSTRUCTION

logger = logging.getLogger(__name__)


DEFAULT_JOB_PROFILE = {
    "job_title": "",
    "education": "",
    "skills": [],
    "languages": [],
    "certifications": [],
    "years_experience": 0,
    "professional_summary": ""
}

# Root cause (diagnosed 2026-09-25, see ai_engine/diagnose_job_parser_bug.py
# output): under format="json" grammar-constrained decoding, gemma3:4b via
# Ollama occasionally (confirmed nondeterministic -- 4/9 calls in a live
# sample, byte-identical prompt each time) stops generating after 2 tokens
# and returns the literal string "{}" (done_reason="stop", eval_count=2)
# instead of the full structured JSON. json.loads("{}") succeeds -- this is
# not an exception, not a timeout, not a prompt/schema/model difference --
# it is upstream LLM sampling variance for this specific call. Retrying the
# SAME unmodified generate_json() call is the direct, minimal mitigation:
# no prompt change, no schema change, no model change, no change to the
# function's return contract (still returns an empty dict, unchanged, if
# every attempt is empty -- process_job()'s existing "if not profile" check
# is untouched and still the final safety net).
MAX_ATTEMPTS = 3


def _normalize_job_profile_result(result, attempt):
    """
    Second confirmed occurrence of the same shape bug fixed in
    llm_candidate_profile.py._normalize_profile_result() (2026-09-26):
    online_gemma can wrap this function's JSON response in a
    single-item array ([{...}]) instead of returning the bare object
    ({...}). The old `if result:` truthiness check below accepted the
    non-empty list as-is, so a job's ai_job_profile could be stored as
    a LIST -- which then made recruitment_pipeline.py's
    `job_profile.get("skills", [])` raise
    "'list' object has no attribute 'get'" for every application to
    that job, a technical failure surfacing to candidates as "the AI
    analysis could not be completed."

    Same narrow rule as the candidate-profile fix: unwrap ONLY a list
    containing exactly one dict. Every other shape is returned
    untouched, so the existing retry/failure path still governs it --
    no guessing, no fabricating a dict from something that isn't
    already a single object.
    """
    if isinstance(result, dict):
        return result

    if (
        isinstance(result, list)
        and len(result) == 1
        and isinstance(result[0], dict)
    ):
        logger.warning(
            "analyze_job_description attempt %s: LLM returned a "
            "single-item JSON array instead of a bare object; "
            "unwrapping it into the expected job profile object "
            "(original_type=list, normalized_type=dict).",
            attempt
        )
        return result[0]

    return result


def analyze_job_description(job_description):

    prompt = f"""
You are an expert HR Recruitment Analyst.

{MULTILINGUAL_INSTRUCTION}

Analyze the following Job Description.

Extract ONLY factual information.

Everything you extract (education, experience, skills, languages,
certifications) describes what THIS SPECIFIC VACANCY is asking for. Do not
present it as, or confuse it with, a national law or civil-service-wide
legal requirement -- a vacancy can ask for more (or less) than the legal
minimum, and this schema only captures what this posting states.

Return ONLY valid JSON.

Schema

{json.dumps(DEFAULT_JOB_PROFILE, indent=4)}

Rules

- Return JSON only.
- No markdown.
- No explanation.
- skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.

Job Description

{job_description}
"""

    last_result = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            result = generate_json(
                prompt=prompt
            )

            result = _normalize_job_profile_result(result, attempt)

            print(f"\n===== JOB PARSER RESPONSE (attempt {attempt}/{MAX_ATTEMPTS}) =====\n")
            print(json.dumps(result, indent=4))
            print("\n===============================\n")

            if isinstance(result, dict) and result:
                return result

            last_result = result

        except Exception as e:

            print(f"Job Parser Error (attempt {attempt}/{MAX_ATTEMPTS}): {e}")

            profile = DEFAULT_JOB_PROFILE.copy()
            profile["error"] = str(e)

            last_result = profile

    return last_result