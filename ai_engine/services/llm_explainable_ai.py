import json

from .llm_service import generate_json


# BASELINE NOTE (Phase 20): generate_explainable_report() below is
# the Phase 1-19 baseline explainable-decision call (used alone, as
# a separate LLM call after semantic_match()). The live pipeline now
# uses llm_reasoning.generate_recruitment_assessment() instead, which
# fuses this step with dimension-scoring into one call. This function
# is kept functional and importable for baseline comparison, not
# because it is still on the live path.

DEFAULT_REPORT = {
    "decision": "",
    "confidence": 0,
    "reasoning": [],
    "risks": [],
    "recommendation": ""
}


def _format_rag_context(rag_context):
    """
    Renders the cached job-level RAG evidence as short prompt text.
    Defensive against None, missing keys, or an empty evidence list
    (e.g. RAG/Ollama was unreachable when the job was created) --
    always returns a usable string, never raises.
    """

    rag_context = rag_context or {}

    evidence = rag_context.get("evidence") or []

    if not evidence:
        return (
            "No retrieved regulatory context is available for this "
            "job (RAG evidence was empty or unavailable). Do not "
            "invent a legal citation -- rely on the Rule-Based "
            "Evaluation above for compliance questions instead."
        )

    lines = []

    for item in evidence[:3]:

        if not isinstance(item, dict):
            continue

        document = item.get("document", "Unknown document")

        excerpt = item.get("excerpt") or item.get("evidence") or ""

        lines.append(f"- ({document}) {excerpt}")

    return "\n".join(lines) if lines else (
        "No retrieved regulatory context is available for this job."
    )


def generate_explainable_report(
    profile,
    job_profile,
    rule_result,
    semantic_result,
    gap_result,
    rag_context=None
):

    rag_context_text = _format_rag_context(rag_context)

    prompt = f"""
You are a senior HR recruitment expert.

Review all recruitment evidence below and make the final hiring recommendation.
Evaluate candidate compatibility based on the retrieved national civil service
regulations provided in the context below, alongside the CV and rule/semantic
evidence. If the retrieved context does not cover a point, say so rather than
inventing a citation.

Candidate Profile

{json.dumps(profile, indent=2)}

Job Profile

{json.dumps(job_profile, indent=2)}

Rule-Based Evaluation

{json.dumps(rule_result, indent=2)}

Semantic Matching

{json.dumps(semantic_result, indent=2)}

Skill Gap Analysis

{json.dumps(gap_result, indent=2)}

Retrieved National Civil Service Regulations (RAG context, applies to
this job category generally, not specifically to this one candidate)

{rag_context_text}

Return ONLY JSON.

Schema:

{{
    "decision":"",
    "confidence":0,
    "reasoning":[],
    "risks":[],
    "recommendation":""
}}

Decision must be exactly one of these four strings:

- Highly Recommended
- Recommended
- Consider
- Not Recommended

The confidence score MUST be an integer between 0 and 100.
"""
    return generate_json(
    prompt=prompt,
    default=DEFAULT_REPORT
)