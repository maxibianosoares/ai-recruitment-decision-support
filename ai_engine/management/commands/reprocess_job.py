"""
Usage:

    python manage.py reprocess_job <job_id>
    python manage.py reprocess_job --all

2026-09-26 -- one-off repair tool for the array-wrapping bug in
llm_job_parser.py (see ai_engine/services/llm_job_parser.py's
_normalize_job_profile_result() comment): before that fix, a job's
`ai_job_profile` could be silently saved as a single-item JSON array
([{...}]) instead of a bare object ({...}), which then made every
application to that job fail in recruitment_pipeline.py with
"'list' object has no attribute 'get'".

The code fix prevents this going forward, but does NOT repair a job
record that was already saved with the bad (list) shape before the
fix was deployed. This command re-runs the existing, unmodified
process_job() pipeline for the given job(s) so a job already stored
correctly as a dict is simply re-profiled (safe, idempotent), and a
job currently stuck as a list gets a fresh, correctly-typed profile.

Does not touch any Application record, any candidate data, the Rule
Engine, scoring, or RAG -- only re-runs the existing job-profiling
step (job_pipeline.process_job) for the selected Job row(s).
"""

from django.core.management.base import BaseCommand, CommandError

from talent.models import Job
from ai_engine.services.job_pipeline import process_job


class Command(BaseCommand):

    help = (
        "Re-run AI job profiling for one job (by id) or every job "
        "(--all) -- repairs job.ai_job_profile records left in an "
        "invalid list shape by the pre-fix array-wrapping bug."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "job_id",
            nargs="?",
            type=int,
            help="ID of the single job to reprocess."
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Reprocess every job in the database.",
        )

    def handle(self, *args, **options):

        job_id = options.get("job_id")
        do_all = options.get("all")

        if not job_id and not do_all:
            raise CommandError(
                "Provide a job_id, or pass --all to reprocess every job."
            )

        if job_id and do_all:
            raise CommandError(
                "Pass either a job_id or --all, not both."
            )

        jobs = Job.objects.all() if do_all else Job.objects.filter(id=job_id)

        if not jobs.exists():
            raise CommandError(f"No job found (job_id={job_id!r}, all={do_all}).")

        for job in jobs:

            current_shape = type(job.ai_job_profile).__name__

            self.stdout.write(
                f"Reprocessing job {job.id} ({job.title!r}) -- "
                f"current ai_job_profile type: {current_shape} ..."
            )

            try:
                process_job(job)
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(
                        f"  FAILED to reprocess job {job.id}: {e}"
                    )
                )
                continue

            new_shape = type(job.ai_job_profile).__name__

            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK -- job {job.id} ai_job_profile is now: "
                    f"{new_shape}"
                )
            )