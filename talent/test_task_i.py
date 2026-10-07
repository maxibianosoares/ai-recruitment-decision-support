"""
TASK I (2026-10-06) -- asynchronous document extraction tests.

Real extraction (pypdf, Poppler, Tesseract) runs in these tests; only
the AI pipeline and the Notification #1 sender are mocked, because the
subject here is WHAT REACHES them and WHEN. All PDFs are synthetic.
"""

import io
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ai_engine.services.document_extraction import orchestrator
from ai_engine.services.document_extraction.structure import (
    check_pdf_structure,
)
from ai_engine.test_document_extraction import (
    _make_digital_pdf,
    _make_scanned_pdf,
)
from talent import statuses as S
from talent.models import Application, ApplicationDocument, Candidate, Job
from talent.tests import _make_role

WORKER = "ai_engine.management.commands.process_pending_applications"

CV_LINES = [
    "Maria da Silva", "Bachelor of Information Technology",
    "Five years of experience as an ICT officer in Dili",
    "Skills: networking, Python, database administration",
    "Languages: Tetum, Portuguese, English",
]


def _bytes_of(builder, *args):
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        builder(path, *args)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def native_pdf():
    return _bytes_of(_make_digital_pdf, CV_LINES)


def scanned_pdf(pages=1):
    return _bytes_of(
        _make_scanned_pdf,
        [[f"Page {n + 1} Curriculum Vitae of Maria da Silva",
          "Experience: ICT officer at the Ministry of Finance in Dili",
          "Education: Bachelor of Information Technology"]
         for n in range(pages)]
    )


