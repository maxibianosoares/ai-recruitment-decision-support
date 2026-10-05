from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User, Role, Permission
from .models import Job, Candidate, Application


def _make_role(name, permission_codes=None):

    role, _ = Role.objects.get_or_create(name=name)

    for code in (permission_codes or []):
        perm, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code}
        )
        role.permissions.add(perm)

    return role


def _native_pdf_bytes():
    # Minimal valid-enough PDF for pypdf to open without raising --
    # native extraction may yield little/no text, which is fine for
    # these access/ownership tests (they don't assert on AI results).
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(
        0, 8,
        "Test Candidate\nBachelor of IT\n3 years experience\nSkills: Testing",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    return bytes(pdf.output(dest="S"))


class CandidateAccessTests(TestCase):

    def setUp(self):

        self.candidate_role = _make_role("Candidate")

        self.hr_role = _make_role("HR Officer", ["recruitment_manage"])

        self.job = Job.objects.create(
            title="Test Job", department="ICT",
            description="x", requirements="x",
            ai_job_profile={
                "job_title": "Test Job", "education": "Bachelor",
                "years_experience": 0, "languages": [],
                "certifications": [], "skills": []
            },
            ai_processed=True
        )

        self.candidate_a = User.objects.create_user(
            username="candA", password="pass12345", email="a@x.com",
            role=self.candidate_role, is_verified=True
        )

        self.candidate_b = User.objects.create_user(
            username="candB", password="pass12345", email="b@x.com",
            role=self.candidate_role, is_verified=True
        )

    def test_apply_job_requires_login(self):

        resp = self.client.get(
            reverse("apply_job", kwargs={"job_id": self.job.id})
        )

        # login_required redirects anonymous users to the login page
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_candidate_can_view_own_application(self):

        candidate_profile = Candidate.objects.create(
            user=self.candidate_a, full_name="A", email="a-cv@x.com"
        )

        application = Application.objects.create(
            candidate=candidate_profile, job=self.job
        )

        self.client.login(email="a@x.com", password="pass12345")

        resp = self.client.get(
            reverse("candidate_detail", kwargs={"application_id": application.id})
        )

        self.assertEqual(resp.status_code, 200)

    def test_candidate_cannot_view_other_candidates_application(self):

        candidate_profile_a = Candidate.objects.create(
            user=self.candidate_a, full_name="A", email="a-cv2@x.com"
        )

        application = Application.objects.create(
            candidate=candidate_profile_a, job=self.job
        )

        # Candidate B tries to view Candidate A's application
        self.client.login(email="b@x.com", password="pass12345")

        resp = self.client.get(
            reverse("candidate_detail", kwargs={"application_id": application.id})
        )

        self.assertEqual(resp.status_code, 403)

    def test_candidate_cannot_submit_human_review_on_own_application(self):

        candidate_profile = Candidate.objects.create(
            user=self.candidate_a, full_name="A", email="a-cv3@x.com"
        )

        application = Application.objects.create(
            candidate=candidate_profile, job=self.job
        )

        self.client.login(email="a@x.com", password="pass12345")

        resp = self.client.post(
            reverse("candidate_detail", kwargs={"application_id": application.id}),
            {"form_type": "human_decision", "decision": "approved", "reason": "self-approving"}
        )

        self.assertEqual(resp.status_code, 403)

    def test_hr_can_view_any_application(self):

        candidate_profile = Candidate.objects.create(
            user=self.candidate_a, full_name="A", email="a-cv4@x.com"
        )

        application = Application.objects.create(
            candidate=candidate_profile, job=self.job
        )

        hr_user = User.objects.create_user(
            username="hr_view", password="pass12345", email="hrv@x.com",
            role=self.hr_role, is_verified=True
        )

        self.client.login(email="hrv@x.com", password="pass12345")

        resp = self.client.get(
            reverse("candidate_detail", kwargs={"application_id": application.id})
        )

        self.assertEqual(resp.status_code, 200)


class SelfApplicationTests(TestCase):

    def setUp(self):

        self.candidate_role = _make_role("Candidate")

        self.job = Job.objects.create(
            title="ICT Officer", department="ICT",
            description="x", requirements="x",
            ai_job_profile={
                "job_title": "ICT Officer", "education": "Bachelor",
                "years_experience": 0, "languages": [],
                "certifications": [], "skills": []
            },
            ai_processed=True,
            ai_rag_context={
                "evidence": [], "best_evidence_score": 0,
                "grounded": False, "error": None
            }
        )

        self.user = User.objects.create_user(
            username="applicant1", password="pass12345",
            email="applicant1@x.com", first_name="Applicant One",
            role=self.candidate_role, is_verified=True
        )

    def test_candidate_can_self_apply_and_owns_result(self):

        self.client.login(email="applicant1@x.com", password="pass12345")

        cv = SimpleUploadedFile(
            "cv.pdf", _native_pdf_bytes(), content_type="application/pdf"
        )

        resp = self.client.post(
            reverse("apply_job", kwargs={"job_id": self.job.id}),
            {"full_name": "Applicant One", "email": "applicant1@x.com", "cv_file": cv},
            follow=True
        )

        self.assertEqual(resp.status_code, 200)

        candidate = Candidate.objects.get(user=self.user)

        self.assertTrue(
            Application.objects.filter(candidate=candidate, job=self.job).exists()
        )

    def test_duplicate_application_blocked(self):

        candidate = Candidate.objects.create(
            user=self.user, full_name="Applicant One",
            email="applicant1@x.com"
        )

        Application.objects.create(candidate=candidate, job=self.job)

        self.client.login(email="applicant1@x.com", password="pass12345")

        resp = self.client.get(
            reverse("apply_job", kwargs={"job_id": self.job.id}), follow=True
        )

        self.assertContains(resp, "already applied")

        self.assertEqual(
            Application.objects.filter(candidate=candidate, job=self.job).count(),
            1
        )


class AsyncApplyJobTests(TestCase):
    """
    FINAL FINISHING SESSION (2026-10-04) -- Section O "Async
    application" tests. Uses mock.patch on recruitment_pipeline so
    these tests assert the ARCHITECTURE (does the HTTP request run
    the expensive pipeline synchronously, does the worker pick up
    QUEUED rows) without needing a real reachable LLM.
    """

    def setUp(self):

        self.candidate_role = _make_role("Candidate")

        self.job = Job.objects.create(
            title="ICT Officer", department="ICT",
            description="x", requirements="x",
            ai_job_profile={
                "job_title": "ICT Officer", "education": "Bachelor",
                "years_experience": 0, "languages": [],
                "certifications": [], "skills": []
            },
            ai_processed=True,
            ai_rag_context={
                "evidence": [], "best_evidence_score": 0,
                "grounded": False, "error": None
            }
        )

        self.user = User.objects.create_user(
            username="asyncapplicant", password="pass12345",
            email="asyncapplicant@x.com", first_name="Async Applicant",
            role=self.candidate_role, is_verified=True
        )

    def test_valid_submission_is_queued_without_running_ai_pipeline(self):

        from unittest import mock

        self.client.login(email="asyncapplicant@x.com", password="pass12345")

        cv = SimpleUploadedFile(
            "cv.pdf", _native_pdf_bytes(), content_type="application/pdf"
        )

        with mock.patch(
            "talent.views.recruitment_pipeline"
        ) as mocked_pipeline:

            resp = self.client.post(
                reverse("apply_job", kwargs={"job_id": self.job.id}),
                {
                    "full_name": "Async Applicant",
                    "email": "asyncapplicant@x.com",
                    "cv_file": cv
                },
                follow=True
            )

            self.assertEqual(resp.status_code, 200)

            # THE core architectural assertion: the HTTP request must
            # NOT have called the expensive AI pipeline synchronously.
            mocked_pipeline.assert_not_called()

        application = Application.objects.get(
            candidate__user=self.user, job=self.job
        )

        self.assertEqual(application.ai_status, "QUEUED")

    def test_worker_processes_queued_application_to_completion(self):

        from unittest import mock
        from io import StringIO
        from django.core.management import call_command

        candidate = Candidate.objects.create(
            user=self.user, full_name="Async Applicant",
            email="asyncapplicant@x.com"
        )

        application = Application.objects.create(
            candidate=candidate, job=self.job, ai_status="QUEUED"
        )

        def _fake_pipeline(app):
            app.ai_status = "SUCCESS"
            app.ai_score = 77
            app.ai_decision = "Recommended"
            app.save()
            return app

        with mock.patch(
            "ai_engine.management.commands."
            "process_pending_applications.recruitment_pipeline",
            side_effect=_fake_pipeline
        ):
            call_command("process_pending_applications", stdout=StringIO())

        application.refresh_from_db()

        self.assertEqual(application.ai_status, "SUCCESS")
        self.assertEqual(application.ai_score, 77)

    def test_worker_marks_failed_application_without_fake_success(self):

        from unittest import mock
        from io import StringIO
        from django.core.management import call_command

        candidate = Candidate.objects.create(
            user=self.user, full_name="Async Applicant",
            email="asyncapplicant@x.com"
        )

        application = Application.objects.create(
            candidate=candidate, job=self.job, ai_status="QUEUED"
        )

        def _fake_failing_pipeline(app):
            app.ai_status = "FAILED"
            app.ai_feedback = (
                "AI recommendation reasoning could not be generated: "
                "Reasoning unavailable: Empty response from Ollama."
            )
            app.save()
            raise ValueError(app.ai_feedback)

        with mock.patch(
            "ai_engine.management.commands."
            "process_pending_applications.recruitment_pipeline",
            side_effect=_fake_failing_pipeline
        ):
            call_command("process_pending_applications", stdout=StringIO())

        application.refresh_from_db()

        self.assertEqual(application.ai_status, "FAILED")
        # Never a fake deterministic decision on failure.
        self.assertEqual(application.ai_score, 0)
        self.assertNotEqual(application.ai_decision, "Not Recommended")

    def test_ai_completed_triggers_first_notification_email(self):
        """
        Notification #1 (Section 17): sent once the worker completes
        AI screening successfully -- distinct from Notification #2
        (final human decision), which has its own existing test
        coverage via candidate_detail's human_decision POST path.
        """

        from unittest import mock
        from io import StringIO
        from django.core import mail
        from django.core.management import call_command

        candidate = Candidate.objects.create(
            user=self.user, full_name="Async Applicant",
            email="asyncapplicant@x.com"
        )

        application = Application.objects.create(
            candidate=candidate, job=self.job, ai_status="QUEUED"
        )

        def _fake_pipeline(app):
            app.ai_status = "SUCCESS"
            app.ai_score = 88
            app.ai_decision = "Recommended"
            app.ai_feedback = "Strong match on technical skills."
            app.save()
            return app

        with mock.patch(
            "ai_engine.management.commands."
            "process_pending_applications.recruitment_pipeline",
            side_effect=_fake_pipeline
        ):
            call_command("process_pending_applications", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1)

        sent = mail.outbox[0]

        self.assertIn("asyncapplicant@x.com", sent.to)
        self.assertIn("AI screening", sent.subject)
        self.assertIn("not a final recruitment decision", sent.body)

    def test_email_failure_does_not_change_ai_status(self):
        """
        Section 24: a notification email failure must never roll
        back or corrupt the AI processing outcome.
        """

        from unittest import mock
        from io import StringIO
        from django.core.management import call_command

        candidate = Candidate.objects.create(
            user=self.user, full_name="Async Applicant",
            email="asyncapplicant@x.com"
        )

        application = Application.objects.create(
            candidate=candidate, job=self.job, ai_status="QUEUED"
        )

        def _fake_pipeline(app):
            app.ai_status = "SUCCESS"
            app.ai_score = 88
            app.ai_decision = "Recommended"
            app.save()
            return app

        with mock.patch(
            "ai_engine.management.commands."
            "process_pending_applications.recruitment_pipeline",
            side_effect=_fake_pipeline
        ), mock.patch(
            "ai_engine.management.commands."
            "process_pending_applications.send_ai_screening_completed_email",
            side_effect=RuntimeError("Brevo unreachable")
        ):
            call_command("process_pending_applications", stdout=StringIO())

        application.refresh_from_db()

        self.assertEqual(application.ai_status, "SUCCESS")
        self.assertEqual(application.ai_score, 88)

    def test_candidate_ownership_preserved_for_queued_application(self):

        other_user = User.objects.create_user(
            username="otherasync", password="pass12345",
            email="otherasync@x.com", first_name="Other",
            role=self.candidate_role, is_verified=True
        )

        candidate = Candidate.objects.create(
            user=self.user, full_name="Async Applicant",
            email="asyncapplicant@x.com"
        )

        application = Application.objects.create(
            candidate=candidate, job=self.job, ai_status="QUEUED"
        )

        self.client.login(email="otherasync@x.com", password="pass12345")

        resp = self.client.get(
            reverse("candidate_detail", kwargs={"application_id": application.id})
        )

        self.assertEqual(resp.status_code, 403)


class DocumentQualityGateTests(TestCase):
    """
    FINAL FINISHING SESSION (2026-10-04) -- Section O "Document
    quality" tests, against the real check_document_quality()
    wrapper (talent/document_quality.py), which itself calls the real
    extract_text_from_pdf() -- no mocking of extraction/OCR, per
    "Use the existing native text extraction and OCR pipeline".
    """

    def test_valid_text_pdf_is_accepted(self):

        import tempfile

        from .document_quality import check_document_quality

        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(_native_pdf_bytes())
            f.flush()

            result = check_document_quality(f.name)

        self.assertTrue(result.valid)
        self.assertEqual(result.extraction_method, "native")
        self.assertFalse(result.ocr_used)
        self.assertGreater(result.extracted_text_length, 0)

    def test_corrupted_file_is_rejected(self):

        import tempfile

        from .document_quality import check_document_quality

        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"this is not a real pdf file at all")
            f.flush()

            result = check_document_quality(f.name)

        self.assertFalse(result.valid)
        self.assertIn("could not be read", result.reason.lower())

    def test_empty_file_is_rejected(self):

        import os
        import tempfile

        from .document_quality import check_document_quality

        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            # Zero bytes -- not even a valid PDF header. Close the
            # handle immediately (nothing to write) so the file is
            # not still open when check_document_quality reads it.
            os.close(fd)

            result = check_document_quality(path)
        finally:
            os.remove(path)

        self.assertFalse(result.valid)

    def test_invalid_document_does_not_create_application(self):

        candidate_role = _make_role("Candidate")

        job = Job.objects.create(
            title="ICT Officer", department="ICT",
            description="x", requirements="x",
            ai_job_profile={"job_title": "ICT Officer"},
        )

        user = User.objects.create_user(
            username="baddocuser", password="pass12345",
            email="baddocuser@x.com", first_name="Bad Doc",
            role=candidate_role, is_verified=True
        )

        self.client.login(email="baddocuser@x.com", password="pass12345")

        bad_file = SimpleUploadedFile(
            "cv.pdf", b"not a real pdf", content_type="application/pdf"
        )

        resp = self.client.post(
            reverse("apply_job", kwargs={"job_id": job.id}),
            {
                "full_name": "Bad Doc",
                "email": "baddocuser@x.com",
                "cv_file": bad_file
            },
            follow=True
        )

        self.assertEqual(resp.status_code, 200)

        # DOCUMENT_INVALID: no Application row created at all, and no
        # Candidate row left behind either -- candidate can resubmit.
        self.assertFalse(
            Application.objects.filter(
                candidate__user=user, job=job
            ).exists()
        )
        self.assertFalse(
            Candidate.objects.filter(user=user).exists()
        )

    def test_valid_text_pdf_is_accepted(self):

        import os
        import tempfile

        from .document_quality import check_document_quality

        # NOTE (2026-10-05): a tempfile.NamedTemporaryFile left open
        # (the `with ... as f:` pattern used here before) cannot be
        # re-opened by a second reader (PdfReader, inside
        # check_document_quality) on Windows -- the OS keeps an
        # exclusive lock on it until the original handle is closed.
        # That is a Windows-only test artifact, not a real bug in
        # document_quality.py/utils.py/views.py: production code
        # always reads an already-saved, already-closed media file
        # (candidate.cv_file.path), never a still-open handle. Using
        # mkstemp + closing the handle before calling
        # check_document_quality avoids the false failure on Windows
        # while still exercising the exact same real extraction code
        # path on every OS.
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(_native_pdf_bytes())

            result = check_document_quality(path)
        finally:
            os.remove(path)

        self.assertTrue(result.valid)
        self.assertEqual(result.extraction_method, "native")
        self.assertFalse(result.ocr_used)
        self.assertGreater(result.extracted_text_length, 0)

    def test_corrupted_file_is_rejected(self):

        import os
        import tempfile

        from .document_quality import check_document_quality

        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(b"this is not a real pdf file at all")

            result = check_document_quality(path)
        finally:
            os.remove(path)

        self.assertFalse(result.valid)
        self.assertIn("could not be read", result.reason.lower())


