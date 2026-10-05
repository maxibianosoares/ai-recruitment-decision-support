"""
FINAL FINISHING SESSION (2026-10-04) -- Async Apply Job background
worker.

WHY THIS SHAPE: the audit (see chat report) confirmed this project has
NO existing durable background mechanism -- no Celery, no Redis, no
RQ, no Django-Q, and the Procfile runs exactly one gunicorn process.
Per the task's explicit safety rule, a raw threading.Thread()/
asyncio.create_task() fire-and-forget inside the web request is NOT
acceptable (it would not survive a Render worker restart/recycle).

This is the smallest production-safe mechanism that needs NO new
infrastructure dependency at all: a DB-backed queue using the
Application.ai_status field that already exists (plain CharField, no
choices=, so these new string values need no migration), polled by
this management command. State lives in the database, not in process
memory, so it is durable across restarts.

State machine (Application.ai_status):
    QUEUED      -- set by talent/views.py.apply_job() immediately
                   after a document passes the quality gate. The
                   candidate's HTTP request returns here -- it never
                   waits for the AI pipeline.
    PROCESSING  -- set by THIS command right before calling the
                   unchanged recruitment_pipeline().
    SUCCESS     -- set by recruitment_pipeline() itself on success
                   (unchanged).
    FAILED      -- set by recruitment_pipeline() itself on any
                   failure, including the Section H reliability fix
                   (malformed/empty fused reasoning -- unchanged
                   function, now raises instead of faking success).

Usage (LOCAL ONLY -- this command is not invoked by the Procfile; it
is not deployed or started in production by this task):

    python manage.py process_pending_applications
        -- single pass: processes every currently-QUEUED application
           once, then exits. Used by tests and for a manual local run.

    python manage.py process_pending_applications --loop
        -- polls every --interval seconds (default 5) until Ctrl+C.
           This is the local stand-in for a Render "worker" process
           type; see the chat report for what a Procfile addition
           would look like if this is ever deployed (NOT done by this
           task).
"""

import time

from django.core.management.base import BaseCommand

from talent.models import Application
from talent.notifications import send_ai_screening_completed_email
from ai_engine.services.recruitment_pipeline import recruitment_pipeline


class Command(BaseCommand):

    help = (
        "Processes Application rows queued (ai_status='QUEUED') by "
        "the async Apply Job flow, running the unchanged "
        "recruitment_pipeline() for each. Local-first: not wired into "
        "the Procfile by this task."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling for newly-queued applications instead "
                 "of exiting after one pass.",
        )

        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="Seconds to sleep between polls when --loop is set "
                 "(default 5).",
        )

    def handle(self, *args, **options):

        loop = options["loop"]
        interval = options["interval"]

        self.stdout.write(
            self.style.NOTICE(
                "[WORKER] process_pending_applications starting "
                f"(loop={loop}, interval={interval}s). Local-only -- "
                "not started by the Procfile."
            )
        )

        while True:

            processed_any = self._process_one_pass()

            if not loop:
                break

            if not processed_any:
                time.sleep(interval)

    def _process_one_pass(self):
        """
        Processes every application currently QUEUED at the moment
        this pass started. Returns True if at least one application
        was processed (so --loop can skip the sleep and check again
        immediately in case more arrived while processing).
        """

        queued_ids = list(
            Application.objects
            .filter(ai_status="QUEUED")
            .order_by("applied_at")
            .values_list("id", flat=True)
        )

        if not queued_ids:
            return False

        self.stdout.write(
            f"[WORKER] found {len(queued_ids)} queued application(s): "
            f"{queued_ids}"
        )

        for application_id in queued_ids:

            # Re-fetch fresh each time rather than reusing a stale
            # in-memory object -- this command may run long (--loop),
            # and each application is independent.
            try:
                application = Application.objects.select_related(
                    "candidate", "job"
                ).get(id=application_id)
            except Application.DoesNotExist:
                continue

            if application.ai_status != "QUEUED":
                # Defensive: guards against double-processing if two
                # worker invocations were ever run concurrently
                # (not expected in this local-only setup, but cheap
                # to guard).
                continue

            application.ai_status = "PROCESSING"
            application.save(update_fields=["ai_status"])

            self.stdout.write(
                f"[WORKER] processing application {application.id} "
                f"(candidate={application.candidate.full_name!r}, "
                f"job={application.job.title!r})..."
            )

            try:

                recruitment_pipeline(application)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"[WORKER] application {application.id} "
                        "completed: ai_status=SUCCESS"
                    )
                )

                # Notification #1 (Section 17): sent ONLY on a real
                # AI_COMPLETED/SUCCESS outcome, right here -- never on
                # FAILED (the except block below), and never confused
                # with Notification #2 (the final human decision
                # email, unchanged -- talent/views.py). An email
                # failure must not change ai_status or any other
                # application field (Section 24) -- caught and logged
                # only, application.ai_status stays "SUCCESS".
                try:
                    send_ai_screening_completed_email(application)
                except Exception as email_error:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[WORKER] application {application.id}: "
                            "AI screening completed, but the "
                            "candidate notification email could not "
                            f"be sent ({email_error}). ai_status "
                            "remains SUCCESS."
                        )
                    )

            except Exception as e:
                # recruitment_pipeline() already recorded
                # ai_status="FAILED" and the error detail in
                # ai_feedback on the application before re-raising --
                # this command just needs to not crash the whole
                # worker loop over one bad application.
                self.stdout.write(
                    self.style.ERROR(
                        f"[WORKER] application {application.id} "
                        f"failed: {e}"
                    )
                )

        return True