def encrypted_pdf():
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(native_pdf())).pages:
        writer.add_page(page)
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def mixed_pdf():
    """Page 1 digital text, page 2 image-only scan."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in CV_LINES:
        pdf.cell(text=line, new_x="LMARGIN", new_y="NEXT")

    img = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(img)
    y = 100
    for line in ["Certificates and training scanned from paper",
                 "Project management certificate awarded in 2022"]:
        draw.text((100, y), line, fill="black")
        y += 60
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "p.png")
        img.save(p)
        pdf.add_page()
        pdf.image(p, x=0, y=0, w=612, h=792)
        return bytes(pdf.output())


def blank_page_pdf():
    """Digital page followed by a genuinely empty scanned page."""
    from fpdf import FPDF
    from PIL import Image

    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in CV_LINES:
        pdf.cell(text=line, new_x="LMARGIN", new_y="NEXT")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "blank.png")
        Image.new("RGB", (1700, 2200), "white").save(p)
        pdf.add_page()
        pdf.image(p, x=0, y=0, w=612, h=792)
        return bytes(pdf.output())


class TaskIBase(TestCase):

    def setUp(self):
        cache.clear()
        self.job = Job.objects.create(
            title="ICT Officer", department="ICT",
            description="x", requirements="x",
            ai_job_profile={
                "job_title": "ICT Officer", "education": "Bachelor",
                "years_experience": 0, "languages": [],
                "certifications": [], "skills": []
            },
            ai_processed=True,
            ai_rag_context={"evidence": [], "best_evidence_score": 0,
                            "grounded": False, "error": None},
        )
        self.user = User.objects.create_user(
            username="ti", password="pass12345", email="ti@x.com",
            first_name="Maria", role=_make_role("Candidate"),
            is_verified=True,
        )
        self.candidate = Candidate.objects.create(
            user=self.user, full_name="Maria da Silva", email="ti@x.com"
        )

    def queue(self, pdf_bytes, with_document=True):
        application = Application.objects.create(
            candidate=self.candidate, job=self.job, ai_status=S.QUEUED
        )
        if with_document:
            ApplicationDocument.objects.create(
                application=application, pdf_bytes=pdf_bytes,
                original_filename="cv.pdf",
            )
        return application

    @staticmethod
    def fake_pipeline(seen=None):
        def _run(app):
            if seen is not None:
                seen.append(app.candidate.extracted_text)
            app.ai_status = S.SUCCESS
            app.ai_score = 70
            app.save()
            return app
        return _run

    def run_worker(self, pipeline=None):
        pipeline = pipeline or mock.MagicMock(
            side_effect=self.fake_pipeline()
        )
        with mock.patch(f"{WORKER}.recruitment_pipeline", pipeline), \
                mock.patch(f"{WORKER}.send_ai_screening_completed_email") \
                as notif1:
            call_command("process_pending_applications", stdout=StringIO())
        return pipeline, notif1


class WorkerExtractionTests(TaskIBase):

    # 1. native PDF
    def test_native_pdf_is_extracted_then_screened_then_notified(self):
        app = self.queue(native_pdf())
        seen = []
        pipeline, notif1 = self.run_worker(
            mock.MagicMock(side_effect=self.fake_pipeline(seen))
        )
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        pipeline.assert_called_once()
        self.assertIn("Maria da Silva", seen[0])
        self.assertEqual(app.extraction_report["method"], "native")
        self.assertTrue(app.extraction_report["complete"])
        notif1.assert_called_once()
        # the stored PDF is released at the terminal state
        self.assertFalse(
            ApplicationDocument.objects.filter(application=app).exists()
        )

    # 2. scanned PDF (real OCR)
    def test_scanned_pdf_goes_through_ocr(self):
        app = self.queue(scanned_pdf(1))
        seen = []
        self.run_worker(mock.MagicMock(side_effect=self.fake_pipeline(seen)))
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        self.assertEqual(app.extraction_report["method"], "ocr")
        self.assertIn("Experience", seen[0])

    # 3. multi-page scan: nothing dropped
    def test_multi_page_scan_keeps_every_page(self):
        app = self.queue(scanned_pdf(3))
        seen = []
        self.run_worker(mock.MagicMock(side_effect=self.fake_pipeline(seen)))
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        report = app.extraction_report
        self.assertEqual(report["pages_total"], 3)
        self.assertEqual(len(report["pages"]), 3)
        self.assertEqual(report["pages_failed"], [])
        for n in (1, 2, 3):
            self.assertIn(f"Page {n}", seen[0])

    # 4. OCR technical failure on a page => no AI, no Notification #1
    def test_ocr_page_failure_stops_before_ai(self):
        app = self.queue(scanned_pdf(2))
        from ai_engine.services import ocr_fallback

        with mock.patch.object(
            ocr_fallback, "_ocr_one_page",
            side_effect=RuntimeError("tesseract timeout")
        ):
            pipeline, notif1 = self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.EXTRACTION_FAILED)
        pipeline.assert_not_called()
        notif1.assert_not_called()

    # 5/6. corrupt and encrypted stored documents
    def test_corrupt_document_is_invalid(self):
        app = self.queue(b"this is definitely not a pdf")
        pipeline, notif1 = self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.DOCUMENT_INVALID)
        pipeline.assert_not_called()
        notif1.assert_not_called()

    def test_encrypted_document_is_invalid(self):
        app = self.queue(encrypted_pdf())
        pipeline, notif1 = self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.DOCUMENT_INVALID)
        self.assertIn("password", app.ai_feedback.lower())
        pipeline.assert_not_called()
        notif1.assert_not_called()

    # 7. too little text
    def test_near_empty_extraction_is_extraction_failed(self):
        app = self.queue(_bytes_of(_make_digital_pdf, ["Hi"]))
        pipeline, notif1 = self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.EXTRACTION_FAILED)
        self.assertTrue(app.ai_feedback)
        pipeline.assert_not_called()
        notif1.assert_not_called()

    # 8. complete text is what gets saved
    def test_full_text_saved_on_candidate(self):
        self.queue(native_pdf())
        self.run_worker()
        self.candidate.refresh_from_db()
        for line in CV_LINES:
            self.assertIn(line, self.candidate.extracted_text)

    # 9. crash recovery
    def test_in_flight_rows_are_requeued_and_finish(self):
        app = self.queue(native_pdf())
        for stuck in (S.EXTRACTING, S.EXTRACTED, S.PROCESSING):
            Application.objects.filter(id=app.id).update(ai_status=stuck)
            self.assertTrue(
                ApplicationDocument.objects.filter(application=app).exists()
            )
            pipeline, _ = self.run_worker()
            app.refresh_from_db()
            self.assertEqual(app.ai_status, S.SUCCESS, stuck)
            pipeline.assert_called_once()
            # put the document back for the next iteration
            ApplicationDocument.objects.update_or_create(
                application=app, defaults={"pdf_bytes": native_pdf()}
            )

    def test_interrupted_run_keeps_the_pdf(self):
        app = self.queue(native_pdf())
        with mock.patch(f"{WORKER}.recruitment_pipeline",
                        side_effect=KeyboardInterrupt), \
                mock.patch(f"{WORKER}.send_ai_screening_completed_email"):
            with self.assertRaises(KeyboardInterrupt):
                call_command("process_pending_applications",
                             stdout=StringIO())
        self.assertTrue(
            ApplicationDocument.objects.filter(application=app).exists()
        )

    # 10. Notification #1 ordering
    def test_notification_not_sent_when_ai_fails(self):
        app = self.queue(native_pdf())

        def failing(a):
            a.ai_status = S.FAILED
            a.save()
            raise ValueError("llm down")

        pipeline, notif1 = self.run_worker(mock.MagicMock(side_effect=failing))
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.FAILED)
        notif1.assert_not_called()

    def test_extraction_crash_is_failed_not_reupload(self):
        app = self.queue(native_pdf())
        with mock.patch.object(
            orchestrator, "extract_document", side_effect=RuntimeError("bug")
        ):
            pipeline, notif1 = self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.FAILED)
        pipeline.assert_not_called()
        notif1.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    # 11. no duplicate processing
    def test_claim_is_taken_only_once(self):
        from ai_engine.management.commands.process_pending_applications \
            import Command
        app = self.queue(native_pdf())
        cmd = Command()
        first, has_doc = cmd._claim(app.id)
        second, _ = cmd._claim(app.id)
        self.assertIsNotNone(first)
        self.assertTrue(has_doc)
        self.assertEqual(first.ai_status, S.EXTRACTING)
        self.assertIsNone(second)

    def test_second_worker_pass_does_not_reprocess(self):
        self.queue(native_pdf())
        pipeline, _ = self.run_worker()
        pipeline.reset_mock()
        pipeline2, _ = self.run_worker()
        pipeline2.assert_not_called()

    # 12. legacy rows
    def test_legacy_queued_row_without_document_goes_to_pipeline(self):
        self.candidate.extracted_text = "Already extracted by the old flow."
        self.candidate.save()
        app = self.queue(b"", with_document=False)
        seen = []
        _, notif1 = self.run_worker(
            mock.MagicMock(side_effect=self.fake_pipeline(seen))
        )
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        self.assertEqual(seen, ["Already extracted by the old flow."])
        notif1.assert_called_once()

    # document-issue email
    def test_document_issue_email_is_sent_and_is_not_notification_one(self):
        self.queue(encrypted_pdf())
        self.run_worker()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ti@x.com"])
        self.assertIn("NOT been screened", message.body)
        self.assertIn("ICT Officer", message.subject)

    def test_email_failure_does_not_change_status(self):
        app = self.queue(encrypted_pdf())
        with mock.patch(f"{WORKER}.send_document_issue_email",
                        side_effect=RuntimeError("smtp down")):
            self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.DOCUMENT_INVALID)


class OrchestratorTests(TaskIBase):

    def _extract(self, data, **kw):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return orchestrator.extract_document(path, **kw)
        finally:
            os.remove(path)

    def test_mixed_pdf_reads_both_native_and_scanned_pages(self):
        outcome = self._extract(mixed_pdf())
        self.assertEqual(outcome.state, orchestrator.OK)
        self.assertEqual(outcome.report["method"], "mixed")
        methods = [p["method"] for p in outcome.report["pages"]]
        self.assertEqual(methods, ["native", "ocr"])
        self.assertIn("Maria da Silva", outcome.text)
        self.assertIn("certificate", outcome.text.lower())

    def test_blank_page_is_reported_blank_not_failed(self):
        outcome = self._extract(blank_page_pdf())
        self.assertEqual(outcome.state, orchestrator.OK)
        self.assertEqual(outcome.report["pages_blank"], [2])
        self.assertEqual(outcome.report["pages_failed"], [])
        self.assertTrue(outcome.report["complete"])

    def test_one_failed_page_fails_the_whole_extraction(self):
        from ai_engine.services import ocr_fallback
        real = ocr_fallback._ocr_one_page

        def flaky(path, page, dpi):
            if page == 2:
                raise RuntimeError("boom")
            return real(path, page, dpi)

        with mock.patch.object(ocr_fallback, "_ocr_one_page", flaky):
            outcome = self._extract(scanned_pdf(3))
        self.assertEqual(outcome.state, orchestrator.INSUFFICIENT)
        self.assertEqual(
            [f["page"] for f in outcome.report["pages_failed"]], [2]
        )
        self.assertFalse(outcome.report["complete"])

    def test_time_budget_exceeded_marks_pages_failed(self):
        outcome = self._extract(scanned_pdf(2), budget_seconds=-1)
        self.assertEqual(outcome.state, orchestrator.INSUFFICIENT)
        self.assertEqual(len(outcome.report["pages_failed"]), 2)

    def test_structure_check_never_raises(self):
        for data in (b"", b"%PDF-", b"garbage", encrypted_pdf()):
            result = check_pdf_structure(data)
            self.assertFalse(result.ok)
            self.assertTrue(result.reason)
        self.assertTrue(check_pdf_structure(native_pdf()).ok)

    def test_too_many_pages_is_invalid(self):
        from ai_engine.services.document_extraction import structure
        with mock.patch.object(structure, "MAX_PAGES", 1):
            result = check_pdf_structure(scanned_pdf(2))
        self.assertFalse(result.ok)


class ApplyJobWebTests(TaskIBase):

    def setUp(self):
        super().setUp()
        self.client.login(email="ti@x.com", password="pass12345")
        self.url = reverse("apply_job", kwargs={"job_id": self.job.id})

    def post(self, data, name="cv.pdf"):
        return self.client.post(
            self.url,
            {"full_name": "Maria da Silva", "email": "ti@x.com",
             "cv_file": SimpleUploadedFile(
                 name, data, content_type="application/pdf")},
            follow=True,
        )

    def test_request_queues_and_stores_pdf_without_extracting(self):
        with mock.patch.object(
            orchestrator, "extract_document"
        ) as extract, mock.patch(
            "ai_engine.services.document_extraction.router."
            "extract_scanned_document"
        ) as ocr:
            resp = self.post(scanned_pdf(2))
        self.assertEqual(resp.status_code, 200)
        extract.assert_not_called()
        ocr.assert_not_called()
        app = Application.objects.get(job=self.job)
        self.assertEqual(app.ai_status, S.QUEUED)
        self.assertTrue(app.pending_document.pdf_bytes)

    def test_corrupt_upload_rejected_with_nothing_queued(self):
        self.post(b"not a pdf at all")
        self.assertFalse(Application.objects.filter(job=self.job).exists())
        self.assertFalse(ApplicationDocument.objects.exists())

    def test_encrypted_upload_rejected_with_nothing_queued(self):
        self.post(encrypted_pdf())
        self.assertFalse(Application.objects.filter(job=self.job).exists())

    def test_reupload_after_failure_resets_same_application(self):
        app = Application.objects.create(
            candidate=self.candidate, job=self.job,
            ai_status=S.EXTRACTION_FAILED, ai_feedback="old reason",
        )
        resp = self.post(native_pdf())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Application.objects.filter(job=self.job).count(), 1
        )
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.QUEUED)
        self.assertTrue(app.pending_document.pdf_bytes)

    def test_reupload_then_worker_completes(self):
        Application.objects.create(
            candidate=self.candidate, job=self.job,
            ai_status=S.DOCUMENT_INVALID, ai_feedback="old reason",
        )
        self.post(native_pdf())
        pipeline, notif1 = self.run_worker()
        app = Application.objects.get(job=self.job)
        self.assertEqual(app.ai_status, S.SUCCESS)
        notif1.assert_called_once()

    def test_in_flight_or_successful_application_cannot_be_replaced(self):
        for status in (S.QUEUED, S.PROCESSING, S.SUCCESS):
            Application.objects.filter(job=self.job).delete()
            app = Application.objects.create(
                candidate=self.candidate, job=self.job, ai_status=status
            )
            self.post(native_pdf())
            app.refresh_from_db()
            self.assertEqual(app.ai_status, status)
            self.assertFalse(
                ApplicationDocument.objects.filter(application=app).exists()
            )

    def test_my_applications_shows_reupload_link(self):
        Application.objects.create(
            candidate=self.candidate, job=self.job,
            ai_status=S.EXTRACTION_FAILED, ai_feedback="Too little text.",
        )
        resp = self.client.get(reverse("my_applications"))
        self.assertContains(resp, "Upload a new CV")
        self.assertContains(resp, "Too little text.")


def hybrid_pdf(header=("Curriculum Vitae - Maria da Silva",)):
    """One page: a short typed header (text layer) over an embedded
    image that carries the real content."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in header:
        pdf.cell(text=line, new_x="LMARGIN", new_y="NEXT")
    img = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(img)
    y = 300
    for line in ["Scanned body: Diploma in Public Administration",
                 "Training: Leadership course completed in Seoul"]:
        draw.text((100, y), line, fill="black")
        y += 60
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "p.png")
        img.save(p)
        pdf.image(p, x=0, y=60, w=612, h=700)
        return bytes(pdf.output())