class HumanDecisionLockTests(TestCase):
    """
    LOCKED FINAL DECISION (2026-10-05) -- once an administrator has
    recorded a Human Review decision for an application, a second
    decision POST must be rejected by candidate_detail() before it
    ever reaches HumanDecision.objects.update_or_create(). This
    prevents Notification #2 (the final-decision email) from being
    sent a second time with a different outcome for the same
    application.
    """

    def setUp(self):

        self.admin_role = _make_role(
            "Administrator", ["recruitment_manage"]
        )

        self.candidate_role = _make_role("Candidate")

        self.job = Job.objects.create(
            title="Test Job", department="ICT",
            description="x", requirements="x",
            ai_job_profile={
                "job_title": "Test Job", "education": "Bachelor",
                "years_experience": 0, "languages": [],
                "certifications": [], "skills": []
            },
            ai_processed=True
        )

        self.admin_user = User.objects.create_user(
            username="admin_lock", password="pass12345",
            email="admin_lock@x.com", role=self.admin_role,
            is_verified=True
        )

        candidate_user = User.objects.create_user(
            username="cand_lock", password="pass12345",
            email="cand_lock@x.com", role=self.candidate_role,
            is_verified=True
        )

        self.candidate = Candidate.objects.create(
            user=candidate_user, full_name="Lock Test Candidate",
            email="cand_lock@x.com"
        )

        self.application = Application.objects.create(
            candidate=self.candidate, job=self.job,
            ai_status="SUCCESS", ai_decision="Recommended"
        )

    def _post_decision(self, decision, reason):

        return self.client.post(
            reverse(
                "candidate_detail",
                kwargs={"application_id": self.application.id}
            ),
            {
                "form_type": "human_decision",
                "decision": decision,
                "reason": reason
            }
        )

    def test_first_final_decision_succeeds(self):

        from .models import HumanDecision

        self.client.login(email="admin_lock@x.com", password="pass12345")

        resp = self._post_decision("approved", "Meets all requirements")

        self.assertEqual(resp.status_code, 302)

        self.application.refresh_from_db()

        self.assertEqual(self.application.status, "accepted")
        self.assertTrue(
            HumanDecision.objects.filter(
                application=self.application, decision="approved"
            ).exists()
        )

    def test_second_decision_post_is_rejected_and_does_not_overwrite(self):

        from django.core import mail
        from .models import HumanDecision

        self.client.login(email="admin_lock@x.com", password="pass12345")

        # First (legitimate) decision -- also sends Notification #2.
        self._post_decision("approved", "Meets all requirements")

        self.application.refresh_from_db()

        self.assertEqual(len(mail.outbox), 1)

        # Second POST for the SAME application, attempting to flip
        # the outcome.
        resp = self._post_decision("rejected", "Changed my mind")

        self.assertEqual(resp.status_code, 302)

        self.application.refresh_from_db()

        human_decision = HumanDecision.objects.get(
            application=self.application
        )

        # Existing decision untouched.
        self.assertEqual(human_decision.decision, "approved")
        self.assertEqual(human_decision.reason, "Meets all requirements")

        # Application final status untouched.
        self.assertEqual(self.application.status, "accepted")

        # Notification #2 was NOT sent again by the rejected second
        # POST.
        self.assertEqual(len(mail.outbox), 1)

    def test_candidate_cannot_submit_human_review_before_or_after_lock(self):

        candidate_login_user = self.candidate.user

        self.client.login(
            email="cand_lock@x.com", password="pass12345"
        )

        resp = self._post_decision("approved", "self-approving")

        # Still blocked by the existing administrator-only check,
        # before the lock check is ever reached -- confirms the lock
        # does not weaken existing authorization.
        self.assertEqual(resp.status_code, 403)

        
    def test_outcome_email_shows_ai_feedback_when_decision_agrees(self):
        """
        FEEDBACK/OUTCOME CONSISTENCY FIX (2026-10-05): when the final
        decision AGREES with the AI recommendation, the existing
        behavior is unchanged -- application.ai_feedback is still
        shown as "Feedback:" in Notification #2.
        """

        from django.core import mail

        self.application.ai_decision = "Recommended"
        self.application.ai_feedback = (
            "Strong match on technical skills."
        )
        self.application.save()

        self.client.login(email="admin_lock@x.com", password="pass12345")

        self._post_decision("approved", "Meets all requirements")

        self.assertEqual(len(mail.outbox), 1)

        sent = mail.outbox[0]

        self.assertIn("has been accepted", sent.body)
        self.assertIn("Feedback:", sent.body)
        self.assertIn("Strong match on technical skills.", sent.body)

    def test_outcome_email_hides_ai_feedback_when_decision_overrides(self):
        """
        FEEDBACK/OUTCOME CONSISTENCY FIX (2026-10-05): when the final
        decision OVERRIDES the AI recommendation (e.g. AI said "Not
        Recommended" but the administrator approves the candidate
        anyway), application.ai_feedback must NOT appear in
        Notification #2 -- showing the AI's contradictory text next
        to the opposite outcome previously confused candidates (real
        example: an email saying "has been accepted" while still
        showing the AI's "Do not proceed with this candidate..."
        text). A neutral line is shown instead, and the recruiter's
        actual reason (HumanDecision.reason) stays internal-only, as
        before.
        """

        from django.core import mail

        self.application.ai_decision = "Not Recommended"
        self.application.ai_feedback = (
            "Do not proceed with this candidate for the Junior Web "
            "Developer position; consider them for ICT Support or "
            "System Administration roles instead."
        )
        self.application.save()

        self.client.login(email="admin_lock@x.com", password="pass12345")

        # Administrator overrides the AI's "Not Recommended" by
        # approving the candidate.
        self._post_decision("approved", "Strong interview, hire anyway")

        self.assertEqual(len(mail.outbox), 1)

        sent = mail.outbox[0]

        self.assertIn("has been accepted", sent.body)
        self.assertNotIn("Do not proceed with this candidate", sent.body)
        self.assertNotIn("Feedback:", sent.body)
        self.assertIn(
            "final decision of an authorized human recruitment "
            "officer",
            sent.body
        )

        # The recruiter's internal reason is never leaked to the
        # candidate email.
        self.assertNotIn("Strong interview, hire anyway", sent.body)