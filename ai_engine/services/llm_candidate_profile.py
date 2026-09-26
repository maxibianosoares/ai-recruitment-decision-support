import json
import logging

from .llm_service import generate_json

logger = logging.getLogger(__name__)

MULTILINGUAL_INSTRUCTION = """
The CV and Job Description may be written in English, Portuguese, Tetum,
Indonesian, or a mixture of these languages.

You must understand the meaning regardless of the language used.

Perform semantic analysis across languages.

Treat equivalent concepts as identical.

Examples

Bachelor Degree
Licenciatura
Sarjana
Graus Universitários

represent the same education level.

Likewise

Teamwork
Trabalho em equipa
Kerja sama
Servisu hamutuk

represent the same soft skill.

Recruitment/civil-service terms also vary by language but mean the same
role or concept, for example: civil service / função pública / servisu
públiku / aparatur sipil -- or: vacancy / vaga / pozisaun / lowongan -- or:
professional experience / experiência profissional / esperiénsia
profisionál / pengalaman kerja. Apply the same principle to any other
recruitment term you encounter, even if not listed here.

Extract information based on meaning rather than exact wording. Do not
translate the source text yourself and do not lose legal/recruitment
meaning by paraphrasing loosely -- read in the original language, extract
the meaning, and write the structured output in the field's expected
format.

Extract only information that is actually stated or clearly implied in the
source document. Do not infer, guess, or fill in missing qualifications,
years of experience, certifications, employment history, or skills that
are not supported by the text. If information for a field is not present,
leave it empty rather than inventing a plausible-sounding value.
"""


DEFAULT_PROFILE = {
    "education": "",
    "skills": [],
    "languages": [],
    "certifications": [],
    "years_experience": 0,
    "professional_summary": ""
}

# Same root cause and fix as ai_engine/services/llm_job_parser.py's
# analyze_job_description() (diagnosed 2026-09-25, see
# ai_engine/diagnose_job_parser_bug.py output): under format="json"
# grammar-constrained decoding, gemma3:4b via Ollama occasionally stops
# generating after 2 tokens and returns the literal string "{}" instead
# of the full structured JSON. Confirmed live for THIS function too
# (candidate "Maria da Costa" application, 2026-09-25: console showed
# "===== PROFILE RESPONSE =====\n{}", which produced an empty
# candidate profile and cascaded into a false "Not Recommended 0%"
# result -- not because the candidate lacked qualifications, but
# because the CV was never actually parsed). Retrying the SAME
# unmodified generate_json() call up to MAX_ATTEMPTS times is the same
# minimal mitigation applied to the job parser: no prompt change, no
# schema change, no model change, no change to analyze_cv()'s return
# contract (still returns an empty dict, unchanged, if every attempt
# is empty).
MAX_ATTEMPTS = 3


def _normalize_profile_result(result, attempt):
    """
    Root-cause fix (2026-09-26, confirmed via Railway production log,
    candidate "Maria da Costa", provider=online_gemma
    model=gemma-4-26b-a4b-it): that model occasionally wraps the
    profile object in a single-item JSON array ([{...}]) instead of
    returning the bare object ({...}). json.loads() succeeds either
    way (both are syntactically valid JSON), so the old `if result:`
    truthiness check accepted the list as-is on attempt 1 -- then
    recruitment_pipeline.py's DEFAULT_PROFILE guard (`key in profile`)
    silently failed against a list instead of a dict, misclassifying
    a fully and correctly parsed profile as a technical CV parsing
    failure. The candidate's data was never actually missing -- only
    its shape was wrong.

    Unwraps ONLY the one unambiguous shape: a list containing exactly
    one dict. Every other shape -- empty list, multiple objects, a
    list of non-dict items, a bare string, etc. -- is returned
    untouched, so the existing retry/failure path still governs it.
    This never guesses which of several objects to keep, and never
    fabricates a dict from something that isn't already a single
    object.
    """
    if isinstance(result, dict):
        return result

    if (
        isinstance(result, list)
        and len(result) == 1
        and isinstance(result[0], dict)
    ):
        logger.warning(
            "analyze_cv attempt %s: LLM returned a single-item JSON "
            "array instead of a bare object; unwrapping it into the "
            "expected profile object (original_type=list, "
            "normalized_type=dict).",
            attempt
        )
        return result[0]

    return result


def analyze_cv(cv_text, num_predict=None):
    """
    num_predict (Phase 23, controlled experiment ONLY): forwarded
    unchanged to generate_json(). Default None -- exact current
    behavior, no change to the request sent to Ollama. Only set by
    phase23_num_predict_benchmark.py to compare configurations; no
    production caller passes this today.
    """

    prompt = f"""
You are an expert AI Recruitment Analyst.

{MULTILINGUAL_INSTRUCTION}

Analyze the following CV.

Extract the candidate profile.

Return ONLY valid JSON.

Schema

{json.dumps(DEFAULT_PROFILE, indent=4)}

Rules

- Return JSON only.
- No markdown.
- No explanation.
- skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.

CV

{cv_text}
"""

    last_result = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            result = generate_json(
                prompt=prompt,
                num_predict=num_predict
            )

            result = _normalize_profile_result(result, attempt)

            print(f"\n===== PROFILE RESPONSE (attempt {attempt}/{MAX_ATTEMPTS}) =====\n")
            print(json.dumps(result, indent=4))
            print("\n============================\n")

            if isinstance(result, dict) and result:
                return result

            last_result = result

        except Exception as e:

            print(f"Candidate Profile Error (attempt {attempt}/{MAX_ATTEMPTS}): {e}")

            profile = DEFAULT_PROFILE.copy()
            profile["error"] = str(e)

            last_result = profile

    return last_result


def analyze_cv_to_dict(cv_text):
    return analyze_cv(cv_text)