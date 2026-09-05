from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from django.utils import timezone

from .llm_candidate_profile import analyze_cv
from .llm_semantic_matcher import semantic_match
from .skill_gap_analysis import skill_gap_analysis
from .recruitment_rules import evaluate_recruitment_rules
from .llm_explainable_ai import generate_explainable_report


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

    NOTE (thesis honesty): rag_score defaults to a fixed placeholder
    (80), NOT a live per-candidate RAG evidence score. The RAG
    Assistant in this system answers POLICY questions from the
    static knowledge base — it has no notion of "this candidate's
    RAG score" to fetch. Treat this weight as reserved for a future
    per-candidate policy-compliance check, not as data currently
    being computed. If asked in the defense, this is the honest
    answer: the 20% RAG term is not yet backed by a real signal.

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
            gap_result=gap_result
        )

        rule_eligible = rule_result.get("eligible", False)

        skill_match_score = gap_result.get("match_score", 0)

        semantic_score = semantic_result.get("overall_score", 0)

        final_score = compute_final_score(
            rule_eligible=rule_eligible,
            skill_match_score=skill_match_score,
            semantic_score=semantic_score
        )

        # =====================================
        # Save Result
        # =====================================

        application.ai_profile = profile

        application.ai_job_profile = job_profile

        application.ai_rule_result = rule_result

        application.ai_semantic_result = semantic_result

        application.ai_skill_gap = gap_result

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