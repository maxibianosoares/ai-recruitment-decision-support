"""
Phase 20 (F1) — fused semantic-matching + explainable-recommendation
reasoning, in ONE LLM call instead of two.

Baseline (Phase 1-19, kept intact and importable for comparison):
    llm_semantic_matcher.semantic_match()       -- LLM call #1
    llm_explainable_ai.generate_explainable_report()  -- LLM call #2

Both baseline functions took essentially the same inputs (candidate
profile, job profile, rule result, gap result, and -- for the second
call -- the first call's own output) and asked the LLM to reason
over the same evidence twice: once to produce per-dimension scores,
once to produce a decision/confidence/explanation. This module asks
for both outputs from a single pass over the evidence.

`generate_recruitment_assessment()` returns the raw combined JSON.
`split_assessment()` maps that single result into the two existing
shapes (`semantic_result`, `report`) the rest of the pipeline, the
database fields, and the UI already expect -- so no template, model
field, or downstream consumer needed to change.
"""

import json
import logging

from .model_config import MODEL_NAME
from .llm_service import generate_json
from .llm_candidate_profile import MULTILINGUAL_INSTRUCTION
from .llm_explainable_ai import _format_rag_context
from .llm_semantic_matcher import clamp_score, extract_json

logger = logging.getLogger(__name__)


DEFAULT_DIMENSION_SCORES = {
    "education": 0,
    "experience": 0,
    "technical_skills": 0,
    "soft_skills": 0,
    "certifications": 0,
    "languages": 0
}

DEFAULT_ASSESSMENT = {
    "dimension_scores": dict(DEFAULT_DIMENSION_SCORES),
    "overall_score": 0,
    "strengths": [],
    "weaknesses": [],
    "decision": "",
    "confidence": 0,
    "reasoning": [],
    "risks": [],
    "recommendation": ""
}

ALLOWED_DECISIONS = [
    "Highly Recommended",
    "Recommended",
    "Consider",
    "Not Recommended"
]


def _format_candidate_legal_evidence(candidate_legal_evidence):
    """
    Phase 21 (research, NEW_CANDIDATE_RAG). Additive formatting only
    -- does not touch _format_rag_context (the existing job-level
    formatter, unchanged). Returns "" when there is nothing to add
    (OLD_RAG, or every dimension came back not_applicable), so the
    prompt is byte-identical to before this change whenever the
    feature flag is off.
    """

    if not candidate_legal_evidence:
        return ""

    lines = []

    for dimension, result in candidate_legal_evidence.items():

        status = result.get("status", "not_applicable")

        if status == "not_applicable":
            continue

        lines.append(f"- Dimension: {dimension}")
        lines.append(f"  Evidence status: {status}")

        for item in result.get("evidence", []):

            excerpt = (item.get("verbatim_text") or "")[:400]

            lines.append(
                f"  Evidence ({item.get('source', 'unknown source')}, "
                f"score={item.get('score', 0)}): {excerpt}"
            )

    if not lines:
        return ""

    return "\n".join(lines)


