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

        self.client.login(username="candA", password="pass12345")

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
        self.client.login(username="candB", password="pass12345")

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

        self.client.login(username="candA", password="pass12345")

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

        self.client.login(username="hr_view", password="pass12345")

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
            email="applicant1@x.com",
            role=self.candidate_role, is_verified=True
        )

    def test_candidate_can_self_apply_and_owns_result(self):

        self.client.login(username="applicant1", password="pass12345")

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

        self.client.login(username="applicant1", password="pass12345")

        resp = self.client.get(
            reverse("apply_job", kwargs={"job_id": self.job.id}), follow=True
        )

        self.assertContains(resp, "already applied")

        self.assertEqual(
            Application.objects.filter(candidate=candidate, job=self.job).count(),
            1
        )
