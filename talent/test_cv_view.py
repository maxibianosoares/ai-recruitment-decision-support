"""Opening the CV of an application from the candidate page."""

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
import shutil
import tempfile

from accounts.models import User
from talent.models import Application, ApplicationCvFile, Candidate, Job
from django.core.files.uploadedfile import SimpleUploadedFile
from talent.tests import _make_role, _native_pdf_bytes

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class CvViewTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cand_role = _make_role("Candidate")
        hr_role = _make_role("HR Officer", ["recruitment_manage"])
        self.job = Job.objects.create(
            title="J", department="ICT", description="x", requirements="x",
            ai_job_profile={}, ai_processed=True)
        self.owner = User.objects.create_user(
            username="own", password="pass12345", email="own@x.com",
            role=cand_role, is_verified=True)
        self.other = User.objects.create_user(
            username="oth", password="pass12345", email="oth@x.com",
            role=cand_role, is_verified=True)
        self.hr = User.objects.create_user(
            username="hr", password="pass12345", email="hr@x.com",
            role=hr_role, is_verified=True)
        self.profile = Candidate.objects.create(
            user=self.owner, full_name="O", email="o-cv@x.com")
        self.app = Application.objects.create(candidate=self.profile, job=self.job)
        self.url = reverse("application_cv_file", args=[self.app.id])

    def login(self, email):
        self.client.login(email=email, password="pass12345")

    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r.url)

    def test_owner_and_staff_open_the_saved_copy_inline(self):
        ApplicationCvFile.objects.create(
            application=self.app, pdf_bytes=PDF, original_name="my cv.pdf")
        for email in ("own@x.com", "hr@x.com"):
            self.client.logout(); self.login(email)
            r = self.client.get(self.url)
            self.assertEqual(r.status_code, 200, email)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r["Content-Disposition"].startswith("inline"))
            self.assertEqual(r["X-Content-Type-Options"], "nosniff")
            self.assertEqual(r.content, PDF)

    def test_another_candidate_is_refused(self):
        ApplicationCvFile.objects.create(
            application=self.app, pdf_bytes=PDF, original_name="cv.pdf")
        self.login("oth@x.com")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_older_application_falls_back_to_the_candidate_file(self):
        self.profile.cv_file.save("old.pdf", ContentFile(PDF))
        self.login("hr@x.com")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PDF)

    def test_no_file_anywhere_gives_a_clear_404(self):
        self.login("hr@x.com")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)
        self.assertIn(b"not stored", r.content)

    def test_page_shows_view_cv_only_when_a_file_exists(self):
        self.login("hr@x.com")
        detail = reverse("candidate_detail", args=[self.app.id])
        page = self.client.get(detail).content.decode()
        self.assertNotIn(self.url, page)
        self.assertIn("CV file not stored", page)
        ApplicationCvFile.objects.create(
            application=self.app, pdf_bytes=PDF, original_name="cv.pdf")
        page = self.client.get(detail).content.decode()
        self.assertIn(self.url, page)
        self.assertIn("View CV", page)

    def test_copy_is_deleted_with_the_application(self):
        ApplicationCvFile.objects.create(
            application=self.app, pdf_bytes=PDF, original_name="cv.pdf")
        self.app.delete()
        self.assertFalse(ApplicationCvFile.objects.exists())


@override_settings(MEDIA_ROOT=MEDIA)
class ApplyStoresCvCopyTests(TestCase):

    def test_submitting_an_application_saves_a_copy_of_the_cv(self):
        cand_role = _make_role("Candidate")
        job = Job.objects.create(
            title="J", department="ICT", description="x", requirements="x",
            ai_job_profile={"job_title": "J", "education": "Bachelor",
                            "years_experience": 0, "languages": [],
                            "certifications": [], "skills": []},
            ai_processed=True,
            ai_rag_context={"evidence": [], "best_evidence_score": 0,
                            "grounded": False, "error": None})
        user = User.objects.create_user(
            username="ap", password="pass12345", email="ap@x.com",
            first_name="Ap", role=cand_role, is_verified=True)
        self.client.login(email="ap@x.com", password="pass12345")
        pdf = _native_pdf_bytes()
        self.client.post(
            reverse("apply_job", kwargs={"job_id": job.id}),
            {"full_name": "Ap", "email": "ap@x.com",
             "cv_file": SimpleUploadedFile("cv.pdf", pdf, content_type="application/pdf"),
             "education_file": SimpleUploadedFile("d.pdf", pdf, content_type="application/pdf")},
            follow=True)
        app = Application.objects.get(candidate__user=user, job=job)
        self.assertEqual(bytes(app.cv_copy.pdf_bytes), pdf)
        self.assertEqual(app.cv_copy.original_name, "cv.pdf")
