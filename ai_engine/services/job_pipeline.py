from time import perf_counter
from django.utils import timezone

from .llm_job_parser import analyze_job_description


def process_job(job):

    start = perf_counter()

    profile = analyze_job_description(
        job.description
    )

    job.ai_job_profile = profile

    job.ai_processed = True

    job.ai_processing_time = round(
        perf_counter() - start,
        2
    )

    job.ai_processed_at = timezone.now()

    job.save()

    return job