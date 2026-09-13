from time import perf_counter
from django.utils import timezone

from .llm_job_parser import analyze_job_description
from .rag_screening_context import get_rag_screening_context


def process_job(job):

    start = perf_counter()

    profile = analyze_job_description(
        job.description
    )

    if not profile:
        raise ValueError(
            "AI service returned an empty job profile "
            "(the local LLM may be unreachable)."
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