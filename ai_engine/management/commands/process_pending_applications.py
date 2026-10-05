"""
FINAL FINISHING SESSION (2026-10-04, updated 2026-10-05 for automatic
execution) -- Async Apply Job background worker.

WHY THIS SHAPE: the audit (see chat report) confirmed this project has
NO existing durable background mechanism -- no Celery, no Redis, no
RQ, no Django-Q. Per the task's explicit safety rule, a raw
threading.Thread()/asyncio.create_task() fire-and-forget inside the
web request is NOT acceptable (it would not survive a Render web
process restart/recycle, and would stop running the moment nobody is
sending it HTTP requests).

This is the smallest production-safe mechanism that needs NO new
infrastructure dependency at all: a DB-backed queue using the
Application.ai_status field that already exists (plain CharField, no
choices=, so these new string values need no migration), polled by
this management command running as its own OS process. State lives in
the database, not in process memory, so it is durable across restarts
of either the web process or this worker process.

AUTOMATIC EXECUTION (2026-10-05): this command is now meant to run
continuously (`--loop`) as its OWN long-lived process -- in
production, that process is a separate Render "Background Worker"
service (see Procfile's new `worker:` line and the deployment notes in
the chat report), supervised and auto-restarted by Render itself, not
by this project's code. Nobody needs to SSH into Render and run this
command by hand; Render starts it when the service deploys and
restarts it if it crashes, exactly like it already does for the `web`
service. Locally, the equivalent is simply running this same command
with --loop in a second terminal (see chat report for the exact local
dev instructions) -- there is no in-process/thread-based "auto-start"
here on purpose, because that would NOT reflect how it actually runs
in production and would violate the "no thread/asyncio background
task" rule.

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
                   function, raises instead of faking success).

CRASH RECOVERY (2026-10-05): if this worker process itself is killed
or crashes (not a Python exception inside recruitment_pipeline, which
is already handled below, but the OS process dying -- e.g. Render
redeploying/recycling the Background Worker service) WHILE an
application was marked PROCESSING, nothing would otherwise ever move
that row back to QUEUED, since the normal poll only ever looks for
ai_status="QUEUED". See _requeue_stale_processing_applications() below
-- run once at startup, it requeues any leftover PROCESSING row so it
gets retried through the full pipeline on the next pass. This is safe
specifically because this project runs exactly ONE worker instance
(see the atomic claim in _process_one_pass() below for why a second
concurrent instance is also safe, should one ever be added).

Usage:

    python manage.py process_pending_applications
        -- single pass: processes every currently-QUEUED application
           once, then exits. Used by the automated tests and for a
           manual one-off local run.

    python manage.py process_pending_applications --loop
        -- polls every --interval seconds (default 5) until stopped.
           This is the command Render's Background Worker service
           (production) and a second local terminal (development) both
           run continuously -- see the chat report for exact commands.
"""

import time

from django.core.management.base import BaseCommand
from django.db import transaction

from talent.models import Application
from talent.notifications import send_ai_screening_completed_email
from ai_engine.services.recruitment_pipeline import recruitment_pipeline


class Command(BaseCommand):

    help = (
        "Processes Application rows queued (ai_status='QUEUED') by "
        "the async Apply Job flow, running the unchanged "
        "recruitment_pipeline() for each. Intended to run "
        "continuously via --loop, as its own process (a Render "
        "Background Worker service in production; a second local "
        "terminal in development)."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling for newly-queued applications instead "
                 "of exiting after one pass. This is the mode used "
                 "for continuous/automatic execution.",
        )

        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="Seconds to sleep between polls when --loop is set "
                 "and nothing was found to process (default 5). Not "
                 "a busy-loop: the sleep only happens when a pass "
                 "found zero QUEUED applications.",
        )

    def handle(self, *args, **options):

        loop = options["loop"]
        interval = options["interval"]

        self.stdout.write(
            self.style.NOTICE(
                "[WORKER] process_pending_applications starting "
                f"(loop={loop}, interval={interval}s)."
            )
        )

        self._requeue_stale_processing_applications()

        while True:

            processed_any = self._process_one_pass()

            if not loop:
                break

            if not processed_any:
                time.sleep(interval)

    def _requeue_stale_processing_applications(self):
        """
        Crash-recovery step, run once when this worker process starts
        (see module docstring). Any Application still marked
        PROCESSING at startup cannot belong to a worker that is still
        alive -- this process is the only worker instance, and it is
        only just starting now -- so it can only be left over from a
        previous run of this same command that did not get to finish
        normally (crash, kill, Render recycling the service mid-job).
        Reset to QUEUED so the normal poll below picks it up and
        retries it through the full, unchanged recruitment_pipeline()
        -- not resumed mid-way (this pipeline is not designed to be
        partially resumed; a full retry is the safe behavior here,
        exactly as a fresh application would be processed).
        """

        stale_ids = list(
            Application.objects
            .filter(ai_status="PROCESSING")
            .values_list("id", flat=True)
        )

        if not stale_ids:
            return

        Application.objects.filter(id__in=stale_ids).update(
            ai_status="QUEUED"
        )

        self.stdout.write(
            self.style.WARNING(
                f"[WORKER] requeued {len(stale_ids)} application(s) "
                "found stuck in PROCESSING from a previous run "
                f"(crash/restart recovery): {stale_ids}"
            )
        )

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

            # ATOMIC CLAIM (2026-10-05, automatic-worker hardening):
            # the fetch-check-update that marks an application
            # PROCESSING is now wrapped in one DB transaction using
            # select_for_update(skip_locked=True) -- this makes "two
            # workers never process the same application twice" true
            # even if more than one worker instance is ever run
            # concurrently (e.g. if the Render Background Worker
            # service were later scaled to >1 instance), not just true
            # "by convention" as the single select+update below used
            # to be (a race was possible between the status check and
            # the save under concurrent workers). skip_locked=True
            # means a second worker that reaches the same row while
            # it's locked simply skips it this pass, instead of
            # blocking or double-processing it.
            #
            # On SQLite (local dev), select_for_update() has no
            # effect (SQLite has no row-level locking support) --
            # this is a documented, harmless no-op there, which is
            # fine because local dev only ever runs one worker
            # instance. On the production Postgres database (Neon),
            # it provides the real row lock.
            with transaction.atomic():

                try:
                    application = (
                        Application.objects
                        .select_for_update(skip_locked=True)
                        .select_related("candidate", "job")
                        .get(id=application_id)
                    )
                except Application.DoesNotExist:
                    continue

                if application.ai_status != "QUEUED":
                    # Either already claimed by another worker
                    # instance between the query above and this
                    # lock, or already processed -- skip, never
                    # reprocess.
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
                # worker loop over one bad application, so the next
                # application in this pass (and future passes) still
                # gets processed.
                self.stdout.write(
                    self.style.ERROR(
                        f"[WORKER] application {application.id} "
                        f"failed: {e}"
                    )
                )

        return True