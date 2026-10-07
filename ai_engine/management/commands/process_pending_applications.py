"""
FINAL FINISHING SESSION (2026-10-04, updated 2026-10-05 for automatic
execution, updated 2026-10-06 for TASK I) -- Async Apply Job background
worker.

WHY THIS SHAPE: this project has NO durable background mechanism --
no Celery, no Redis, no RQ, no Django-Q. A raw threading.Thread()/
asyncio.create_task() inside the web request is NOT acceptable (it
would not survive a web process restart, and would stop the moment
nobody is sending HTTP requests).

This is the smallest production-safe mechanism that needs NO new
infrastructure: a DB-backed queue using the Application.ai_status
field (a plain CharField, so new string values need no migration),
polled by this management command running as its own OS process. State
lives in the database, not in process memory, so it survives restarts
of either the web process or this worker.

RUNNING: meant to run continuously (`--loop`) as its OWN long-lived
process -- in production the Railway "worker" service from the
Procfile; locally a second terminal. Nothing starts it in-process.

TASK I -- the heavy work moved here. The web request used to run
document extraction/OCR before creating the Application (blocked by
gunicorn's 120s timeout, and able to exhaust memory on a long scan).
Now the web request only validates the file's structure and queues it;
this worker does the extraction and then the AI screening.

State machine (Application.ai_status, see talent/statuses.py):

    QUEUED             set by apply_job() after the cheap structural
                       check; the candidate's request returns here.
    EXTRACTING         worker claimed it and is reading the document.
      -> DOCUMENT_INVALID   corrupt / password-protected / unrenderable.
      -> EXTRACTION_FAILED  valid PDF, but text missing, too little,
                            low quality, or a page failed technically.
         (neither reaches the AI pipeline; neither sends Notification
         #1; the candidate gets an explanatory email and may re-upload)
    EXTRACTED          text is complete enough; saved on the candidate.
    PROCESSING         recruitment_pipeline() (unchanged) is running.
    SUCCESS / FAILED   set by recruitment_pipeline() itself.
                       Notification #1 is sent ONLY after SUCCESS.

DUPLICATE PREVENTION: the QUEUED -> EXTRACTING/PROCESSING claim is one
DB transaction using select_for_update(skip_locked=True), so two worker
instances can never take the same application (a no-op on SQLite, real
row locks on production Postgres).

CRASH RECOVERY: if this process dies while an application is
EXTRACTING / EXTRACTED / PROCESSING, nothing would otherwise move it
back. At startup every such row is requeued; the uploaded PDF is kept
in ApplicationDocument until the application reaches a terminal state,
so extraction can simply be redone from the start (the pipeline is not
resumable mid-way either). Safe because exactly ONE worker instance
runs; if more are ever added, requeue-at-startup would need a
heartbeat/lease instead.

LEGACY ROWS: an application queued before TASK I has no
ApplicationDocument (its text was already extracted by the old web
request). It skips extraction and goes straight to the pipeline.

Usage:

    python manage.py process_pending_applications
        -- single pass over everything currently QUEUED, then exit
           (automated tests, one-off local run).

    python manage.py process_pending_applications --loop
        -- poll every --interval seconds until stopped (production).
"""

import os
import tempfile
import time

from django.core.management.base import BaseCommand
from django.db import (
    InterfaceError,
    OperationalError,
    connections,
    transaction,
)
from django.utils import timezone

from talent import statuses as S
from talent.models import Application, ApplicationDocument
from talent.notifications import (
    send_ai_screening_completed_email,
    send_document_issue_email,
)
from ai_engine.services.recruitment_pipeline import recruitment_pipeline
from ai_engine.services.document_extraction import orchestrator