def generate_recruitment_assessment(
    profile,
    job_profile,
    rule_result,
    gap_result,
    rag_context=None,
    candidate_legal_evidence=None,
    num_predict=None
):
    """
    ONE targeted LLM call producing both the per-dimension semantic
    match AND the explainable decision, grounded in the candidate
    profile, job profile, deterministic rule result, skill gap
    result, and the job's cached CSC legal/policy evidence.

    candidate_legal_evidence (Phase 21, research, NEW_CANDIDATE_RAG
    only): optional per-dimension targeted legal evidence from
    candidate_legal_rag.py. When absent/empty (OLD_RAG, the
    production default), the prompt is unchanged from Phase 1-20.

    num_predict (Phase 23, controlled experiment ONLY): forwarded
    unchanged to generate_json(). Default None -- exact current
    behavior. Only set by phase23_num_predict_benchmark.py; no
    production caller passes this today.
    """

    rag_context_text = _format_rag_context(rag_context)

    candidate_legal_evidence_text = _format_candidate_legal_evidence(
        candidate_legal_evidence
    )

    # Empty string when OLD_RAG (or every dimension was
    # not_applicable) -- prompt stays byte-identical to Phase 1-20
    # in that case, nothing new is inserted.
    candidate_section = ""

    if candidate_legal_evidence_text:

        candidate_section = f"""
Candidate-Specific Legal Evidence (targeted retrieval for THIS
candidate's specific gaps against THIS job's requirements -- in
addition to, not a replacement for, the general regulations above.
This is grounding context only; it does NOT by itself determine
eligibility -- the Rule-Based Evaluation above remains the
authoritative source for whether the candidate meets mandatory
requirements. A missing or insufficient evidence status here does
NOT mean the candidate is unqualified, and a found evidence status
does NOT mean the candidate is qualified.)
{candidate_legal_evidence_text}
"""

    prompt = f"""You are a senior HR recruitment expert evaluating a candidate for a civil service position.

{MULTILINGUAL_INSTRUCTION}

Treat synonymous or related terms as matching across languages (e.g.
"Database Management", "Administração de Bases de Dados", and "Administrasi
Basis Data" are the same skill; "Computer Networks" and "Administração de
Redes" are the same). A candidate's language of expression must never by
itself lower or raise a score -- score the underlying evidence, not the
language it is written in.

When comparing candidate evidence to a requirement, distinguish: exact
match, strong semantic match (clearly the same concept, different wording),
partial/related match (relevant but not a direct match), or no evidence.
Reflect that distinction in your reasoning and weaknesses, not just in the
numeric score.

Semantic or linguistic similarity is relevance information for your
scoring, not a legal eligibility decision -- the Rule-Based Evaluation
below is the authoritative source for whether the candidate meets
mandatory/legal requirements. Do not describe a requirement as a Timor-
Leste legal or national requirement unless the Retrieved Regulations below
actually state that; if they do not cover a point, say the regulations do
not specify it, do not assert a legal requirement from general knowledge.

Review all evidence below and produce ONE combined assessment: a per-dimension
match score, and a final recommendation grounded in the retrieved civil
service regulations. If the retrieved regulatory context does not cover a
point, say so rather than inventing a citation.

Candidate Profile
{json.dumps(profile, indent=2)}

Job Profile
{json.dumps(job_profile, indent=2)}

Rule-Based Evaluation
{json.dumps(rule_result, indent=2)}

Skill Gap Analysis
{json.dumps(gap_result, indent=2)}

Retrieved National Civil Service Regulations (applies to this job
category generally, not specifically to this one candidate)
{rag_context_text}
{candidate_section}
All numeric scores are integers from 0 to 100. Keep each reasoning entry to
one short sentence. Return ONLY this JSON, no markdown, no extra text:

{{
    "dimension_scores": {{
        "education": 0,
        "experience": 0,
        "technical_skills": 0,
        "soft_skills": 0,
        "certifications": 0,
        "languages": 0
    }},
    "overall_score": 0,
    "strengths": [],
    "weaknesses": [],
    "decision": "",
    "confidence": 0,
    "reasoning": [],
    "risks": [],
    "recommendation": ""
}}

"decision" must be exactly one of these four strings:
- Highly Recommended
- Recommended
- Consider
- Not Recommended
"""

    try:

        raw = generate_json(prompt=prompt, default=None, num_predict=num_predict)

        # Diagnostic-only addition (2026-09-26): unlike analyze_cv() and
        # analyze_job_description(), this function never printed the raw
        # LLM response, so a "successful" (non-exception) but degenerate
        # response (e.g. all-zero scores, empty reasoning/recommendation)
        # was invisible in production logs -- there was no way to tell
        # a genuinely low-effort LLM answer apart from a deeper problem.
        # Pure visibility: does not change what is validated, returned,
        # or how any decision is made.
        print(f"\n===== FUSED REASONING RAW RESPONSE =====\n")
        print(json.dumps(raw, indent=4) if isinstance(raw, (dict, list)) else raw)
        print("\n=========================================\n")

        # Root cause fix (2026-09-26, confirmed live via the print above,
        # candidate "Joao Martins" / job "Junior Web Developer"): THIRD
        # confirmed occurrence of the same online_gemma array-wrapping
        # shape already fixed in analyze_cv() and
        # analyze_job_description() -- here it was silent and more
        # dangerous than either of those, because there was no
        # dict-vs-list guard at all. _normalize_assessment()'s
        # `dict(raw_result) if isinstance(raw_result, dict) else {}`
        # treated the wrapping list as "not a dict" and threw the ENTIRE
        # real assessment away, replacing a fully-reasoned response
        # (overall_score=33, decision="Not Recommended", confidence=100,
        # full reasoning/strengths/weaknesses/risks/recommendation) with
        # silent all-zero/empty defaults and decision "Consider" -- with
        # ai_status left at "SUCCESS", so nothing on the application
        # record even hinted the real decision was discarded.
        #
        # Same narrow rule as the other two fixes: unwrap ONLY a list
        # containing exactly one dict. Any other shape (empty list,
        # multiple objects, non-dict items) is left untouched, so it
        # still reaches _normalize_assessment()'s existing
        # isinstance(dict) guard and degrades to the same safe defaults
        # as before -- no guessing, no fabricating a result.
        if (
            isinstance(raw, list)
            and len(raw) == 1
            and isinstance(raw[0], dict)
        ):
            logger.warning(
                "generate_recruitment_assessment: LLM returned a "
                "single-item JSON array instead of a bare object; "
                "unwrapping it into the expected assessment object "
                "(original_type=list, normalized_type=dict)."
            )
            raw = raw[0]

        if not raw:
            raise ValueError("Empty response from Ollama.")

        return _normalize_assessment(raw)

    except Exception as e:

        print("Combined Reasoning Error:", str(e))

        result = json.loads(json.dumps(DEFAULT_ASSESSMENT))
        result["recommendation"] = f"Reasoning unavailable: {e}"

        return result