class LimitsAndCompletenessTests(TaskIBase):

    def _extract(self, data, **kw):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return orchestrator.extract_document(path, **kw)
        finally:
            os.remove(path)

    # 50-page limit, real boundary
    def test_50_pages_accepted_51_rejected(self):
        self.assertTrue(check_pdf_structure(self._digital_n(50)).ok)
        over = check_pdf_structure(self._digital_n(51))
        self.assertFalse(over.ok)
        self.assertIn("50-page", over.reason)
        self.assertEqual(over.page_count, 51)

    @staticmethod
    def _digital_n(n):
        from fpdf import FPDF
        pdf = FPDF(unit="pt", format="letter")
        pdf.set_font("helvetica", size=12)
        for i in range(n):
            pdf.add_page()
            pdf.cell(text=f"Page {i + 1} of a long CV for Maria da Silva",
                     new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    def test_50_page_native_document_extracts_every_page(self):
        outcome = self._extract(self._digital_n(50))
        self.assertEqual(outcome.state, orchestrator.OK)
        self.assertEqual(outcome.report["pages_total"], 50)
        self.assertEqual(len(outcome.report["pages"]), 50)
        self.assertIn("Page 50 of", outcome.text)

    def test_web_rejects_over_limit_before_storing(self):
        self.client.login(email="ti@x.com", password="pass12345")
        self.client.post(
            reverse("apply_job", kwargs={"job_id": self.job.id}),
            {"full_name": "Maria da Silva", "email": "ti@x.com",
             "cv_file": SimpleUploadedFile(
                 "cv.pdf", self._digital_n(51),
                 content_type="application/pdf")},
        )
        self.assertFalse(Application.objects.filter(job=self.job).exists())
        self.assertFalse(ApplicationDocument.objects.exists())

    # per-page OCR timeout, with the REAL tesseract
    def test_real_tesseract_timeout_is_recorded_per_page(self):
        from ai_engine.services import ocr_fallback
        with mock.patch.object(
            ocr_fallback, "PAGE_OCR_TIMEOUT_SECONDS", 0.001
        ):
            outcome = self._extract(scanned_pdf(2))
        self.assertEqual(outcome.state, orchestrator.INSUFFICIENT)
        failed = outcome.report["pages_failed"]
        self.assertEqual([f["page"] for f in failed], [1, 2])
        self.assertIn("timeout", failed[0]["error"].lower())

    def test_budget_is_checked_between_pages(self):
        # Budget already spent: no page starts, all reported failed
        # (never silently dropped).
        outcome = self._extract(scanned_pdf(3), budget_seconds=-1)
        self.assertEqual(len(outcome.report["pages_failed"]), 3)
        self.assertIn(
            "budget", outcome.report["pages_failed"][0]["error"].lower()
        )

    # image content on a page that also has a short text layer
    def test_hybrid_page_image_content_is_not_lost(self):
        outcome = self._extract(hybrid_pdf())
        self.assertEqual(outcome.state, orchestrator.OK)
        self.assertEqual(outcome.report["pages_supplemental_ocr"], [1])
        self.assertIn("Maria da Silva", outcome.text)
        self.assertIn("Diploma", outcome.text)

    def test_supplemental_ocr_failure_keeps_native_text_with_warning(self):
        from ai_engine.services import ocr_fallback
        with mock.patch.object(
            ocr_fallback, "_ocr_one_page", side_effect=RuntimeError("x")
        ):
            outcome = self._extract(hybrid_pdf(header=(
                "Maria da Silva, ICT officer, Dili, Timor-Leste",
                "Bachelor of Information Technology, five years",
            )))
        self.assertEqual(outcome.state, orchestrator.OK)
        self.assertIn("Maria da Silva", outcome.text)
        self.assertTrue(any("embedded image" in w
                            for w in outcome.report["warnings"]))
        self.assertEqual(outcome.report["pages_failed"], [])

    def test_plain_native_page_is_not_ocrd(self):
        with mock.patch(
            "ai_engine.services.document_extraction.orchestrator."
            "ocr_pdf_pages"
        ) as ocr:
            outcome = self._extract(native_pdf())
        ocr.assert_not_called()
        self.assertEqual(outcome.report["pages_supplemental_ocr"], [])

    # report explains the outcome
    def test_report_fields_explain_the_result(self):
        outcome = self._extract(mixed_pdf())
        r = outcome.report
        for key in ("pages_total", "method", "provider", "pages",
                    "pages_failed", "pages_unreadable", "pages_blank",
                    "chars", "quality", "complete", "warnings",
                    "seconds"):
            self.assertIn(key, r)
        self.assertEqual(r["pages_total"], 2)
        self.assertEqual(r["quality"], "OK")
        for page in r["pages"]:
            self.assertNotIn("text", page)

    def test_failure_report_is_stored_with_reason(self):
        app = self.queue(scanned_pdf(2))
        from ai_engine.services import ocr_fallback
        with mock.patch.object(
            ocr_fallback, "_ocr_one_page", side_effect=RuntimeError("boom")
        ):
            self.run_worker()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.EXTRACTION_FAILED)
        self.assertFalse(app.extraction_report["complete"])
        self.assertEqual(len(app.extraction_report["pages_failed"]), 2)
        self.assertIn("page", app.ai_feedback.lower())
        self.assertIn("boom", app.ai_error)


