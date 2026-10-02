import json
import logging
import re

from .llm_service import generate_json
# from .local_llm import generate_json
from .llm_candidate_profile import MULTILINGUAL_INSTRUCTION

logger = logging.getLogger(__name__)


DEFAULT_JOB_PROFILE = {
    "job_title": "",
    "education": "",
    "skills": [],
    "preferred_skills": [],
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

# JSON Schema sent with EVERY job-profiling attempt (see analyze_job_description).
# Same keys/types as DEFAULT_JOB_PROFILE -- no change to the stored shape.
JOB_PROFILE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "job_title": {"type": "string"},
        "education": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "preferred_skills": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "certifications": {"type": "array", "items": {"type": "string"}},
        "years_experience": {"type": "integer"},
        "professional_summary": {"type": "string"}
    },
    "required": [
        "job_title", "education", "skills", "preferred_skills", "languages",
        "certifications", "years_experience", "professional_summary"
    ]
}


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



# ---------------------------------------------------------------------
# Safety net for REQUIRED vs ADVANTAGE (Task E, A+B follow-up).
# Live result on job 30: gemma3:4b ignored the prompt rules for
# "languages" and "certifications" (it listed Portuguese/English and a
# training/certification that the vacancy only calls an advantage). A
# small model cannot be trusted to follow that rule every time, and the
# Rule Engine treats every listed language as a HARD requirement, so a
# wrong entry wrongly makes candidates ineligible. This deterministic
# check removes a language/certification ONLY when the job text itself
# mentions it as an advantage / "at least one" option and never as a
# mandatory item. If the text does not mention it, or is unclear, the
# entry is KEPT (no change from the LLM answer). No LLM call.
# ---------------------------------------------------------------------
_ADVANTAGE_MARKERS = (
    "advantage", "asset", "preferred", "preferable", "desirable",
    "optional", "nice to have", "bonus", "a plus", "vantagem",
    "preferivel", "preferivel", "sei konsidera", "considered an",
)
_OPTION_MARKERS = (
    "at least one", "one of", "any of", "either", "pelumenus",
    "pelo menos", "minimum one",
)
_MANDATORY_MARKERS = (
    "must", "required", "mandatory", "requires", "has to", "have to",
    "need to", "essential", "obrigat", "tenke",
)


def _sentences(text):
    return [
        x.strip().lower()
        for x in re.split(r"[.;!?\n\r\u2022*]+", text or "")
        if x.strip()
    ]


def _is_not_required(mentions, is_language):
    """mentions = sentences that talk about the item."""
    if not mentions:
        return False  # cannot verify -> keep the LLM's answer

    def flags(sentence):
        adv = any(m in sentence for m in _ADVANTAGE_MARKERS)
        opt = is_language and any(m in sentence for m in _OPTION_MARKERS)
        mand = any(m in sentence for m in _MANDATORY_MARKERS)
        return adv, opt, mand

    marked = [flags(x) for x in mentions]
    has_not_required = any(adv or opt for adv, opt, _ in marked)
    has_required = any(
        mand and not adv and not opt for adv, opt, mand in marked
    )
    return has_not_required and not has_required


def _drop_non_required(profile, text):
    """Never raises; returns the profile (possibly with entries removed)."""
    try:
        sentences = _sentences(text)

        languages = profile.get("languages")
        if isinstance(languages, list):
            kept = []
            for language in languages:
                name = str(language).lower().strip()
                pattern = r"\b" + re.escape(name) + r"\b"
                mentions = [x for x in sentences if name and re.search(pattern, x)]
                if not _is_not_required(mentions, is_language=True):
                    kept.append(language)
            profile["languages"] = kept

        certifications = profile.get("certifications")
        if isinstance(certifications, list):
            kept = []
            for cert in certifications:
                name = str(cert).lower().strip()
                generic = any(w in name for w in ("certif", "training", "course"))
                mentions = [
                    x for x in sentences
                    if (name and name in x)
                    or (generic and any(
                        w in x for w in ("certif", "sertifik", "training", "formasaun")
                    ))
                ]
                if not _is_not_required(mentions, is_language=False):
                    kept.append(cert)
            profile["certifications"] = kept
    except Exception as e:
        logger.warning("_drop_non_required skipped: %s", e)
    return profile


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
- preferred_skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.

REQUIRED vs PREFERRED (very important):
- "skills" = ONLY skills that are REQUIRED / mandatory (for example "must have", "required", "mandatory", "tenke iha", "obrigatoriu").
- Anything marked preferred, preferable, desirable, advantage, optional, nice to have, "sei konsidera hanesan vantagem", "preferivel" or "vantagem" must NOT go in "skills". Put those skills in "preferred_skills" instead.
- Do not list job duties or verbs (for example managing, monitoring, ensuring, maintaining) as skills. Use only technologies, tools and professional competencies that the vacancy asks for.
- "certifications" = ONLY certifications that are explicitly REQUIRED. If a certification or training is only an advantage / preferred, leave it out of "certifications".
- "languages" = ONLY languages that are explicitly REQUIRED as a specific mandatory language. Languages mentioned as an advantage are NOT included.
- If the vacancy only asks for "at least one" language (for example "at least one official language", "pelumenus ida hosi lian ofisial", "one of Tetum or Portuguese"), do NOT list the individual languages: leave "languages" as an empty array.
- years_experience = the MINIMUM years of experience stated as required.

Job Description

{job_description}
"""

    last_result = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            # The schema is sent from the FIRST attempt: with every key
            # required, Gemma cannot stop early with the empty "{}"
            # (which wasted ~18s per occurrence). The existing retry
            # loop is kept unchanged as the safety net.
            result = generate_json(
                prompt=prompt,
                json_schema=JOB_PROFILE_JSON_SCHEMA
            )

            result = _normalize_job_profile_result(result, attempt)

            if isinstance(result, dict) and result:
                result = _drop_non_required(result, job_description)

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