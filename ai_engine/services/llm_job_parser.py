import json

from .llm_service import generate_json
# from .local_llm import generate_json
from .llm_candidate_profile import MULTILINGUAL_INSTRUCTION


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

            print(f"\n===== JOB PARSER RESPONSE (attempt {attempt}/{MAX_ATTEMPTS}) =====\n")
            print(json.dumps(result, indent=4))
            print("\n===============================\n")

            if result:
                return result

            last_result = result

        except Exception as e:

            print(f"Job Parser Error (attempt {attempt}/{MAX_ATTEMPTS}): {e}")

            profile = DEFAULT_JOB_PROFILE.copy()
            profile["error"] = str(e)

            last_result = profile

    return last_result