class RobustnessTests(TaskIBase):

    def test_orphaned_documents_are_removed_at_startup(self):
        done = self.queue(native_pdf())
        Application.objects.filter(id=done.id).update(ai_status=S.SUCCESS)
        other_user = User.objects.create_user(
            username="t2", password="pass12345", email="t2@x.com",
            first_name="Other", role=self.user.role, is_verified=True,
        )
        cand2 = Candidate.objects.create(
            user=other_user, full_name="Other", email="t2@x.com"
        )
        waiting = Application.objects.create(
            candidate=cand2, job=self.job, ai_status=S.QUEUED
        )
        ApplicationDocument.objects.create(
            application=waiting, pdf_bytes=native_pdf()
        )
        from ai_engine.management.commands.process_pending_applications \
            import Command
        Command()._remove_orphan_documents()
        self.assertFalse(
            ApplicationDocument.objects.filter(application=done).exists()
        )
        self.assertTrue(
            ApplicationDocument.objects.filter(application=waiting).exists()
        )

    def test_concurrent_duplicate_create_is_handled_not_500(self):
        from django.db import IntegrityError
        self.client.login(email="ti@x.com", password="pass12345")
        with mock.patch(
            "talent.views.Application.objects.create",
            side_effect=IntegrityError("duplicate")
        ):
            resp = self.client.post(
                reverse("apply_job", kwargs={"job_id": self.job.id}),
                {"full_name": "Maria da Silva", "email": "ti@x.com",
                 "cv_file": SimpleUploadedFile(
                     "cv.pdf", native_pdf(),
                     content_type="application/pdf")},
                follow=True,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already applied")

    def test_sqlite_lock_from_concurrent_submit_is_handled_not_500(self):
        """SQLite (local dev) raises OperationalError for the second of
        two simultaneous submits. If the other request's application
        exists, the user sees 'already applied', not a 500."""
        from django.db import OperationalError
        self.client.login(email="ti@x.com", password="pass12345")

        def other_request_commits(seconds):
            # runs in the retry wait, i.e. AFTER our transaction was
            # rolled back: the other request's commit lands now.
            Application.objects.get_or_create(
                candidate=self.candidate, job=self.job,
                defaults={"ai_status": S.QUEUED},
            )

        with mock.patch(
            "talent.views.ApplicationDocument.objects.update_or_create",
            side_effect=OperationalError("database is locked")
        ), mock.patch(
            "talent.views.time.sleep", side_effect=other_request_commits
        ):
            resp = self.client.post(
                reverse("apply_job", kwargs={"job_id": self.job.id}),
                {"full_name": "Maria da Silva", "email": "ti@x.com",
                 "cv_file": SimpleUploadedFile(
                     "cv.pdf", native_pdf(),
                     content_type="application/pdf")},
                follow=True,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already applied")

    def test_other_database_errors_are_not_hidden(self):
        from django.db import OperationalError
        self.client.login(email="ti@x.com", password="pass12345")
        self.client.raise_request_exception = False
        with mock.patch(
            "talent.views.ApplicationDocument.objects.update_or_create",
            side_effect=OperationalError("disk I/O error")
        ), mock.patch("talent.views.time.sleep"):
            resp = self.client.post(
                reverse("apply_job", kwargs={"job_id": self.job.id}),
                {"full_name": "Maria da Silva", "email": "ti@x.com",
                 "cv_file": SimpleUploadedFile(
                     "cv.pdf", native_pdf(),
                     content_type="application/pdf")},
            )
        self.assertEqual(resp.status_code, 500)


class WorkerDatabaseErrorTests(TaskIBase):

    class _StopLoop(Exception):
        pass

    def _run_loop_with_first_pass_failing(self):
        from ai_engine.management.commands.process_pending_applications \
            import Command
        from django.db import OperationalError

        original = Command._process_one_pass
        calls = {"n": 0}
        stop = self._StopLoop

        def flaky(command):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("database is locked")
            original(command)
            raise stop()

        pipeline = mock.MagicMock(side_effect=self.fake_pipeline())
        with mock.patch.object(Command, "_process_one_pass", flaky), \
                mock.patch(f"{WORKER}.time.sleep"), \
                mock.patch(f"{WORKER}.recruitment_pipeline", pipeline), \
                mock.patch(f"{WORKER}.send_ai_screening_completed_email"):
            with self.assertRaises(stop):
                call_command("process_pending_applications", loop=True,
                             interval=0.01, stdout=StringIO())
        return calls["n"]

    def test_loop_survives_a_transient_database_error(self):
        app = self.queue(native_pdf())
        self._run_loop_with_first_pass_failing()
        app.refresh_from_db()
        # the worker did not die: it retried and finished the application
        self.assertEqual(app.ai_status, S.SUCCESS)

    def test_row_left_in_flight_by_a_database_error_is_recovered(self):
        app = self.queue(native_pdf())
        Application.objects.filter(id=app.id).update(
            ai_status=S.EXTRACTING
        )
        self._run_loop_with_first_pass_failing()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)

    def test_single_pass_mode_still_raises_database_errors(self):
        from django.db import OperationalError
        from ai_engine.management.commands.process_pending_applications \
            import Command
        with mock.patch.object(
            Command, "_process_one_pass",
            side_effect=OperationalError("database is locked")
        ):
            with self.assertRaises(OperationalError):
                call_command("process_pending_applications",
                             stdout=StringIO())


class MyApplicationsProgressTests(TaskIBase):

    def test_each_live_status_has_its_own_label_and_autorefresh(self):
        self.client.login(email="ti@x.com", password="pass12345")
        app = Application.objects.create(
            candidate=self.candidate, job=self.job, ai_status=S.QUEUED
        )
        for status in (S.QUEUED, S.EXTRACTING, S.EXTRACTED, S.PROCESSING):
            Application.objects.filter(id=app.id).update(ai_status=status)
            resp = self.client.get(reverse("my_applications"))
            self.assertContains(resp, S.DISPLAY[status])
            self.assertContains(resp, "location.reload")

    def test_finished_application_does_not_autorefresh(self):
        self.client.login(email="ti@x.com", password="pass12345")
        Application.objects.create(
            candidate=self.candidate, job=self.job, ai_status=S.SUCCESS
        )
        resp = self.client.get(reverse("my_applications"))
        self.assertNotContains(resp, "location.reload")


class EmailDetailLinkTests(TaskIBase):
    """Every candidate email carries a link to /ranking/<application id>/."""

    def setUp(self):
        super().setUp()
        self.app = Application.objects.create(
            candidate=self.candidate, job=self.job, ai_status=S.SUCCESS,
            ai_decision="Recommended", ai_feedback="Good fit.",
            status="accepted",
        )
        self.path = reverse("candidate_detail", args=[self.app.id])

    def test_path_is_ranking_application_id(self):
        self.assertEqual(self.path, f"/ranking/{self.app.id}/")

    def test_notification_one_has_the_link(self):
        from talent.notifications import send_ai_screening_completed_email
        send_ai_screening_completed_email(self.app)
        self.assertIn(
            f"http://127.0.0.1:8000/ranking/{self.app.id}/",
            mail.outbox[0].body,
        )

    def test_notification_two_has_the_link(self):
        from talent.views import _send_candidate_outcome_email
        _send_candidate_outcome_email(self.app, agreed_with_ai=True)
        self.assertIn(
            f"http://127.0.0.1:8000/ranking/{self.app.id}/",
            mail.outbox[0].body,
        )

    def test_document_issue_email_has_the_link(self):
        from talent.notifications import send_document_issue_email
        send_document_issue_email(self.app)
        self.assertIn(
            f"http://127.0.0.1:8000/ranking/{self.app.id}/",
            mail.outbox[0].body,
        )

    def test_link_uses_site_url_setting(self):
        from django.test import override_settings
        from talent.notifications import send_ai_screening_completed_email
        with override_settings(SITE_URL="https://cv.example.org"):
            send_ai_screening_completed_email(self.app)
        self.assertIn(
            f"https://cv.example.org/ranking/{self.app.id}/",
            mail.outbox[0].body,
        )

    def test_owner_can_open_the_link_but_others_cannot(self):
        self.client.login(email="ti@x.com", password="pass12345")
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.client.logout()

        User.objects.create_user(
            username="other", password="pass12345", email="o@x.com",
            first_name="Other", role=_make_role("Candidate"),
            is_verified=True,
        )
        self.client.login(email="o@x.com", password="pass12345")
        self.assertEqual(self.client.get(self.path).status_code, 403)

    def test_worker_sends_notification_one_with_link(self):
        self.app.delete()
        app = self.queue(native_pdf())
        with mock.patch(f"{WORKER}.recruitment_pipeline",
                        side_effect=self.fake_pipeline()):
            call_command("process_pending_applications", stdout=StringIO())
        bodies = [m.body for m in mail.outbox]
        self.assertTrue(any(
            f"/ranking/{app.id}/" in b for b in bodies
        ))