"""
Candidate-Specific Legal RAG (Phase 21, research -- gated by
model_config.NEW_CANDIDATE_RAG, default OFF).

Single responsibility: for the specific gaps/requirements a given
candidate actually has against a given job, find targeted legal
evidence -- as opposed to job.ai_rag_context (rag_screening_context.py),
which answers "what does policy require for this job title in
general" once per job and is identical for every applicant.

MAXIMUM REUSE, NO NEW VERIFIER:
    - retrieval + threshold + LLM scope/temporal verification is
      100% delegated to rag.evidence_coverage.evidence_coverage,
      UNCHANGED (rule 13/14 baseline, no rule 15). This module never
      calls the retriever or the LLM verifier directly -- it only
      decides WHICH targeted claims are worth asking, and formats
      the result.
    - evaluate_recruitment_rules() (recruitment_rules.py) is not
      duplicated or reimplemented. Its existing `matrix` output
      (requirement / evidence / met, per dimension) is the ONLY
      signal used to decide which dimensions need legal grounding.

NO NEW LLM CALLS are introduced for routing, filtering, caching, or
dedup -- all of that is deterministic Python. The only LLM calls that
can happen here are the ones evidence_coverage.evaluate() already
makes internally (unchanged behavior, same as the AI Assistant path).

Output shape (see get_candidate_legal_evidence docstring):
    {
        "education":    {"status": "...", "evidence": [...]},
        "experience":   {"status": "...", "evidence": [...]},
        "language":     {"status": "...", "evidence": [...]},
        "certification":{"status": "...", "evidence": [...]},
    }
Allowed status values only:
    evidence_found | evidence_not_found | evidence_insufficient | not_applicable

Known, documented limitation (not fabricated, not silently ignored):
    - "medical/physical" dimension (see design report Section 6) is
      NOT implemented in this first pass -- DEFAULT_PROFILE /
      DEFAULT_JOB_PROFILE (llm_candidate_profile.py, llm_job_parser.py)
      do not currently extract any medical/physical-eligibility field,
      so there is no candidate signal to check it against. Inventing
      one here would mean either a new LLM extraction field (schema
      change, out of scope for this minimal pass) or fabricating a
      status with no underlying evidence -- both explicitly
      disallowed. Left out entirely rather than faked.
    - The retrieved chunk metadata (rag/vector_store.py) does not
      carry page/article numbers (confirmed during the earlier DE10
      diagnostic: "page: N/A, not tracked in metadata"). Evidence
      entries below therefore omit "article"/"page" rather than
      inventing them.
    - "full-time vs internship vs volunteer" experience-type
      breakdown (design report Section 8) is not implemented: the
      candidate profile schema (llm_candidate_profile.py) only
      extracts a single integer years_experience, with no employment-
      type breakdown field. Building that distinction would require
      either a new extraction field or new rule logic in
      recruitment_rules.py -- both out of scope ("jangan membuat
      aturan experience baru", "jangan mengubah recruitment_rules.py").
      The experience query below is grounded only in the existing
      years_experience number.
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from django.core.cache import cache

from rag.evidence_coverage import evidence_coverage


logger = logging.getLogger(__name__)


# Bump this whenever the query templates, dimension-detection logic,
# or evidence_coverage's own behavior changes in a way that should
# invalidate previously cached candidate-legal-evidence entries.
RAG_VERSION = "candidate-legal-rag-v1"

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h -- research-scale, not tuned yet.

# Safety ceiling per dimension (retrieval + verification combined).
# This is IN ADDITION TO evidence_coverage's own Ollama HTTP timeout
# (OLLAMA_TIMEOUT_SECONDS=300, model_config.py) -- that one guards a
# single generate_json() call; this one guards the whole per-dimension
# step (including retrieval) inside the synchronous candidate-facing
# request path (recruitment_pipeline() runs inline in talent/views.py).
PER_DIMENSION_TIMEOUT_SECONDS = 45

ALLOWED_STATUSES = {
    "evidence_found",
    "evidence_not_found",
    "evidence_insufficient",
    "not_applicable",
}

EMPTY_DIMENSION_RESULT = {"status": "not_applicable", "evidence": []}


# =========================================================
# STEP 4 -- DETERMINISTIC DIMENSION FILTERING (no LLM)
# =========================================================

_DIMENSION_PREFIXES = {
    "education": "Education:",
    "experience": "Experience:",
    "language": "Language:",
    "certification": "Certification (preferred):",
    # "Skill:" entries intentionally excluded -- per design report
    # Section 6, ordinary technical skills do not need legal
    # grounding unless a job/rule signal says otherwise, and no such
    # signal currently exists in recruitment_rules.py's matrix.
}


def _dimensions_needing_legal_grounding(rule_result):
    """
    Pure Python, no I/O, no LLM. Reads recruitment_rules.py's
    existing `matrix` (list of {"requirement", "evidence", "met"})
    and returns {dimension: True/False} for the dimensions this
    module handles.

    A dimension needs legal grounding only if:
      (a) the job actually has a requirement for it (a matrix entry
          exists for that prefix), AND
      (b) at least one of those requirements is NOT met (a genuine
          gap/mismatch worth grounding in the law), per the
          candidate-vs-requirement example in design report
          Section 7 (Bachelor required, Diploma held -> gap -> ground it).

    A requirement that is already fully met needs no legal grounding
    -- there is nothing to justify or contextualize.
    """

    matrix = rule_result.get("matrix", []) if rule_result else []

    needs = {dim: False for dim in _DIMENSION_PREFIXES}
    has_requirement = {dim: False for dim in _DIMENSION_PREFIXES}

    for entry in matrix:

        requirement_text = entry.get("requirement", "") or ""

        for dimension, prefix in _DIMENSION_PREFIXES.items():

            if requirement_text.startswith(prefix):

                has_requirement[dimension] = True

                if not entry.get("met", True):
                    needs[dimension] = True

    return needs, has_requirement


# =========================================================
# STEP 5 -- TARGETED QUERY CONSTRUCTION (no LLM)
# =========================================================

def _build_targeted_query(dimension, profile, job_profile):
    """
    Builds one targeted natural-language query per dimension,
    combining requirement + candidate condition + recruitment
    context (design report Section 7 -- never a bare keyword like
    "education").
    """

    if dimension == "education":

        return (
            "For civil service recruitment, what does the law say "
            "about education eligibility when the position requires "
            f"\"{job_profile.get('education', '') or 'a specific education level'}\" "
            f"but the candidate holds \"{profile.get('education', '') or 'a different education level'}\"?"
        )

    if dimension == "experience":

        return (
            "For civil service recruitment, what does the law say "
            "about professional experience eligibility when the "
            f"position requires at least {job_profile.get('years_experience', 0)} "
            f"years of experience and the candidate has "
            f"{profile.get('years_experience', 0)} years?"
        )

    if dimension == "language":

        required = ", ".join(job_profile.get("languages", []) or []) or "a specific language"
        candidate = ", ".join(profile.get("languages", []) or []) or "no listed language"

        return (
            "For civil service recruitment, what does the law say "
            f"about language requirements when the position requires "
            f"\"{required}\" and the candidate's listed languages are "
            f"\"{candidate}\"?"
        )

    if dimension == "certification":

        required = ", ".join(job_profile.get("certifications", []) or []) or "a specific certification"
        candidate = ", ".join(profile.get("certifications", []) or []) or "no listed certification"

        return (
            "For civil service recruitment, what does the law say "
            f"about certification or qualification requirements when "
            f"the position prefers \"{required}\" and the candidate "
            f"holds \"{candidate}\"?"
        )

    raise ValueError(f"Unknown dimension: {dimension}")


# =========================================================
# STEP 7 -- CACHE KEY (candidate profile + job requirement +
# dimension + RAG_VERSION -- never candidate_id alone, so a changed
# profile can never read a stale cache entry).
# =========================================================

def _cache_key(dimension, profile, job_profile):

    relevant_profile = {
        "education": profile.get("education", ""),
        "years_experience": profile.get("years_experience", 0),
        "languages": sorted(profile.get("languages", []) or []),
        "certifications": sorted(profile.get("certifications", []) or []),
    }

    relevant_job = {
        "education": job_profile.get("education", ""),
        "years_experience": job_profile.get("years_experience", 0),
        "languages": sorted(job_profile.get("languages", []) or []),
        "certifications": sorted(job_profile.get("certifications", []) or []),
    }

    payload = json.dumps(
        {
            "dimension": dimension,
            "profile": relevant_profile,
            "job_profile": relevant_job,
            "version": RAG_VERSION,
        },
        sort_keys=True,
    )

    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return f"candidate_legal_rag:{digest}"


# =========================================================
# STEP 6 -- RETRIEVAL + EXISTING VERIFIER REUSE (no new verifier)
# =========================================================

def _retrieve_dimension_evidence(dimension, query):
    """
    Delegates entirely to evidence_coverage.evaluate() -- the exact
    same retrieval (top_k=3), threshold (0.55), and LLM verify_claim()
    (rule 13/14, unchanged) used by the AI Assistant path. This
    function does not touch the retriever, EvidenceGate, or the LLM
    directly.
    """

    result = evidence_coverage.evaluate([
        {"id": dimension, "text": query}
    ])

    claim_result = result["claims"][0]

    below_threshold = (
        claim_result["score"] < evidence_coverage.threshold
    )

    if claim_result["supported"]:

        status = "evidence_found"

    elif below_threshold:

        status = "evidence_not_found"

    else:

        # Retrieval cleared the relevance threshold but the existing
        # verifier (rule 13/14) rejected it -- wrong actor/population/
        # scheme/temporal scope, or otherwise insufficient. This is
        # the "evidence_insufficient" case, distinct from "nothing
        # relevant was even retrieved".
        status = "evidence_insufficient"

    evidence = []

    if claim_result.get("evidence") and status != "evidence_not_found":

        evidence.append({
            "source": claim_result.get("document"),
            "score": round(float(claim_result.get("score", 0)), 4),
            "verbatim_text": claim_result.get("evidence"),
            "evidence_type": "legal",
            "claim_supported": status == "evidence_found",
            "verification_status": (
                "VERIFIED_VERBATIM" if status == "evidence_found"
                else "REJECTED_BY_VERIFIER"
            ),
            "verification_reason": claim_result.get("verification_reason", ""),
        })

    return status, evidence


def _get_dimension_result(dimension, profile, job_profile, stats):
    """One dimension, cache-checked, timeout-guarded, never raises."""

    key = _cache_key(dimension, profile, job_profile)

    cached = cache.get(key)

    if cached is not None:
        stats["cache_hit"] += 1
        return cached

    stats["cache_miss"] += 1

    query = _build_targeted_query(dimension, profile, job_profile)

    def _run():
        return _retrieve_dimension_evidence(dimension, query)

    stats["retrieval_count"] += 1
    stats["verification_count"] += 1

    try:

        with ThreadPoolExecutor(max_workers=1) as executor:

            future = executor.submit(_run)

            status, evidence = future.result(
                timeout=PER_DIMENSION_TIMEOUT_SECONDS
            )

    except FutureTimeoutError:

        logger.warning(
            "candidate_legal_rag: dimension '%s' timed out after %ss",
            dimension, PER_DIMENSION_TIMEOUT_SECONDS
        )

        status, evidence = "evidence_insufficient", []

    except Exception as exc:

        # Never let a candidate-specific RAG failure fail the
        # application submission (design report Section E / user
        # instruction #18). Log the error, degrade gracefully.
        logger.error(
            "candidate_legal_rag: dimension '%s' failed: %s",
            dimension, exc
        )

        status, evidence = "evidence_not_found", []

    result = {"status": status, "evidence": evidence}

    cache.set(key, result, CACHE_TTL_SECONDS)

    return result


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

def get_candidate_legal_evidence(profile, job_profile, rule_result):
    """
    Main entry point (Step 8 integration target).

    Input:
        profile      -- candidate profile dict (llm_candidate_profile.py shape)
        job_profile  -- job profile dict (llm_job_parser.py shape)
        rule_result  -- evaluate_recruitment_rules() output
                         (recruitment_rules.py, UNCHANGED, read-only here)

    Output:
        (candidate_legal_evidence, stats)

        candidate_legal_evidence: dict keyed by dimension name, e.g.
            {
              "education": {"status": "evidence_found", "evidence": [...]},
              "experience": {"status": "evidence_insufficient", "evidence": []},
              "language": {"status": "not_applicable", "evidence": []},
              "certification": {"status": "not_applicable", "evidence": []}
            }
            Every one of the 4 dimensions handled by this module is
            always present in the output (defaulting to
            not_applicable), so downstream consumers never need a
            missing-key check for a specific dimension -- only the
            top-level key itself may be absent for OLD_RAG callers.

        stats: observability dict (Section 20) -- counts only, no CV
            content, no medical content:
            {
              "dimensions_checked": int,
              "dimensions_retrieved": int,
              "cache_hit": int,
              "cache_miss": int,
              "retrieval_count": int,
              "verification_count": int,
              "candidate_rag_latency": float (seconds)
            }

    Never raises. On any unexpected top-level error, returns an
    empty-but-valid result (all dimensions not_applicable) rather
    than propagating -- application submission must never fail
    because of this module (design report Section E / instruction #18).
    """

    start = time.perf_counter()

    stats = {
        "dimensions_checked": 0,
        "dimensions_retrieved": 0,
        "cache_hit": 0,
        "cache_miss": 0,
        "retrieval_count": 0,
        "verification_count": 0,
        "candidate_rag_latency": 0.0,
    }

    result = {dim: dict(EMPTY_DIMENSION_RESULT) for dim in _DIMENSION_PREFIXES}

    try:

        profile = profile or {}
        job_profile = job_profile or {}
        rule_result = rule_result or {}

        needs, has_requirement = _dimensions_needing_legal_grounding(rule_result)

        for dimension in _DIMENSION_PREFIXES:

            stats["dimensions_checked"] += 1

            if not has_requirement[dimension] or not needs[dimension]:
                # No requirement for this dimension, or requirement
                # already satisfied -- no retrieval call at all
                # (Section 6/11: filter BEFORE retrieval).
                continue

            stats["dimensions_retrieved"] += 1

            result[dimension] = _get_dimension_result(
                dimension, profile, job_profile, stats
            )

    except Exception as exc:

        logger.error("candidate_legal_rag: top-level failure: %s", exc)

        result = {dim: dict(EMPTY_DIMENSION_RESULT) for dim in _DIMENSION_PREFIXES}

    stats["candidate_rag_latency"] = round(time.perf_counter() - start, 3)

    return result, stats