from time import perf_counter
from django.utils import timezone

from .llm_job_parser import analyze_job_description, DEFAULT_JOB_PROFILE
from .rag_screening_context import get_rag_screening_context


def process_job(job):

    start = perf_counter()

    profile = analyze_job_description(
        job.description
    )

    # Widened 2026-09-26 (same root cause/fix as
    # recruitment_pipeline.py's analogous guard): a bare `if not
    # profile:` treats ANY non-empty list as valid, including a
    # multi-item array shape that analyze_job_description()'s own
    # normalization intentionally leaves unwrapped (no safe single
    # object to pick). Checking for a dict carrying at least one
    # DEFAULT_JOB_PROFILE key (and rejecting the existing "error" key
    # from analyze_job_description()'s own exception path) closes that
    # gap without changing behavior for the normal case.
    if (
        not isinstance(profile, dict)
        or not any(key in profile for key in DEFAULT_JOB_PROFILE)
        or "error" in profile
    ):
        raise ValueError(
            "AI service returned an invalid or empty job profile "
            "(the LLM may be unreachable, or returned an unexpected "
            "response shape)."
        )

    print("\n====================================")
    print("ICT OFFICER JOB PROFILE")
    print("====================================")
    print(profile)
    print("====================================\n")

    job.ai_job_profile = profile

    # Knowledge-Infused Screening: one live RAG query per job,
    # cached here so every applicant to this job reuses the same
    # policy evidence instead of re-querying RAG identically on
    # every single application. Never raises — a RAG/Ollama failure
    # here degrades to an empty context (handled downstream by
    # recruitment_pipeline's fallback to the static placeholder
    # weight), it does not block job creation.
    job.ai_rag_context = get_rag_screening_context(job.title)

    job.ai_processed = True

    job.ai_processing_time = round(
        perf_counter() - start,
        2
    )

    job.ai_processed_at = timezone.now()

    job.save()

    return job