def _normalize_assessment(raw_result):
    """Defense-in-depth clamping, same philosophy as Phase 5/13."""

    result = dict(raw_result) if isinstance(raw_result, dict) else {}

    result["overall_score"] = clamp_score(result.get("overall_score", 0))

    raw_dimensions = result.get("dimension_scores") or {}

    result["dimension_scores"] = {
        key: clamp_score(raw_dimensions.get(key, 0))
        for key in DEFAULT_DIMENSION_SCORES
    }

    try:
        confidence = float(result.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0

    result["confidence"] = int(max(0, min(100, round(confidence))))

    decision_text = str(result.get("decision", "")).strip().lower()

    normalized_decision = "Consider"

    for option in ALLOWED_DECISIONS:
        if option.lower() == decision_text:
            normalized_decision = option
            break
    else:
        if "highly" in decision_text:
            normalized_decision = "Highly Recommended"
        elif "not" in decision_text:
            normalized_decision = "Not Recommended"
        elif "recommend" in decision_text:
            normalized_decision = "Recommended"

    result["decision"] = normalized_decision

    result.setdefault("strengths", [])
    result.setdefault("weaknesses", [])
    result.setdefault("reasoning", [])
    result.setdefault("risks", [])
    result.setdefault("recommendation", "")

    return result


def split_assessment(assessment):
    """
    Maps the single combined assessment into the two shapes the
    existing pipeline, database fields, and templates already
    expect -- application.ai_semantic_result and
    application.ai_explainable_report. No schema/migration change
    needed anywhere downstream.
    """

    semantic_result = {
        "overall_score": assessment["overall_score"],
        "dimension_scores": assessment["dimension_scores"],
        "strengths": assessment.get("strengths", []),
        "weaknesses": assessment.get("weaknesses", []),
        "reasoning": {},
        "recommendation": assessment.get("recommendation", "")
    }

    report = {
        "decision": assessment["decision"],
        "confidence": assessment["confidence"],
        "reasoning": assessment.get("reasoning", []),
        "risks": assessment.get("risks", []),
        "recommendation": assessment.get("recommendation", "")
    }

    return semantic_result, report