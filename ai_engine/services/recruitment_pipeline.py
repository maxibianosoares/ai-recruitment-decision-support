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


def clamp_confidence(raw_confidence):
    """Guarantee an integer 0-100 regardless of what the LLM returns."""

    try:
        value = float(raw_confidence)
    except (TypeError, ValueError):
        return 0

    return int(max(0, min(100, round(value))))


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

        # =====================================
        # Save Result
        # =====================================

        application.ai_profile = profile

        application.ai_job_profile = job_profile

        application.ai_rule_result = rule_result

        application.ai_semantic_result = semantic_result

        application.ai_skill_gap = gap_result

        application.ai_explainable_report = report

        application.ai_score = semantic_result.get(
            "overall_score",
            0
        )

        application.ai_decision = normalize_decision(
            report.get("decision", "")
        )

        application.ai_confidence = clamp_confidence(
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