from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from django.utils import timezone

from .llm_candidate_profile import analyze_cv
from .llm_semantic_matcher import semantic_match
from .skill_gap_analysis import skill_gap_analysis
from .recruitment_rules import evaluate_recruitment_rules
from .llm_explainable_ai import generate_explainable_report
from .llm_service import MODEL_NAME as LLM_MODEL_NAME


LLM_PROVIDER_NAME = "Ollama (local)"

AI_PIPELINE_VERSION = "1.0.0"


ALLOWED_DECISIONS = [
    "Highly Recommended",
    "Recommended",
    "Consider",
    "Not Recommended"
]


def normalize_decision(raw_decision):
    """
    The decision label is LLM-generated free text. Map it to the
    canonical whitelist so the UI never has to render an
    unrecognized label; anything unmatched falls back to "Consider"
    so it still surfaces for human review rather than being silently
    dropped.
    """

    text = (raw_decision or "").strip().lower()

    for option in ALLOWED_DECISIONS:
        if option.lower() == text:
            return option

    if "highly" in text:
        return "Highly Recommended"

    if "not" in text:
        return "Not Recommended"

    if "recommend" in text:
        return "Recommended"

    return "Consider"


def clamp_0_100(raw_value):
    """Guarantee an integer 0-100 regardless of what the LLM returns."""

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 0

    return int(max(0, min(100, round(value))))


RAG_POLICY_SCORE_PLACEHOLDER = 80


def compute_final_score(
    rule_eligible,
    skill_match_score,
    semantic_score,
    rag_score=RAG_POLICY_SCORE_PLACEHOLDER
):
    """
    Decision Fusion Formula — single source of truth for the final
    ai_score, shared by the live pipeline and the demo-data seeder
    so seeded scores can never drift from what the real pipeline
    would compute for the same inputs.

    Weighting per thesis methodology:
      Rule Match (skill %)   40%
      LLM Semantic Match     40%
      RAG Engine Policy      20%

    UPDATED (thesis honesty): rag_score is now populated from a real
    RAG query against the CSC legal/policy corpus (see
    rag_screening_context.py + job_pipeline.py) whenever that query
    succeeded at job-creation time. The `RAG_POLICY_SCORE_PLACEHOLDER`
    default below is used ONLY as a fallback when the RAG/Ollama call
    failed or returned no evidence — never as the normal case.

    Known remaining limitation, state this honestly if asked: the
    RAG query is keyed on job title only, computed once per job and
    cached (see recruitment_pipeline.py), not re-run per candidate.
    It answers "what does policy require for this type of role",
    not "how well does this specific person's CV comply" — so this
    term is currently identical for every applicant to the same job,
    not yet a per-candidate compliance signal.

    If the rule engine's hard gate fails (eligible=False), the score
    is capped below the pass threshold regardless of how well
    semantic/skill matching went, so a candidate disqualified by
    hard requirements can never surface as a high score.
    """

    skill_match_score = clamp_0_100(skill_match_score)
    semantic_score = clamp_0_100(semantic_score)
    rag_score = clamp_0_100(rag_score)

    if not rule_eligible:

        final_score = int(
            (skill_match_score * 0.4)
            + (semantic_score * 0.4)
        )

        final_score = min(final_score, 49)

    else:

        final_score = int(
            (skill_match_score * 0.4)
            + (semantic_score * 0.4)
            + (rag_score * 0.2)
        )

    return max(0, min(100, final_score))


def recruitment_pipeline(application):

    start = perf_counter()

    try:

        # =====================================
        # Load Data
        # =====================================

        cv_text = application.candidate.extracted_text

        if not cv_text:

            raise ValueError(
                "Candidate CV text is empty."
            )

        job_profile = application.job.ai_job_profile

        if not job_profile:

            raise ValueError(
                "Job AI Profile has not been generated."
            )

        # Knowledge-Infused Screening: reuse the RAG policy context
        # cached on the job at creation time (see job_pipeline.py).
        # This is a per-job snapshot, not a per-candidate query --
        # copied onto the Application so the evidence a given
        # decision relied on stays fixed even if the job's cached
        # context were ever recomputed later.
        rag_context = application.job.ai_rag_context or {}

        # =====================================
        # STEP 1
        # Candidate Intelligence Profile
        # =====================================

        profile = analyze_cv(
            cv_text
        )

        # =====================================
        # STEP 2
        # Parallel Analysis
        # =====================================

        with ThreadPoolExecutor(max_workers=3) as executor:

            future_rule = executor.submit(
                evaluate_recruitment_rules,
                profile,
                job_profile
            )

            future_gap = executor.submit(
                skill_gap_analysis,
                profile.get("skills", []),
                job_profile.get("skills", [])
            )

            future_semantic = executor.submit(
                semantic_match,
                profile,
                job_profile
            )

            rule_result = future_rule.result()

            gap_result = future_gap.result()

            semantic_result = future_semantic.result()

        # =====================================
        # STEP 3
        # Explainable AI
        # =====================================

        report = generate_explainable_report(
            profile=profile,
            job_profile=job_profile,
            rule_result=rule_result,
            semantic_result=semantic_result,
            gap_result=gap_result,
            rag_context=rag_context
        )

        rule_eligible = rule_result.get("eligible", False)

        skill_match_score = gap_result.get("match_score", 0)

        semantic_score = semantic_result.get("overall_score", 0)

        # Dynamic RAG score: best_evidence_score is a 0-1 float from
        # the RAG evidence gate, scaled to the same 0-100 range as
        # the other two components. If the cached job context is
        # missing, empty, or recorded an error (RAG/Ollama was
        # unreachable when the job was created), fall back to the
        # static placeholder rather than silently scoring every
        # candidate for that job as 0 through no fault of their own.
        if rag_context.get("error") or not rag_context.get("evidence"):

            rag_score = RAG_POLICY_SCORE_PLACEHOLDER

        else:

            rag_score = rag_context.get("best_evidence_score", 0) * 100

        final_score = compute_final_score(
            rule_eligible=rule_eligible,
            skill_match_score=skill_match_score,
            semantic_score=semantic_score,
            rag_score=rag_score
        )

        # =====================================
        # Save Result
        # =====================================

        application.ai_profile = profile

        application.ai_job_profile = job_profile

        application.ai_rule_result = rule_result

        application.ai_semantic_result = semantic_result

        application.ai_skill_gap = gap_result

        application.ai_rag_context = rag_context

        application.ai_explainable_report = report

        application.ai_score = final_score

        application.ai_decision = normalize_decision(
            report.get("decision", "")
        )

        application.ai_confidence = clamp_0_100(
            report.get("confidence", 0)
        )

        application.ai_feedback = report.get(
            "recommendation",
            ""
        )

        # Audit Trail (Phase 18): record which model/provider/version
        # actually produced this decision, rather than relying on the
        # field's static default -- so the value here is genuinely
        # traceable even if the model or version changes later.
        application.ai_model = LLM_MODEL_NAME

        application.ai_provider = LLM_PROVIDER_NAME

        application.ai_version = AI_PIPELINE_VERSION

        application.ai_processing_time = round(
            perf_counter() - start,
            2
        )

        application.ai_processed_at = timezone.now()

        application.ai_status = "SUCCESS"

        application.save()

        return application

    except Exception as e:

        application.ai_status = "FAILED"

        application.ai_feedback = str(e)

        application.ai_processing_time = round(
            perf_counter() - start,
            2
        )

        application.ai_processed_at = timezone.now()

        application.save()

        raise