class Command(BaseCommand):

    help = (
        "Processes Application rows queued (ai_status='QUEUED') by "
        "the async Apply Job flow: extracts the uploaded CV, then runs "
        "the unchanged recruitment_pipeline(). Intended to run "
        "continuously via --loop, as its own process."
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
                 "and nothing was found to process (default 5).",
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

        # Recovery of rows left in-flight by a previous run happens
        # first, and again after any database error below.
        needs_recovery = True

        while True:

            try:

                if needs_recovery:
                    self._requeue_stale_in_flight_applications()
                    needs_recovery = False

                processed_any = self._process_one_pass()

            except (OperationalError, InterfaceError) as db_error:
                # A transient database problem (a dropped Neon
                # connection, a SQLite "database is locked" while the
                # web process is writing) must not kill the worker for
                # good. Drop the connection, wait, and try again. The
                # application being handled when it happened may have
                # been left EXTRACTING/EXTRACTED/PROCESSING, so recovery
                # runs again before the next pass (safe: this is the
                # only worker, and it is not processing anything now).
                if not loop:
                    raise

                self.stdout.write(
                    self.style.WARNING(
                        "[WORKER] database error, will retry in "
                        f"{interval}s: {db_error}"
                    )
                )
                connections.close_all()
                needs_recovery = True
                time.sleep(interval)
                continue

            if not loop:
                break

            if not processed_any:
                time.sleep(interval)

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def _requeue_stale_in_flight_applications(self):
        """
        Run once at startup. Any application still EXTRACTING,
        EXTRACTED or PROCESSING cannot belong to a live worker (this is
        the only worker and it is only just starting), so it is left
        over from a run that did not finish. Reset to QUEUED for a full
        retry from extraction (the PDF is still stored; see module
        docstring).
        """

        self._remove_orphan_documents()

        stale_ids = list(
            Application.objects
            .filter(ai_status__in=S.IN_FLIGHT_STATUSES)
            .values_list("id", flat=True)
        )

        if not stale_ids:
            return

        Application.objects.filter(id__in=stale_ids).update(
            ai_status=S.QUEUED
        )

        self.stdout.write(
            self.style.WARNING(
                f"[WORKER] requeued {len(stale_ids)} application(s) "
                "found stuck in an in-flight state from a previous run "
                f"(crash/restart recovery): {stale_ids}"
            )
        )

    def _remove_orphan_documents(self):
        """
        A stored PDF is only needed while its application is QUEUED or
        in flight, or may be re-queued (DOCUMENT_INVALID /
        EXTRACTION_FAILED rows have already had theirs released). If a
        previous run died between reaching a terminal state and
        releasing the PDF, the 5MB blob would stay forever; remove it.
        """

        keep = (S.QUEUED,) + tuple(S.IN_FLIGHT_STATUSES)

        deleted, _ = (
            ApplicationDocument.objects
            .exclude(application__ai_status__in=keep)
            .delete()
        )

        if deleted:
            self.stdout.write(
                f"[WORKER] removed {deleted} orphaned stored document(s)."
            )

    # ------------------------------------------------------------------
    # Main pass
    # ------------------------------------------------------------------

    def _process_one_pass(self):
        """
        Processes every application QUEUED at the moment this pass
        started. Returns True if at least one was processed (so --loop
        skips the sleep and checks again immediately).
        """

        queued_ids = list(
            Application.objects
            .filter(ai_status=S.QUEUED)
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

            application, has_document = self._claim(application_id)

            if application is None:
                continue

            self.stdout.write(
                f"[WORKER] processing application {application.id} "
                f"(candidate={application.candidate.full_name!r}, "
                f"job={application.job.title!r}, "
                f"has_document={has_document})..."
            )

            self._run(application, has_document)

            # A terminal state was reached: the stored PDF is no
            # longer needed. Deliberately NOT in a `finally`: if the
            # process is interrupted mid-application the PDF must stay
            # so the startup requeue can redo extraction. _run()
            # handles its own errors, so this line is reached for every
            # application that actually finished.
            self._release_document(application.id)

        return True

    def _claim(self, application_id):
        """
        Atomic QUEUED -> EXTRACTING (or -> PROCESSING for a legacy row
        with no stored document). Returns (application, has_document),
        or (None, False) if it was already taken or processed.
        """

        with transaction.atomic():

            try:
                application = (
                    Application.objects
                    .select_for_update(skip_locked=True)
                    .select_related("candidate", "job")
                    .get(id=application_id)
                )
            except Application.DoesNotExist:
                # Gone, or locked by another worker instance.
                return None, False

            if application.ai_status != S.QUEUED:
                return None, False

            has_document = ApplicationDocument.objects.filter(
                application_id=application.id
            ).exists()

            application.ai_status = (
                S.EXTRACTING if has_document else S.PROCESSING
            )
            application.save(update_fields=["ai_status"])

        return application, has_document

    def _run(self, application, has_document):

        if has_document:

            try:
                may_continue = self._extract(application)
            except Exception as e:
                # An unexpected bug in extraction is a SYSTEM fault,
                # not the candidate's: record FAILED honestly instead
                # of telling them to re-upload a fine file.
                self._mark(
                    application, S.FAILED,
                    feedback=f"Document extraction failed unexpectedly: {e}",
                    error=repr(e),
                )
                self.stdout.write(
                    self.style.ERROR(
                        f"[WORKER] application {application.id} "
                        f"extraction crashed: {e}"
                    )
                )
                return

            if not may_continue:
                return

            application.ai_status = S.PROCESSING
            application.save(update_fields=["ai_status"])

        try:

            recruitment_pipeline(application)

            self.stdout.write(
                self.style.SUCCESS(
                    f"[WORKER] application {application.id} "
                    "completed: ai_status=SUCCESS"
                )
            )

            # Notification #1: only after a real AI SUCCESS, never
            # for an extraction failure (those returned above) and
            # never for FAILED (the except below). An email failure
            # must not change ai_status.
            if application.ai_status == S.SUCCESS:
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
            # recruitment_pipeline() already recorded FAILED and the
            # detail in ai_feedback before re-raising; just keep the
            # worker loop alive for the next application.
            self.stdout.write(
                self.style.ERROR(
                    f"[WORKER] application {application.id} "
                    f"failed: {e}"
                )
            )

    # ------------------------------------------------------------------
    # Extraction stage
    # ------------------------------------------------------------------

    def _extract(self, application):
        """
        Reads the stored PDF. Returns True when the text is complete
        enough to go to the AI pipeline (status EXTRACTED, text saved
        on the candidate); returns False after recording a terminal
        DOCUMENT_INVALID / EXTRACTION_FAILED status.
        """

        document = ApplicationDocument.objects.get(
            application_id=application.id
        )

        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(document.pdf_bytes))
            outcome = orchestrator.extract_document(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        report = outcome.report

        self.stdout.write(
            f"[WORKER] application {application.id} extraction: "
            f"state={outcome.state} pages={report.get('pages_total')} "
            f"method={report.get('method')} "
            f"chars={report.get('chars')} "
            f"complete={report.get('complete')} "
            f"seconds={report.get('seconds')}"
        )

        if outcome.state == orchestrator.OK:

            candidate = application.candidate
            candidate.extracted_text = outcome.text
            candidate.save(update_fields=["extracted_text"])

            application.extraction_report = report
            application.ai_status = S.EXTRACTED
            application.save(
                update_fields=["ai_status", "extraction_report"]
            )

            return True

        status = (
            S.DOCUMENT_INVALID
            if outcome.state == orchestrator.INVALID
            else S.EXTRACTION_FAILED
        )

        application.extraction_report = report

        self._mark(
            application, status,
            feedback=outcome.reason,
            error="; ".join(
                f"page {f['page']}: {f['error']}"
                for f in report.get("pages_failed", [])
            ),
        )

        try:
            send_document_issue_email(application)
        except Exception as email_error:
            self.stdout.write(
                self.style.WARNING(
                    f"[WORKER] application {application.id}: could not "
                    f"send the document-issue email ({email_error}). "
                    f"ai_status remains {status}."
                )
            )

        self.stdout.write(
            self.style.WARNING(
                f"[WORKER] application {application.id} stopped before "
                f"AI screening: ai_status={status}"
            )
        )

        return False

    def _mark(self, application, status, feedback="", error=""):

        application.ai_status = status
        application.ai_feedback = feedback
        application.ai_error = error
        application.ai_processed_at = timezone.now()
        application.save(update_fields=[
            "ai_status", "ai_feedback", "ai_error",
            "ai_processed_at", "extraction_report",
        ])

    def _release_document(self, application_id):
        ApplicationDocument.objects.filter(
            application_id=application_id
        ).delete()