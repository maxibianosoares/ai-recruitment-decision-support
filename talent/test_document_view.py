"""Opening an uploaded supporting document from the candidate page."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from talent.models import (
    Application, ApplicationSupportingDocument as SD, Candidate, Job,
)
from talent.tests import _make_role

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class DocumentViewTests(TestCase):

    def setUp(self):
        cand_role = _make_role("Candidate")
        hr_role = _make_role("HR Officer", ["recruitment_manage"])
        job = Job.objects.create(
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
        profile = Candidate.objects.create(
            user=self.owner, full_name="O", email="o-cv@x.com")
        self.app = Application.objects.create(candidate=profile, job=job)
        self.doc = SD.objects.create(
            application=self.app, doc_type=SD.TYPE_EDUCATION,
            pdf_bytes=PDF, original_name='dip"loma\r\n.pdf', sha256="a" * 64,
            status=SD.STATUS_PROCESSED)
        self.url = reverse("supporting_document_file",
                           args=[self.app.id, self.doc.id])

    def login(self, email):
        self.client.login(email=email, password="pass12345")

    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r.url)

    def test_owner_and_staff_can_open_it_inline(self):
        for email in ("own@x.com", "hr@x.com"):
            self.client.logout(); self.login(email)
            r = self.client.get(self.url)
            self.assertEqual(r.status_code, 200, email)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r["Content-Disposition"].startswith("inline"))
            self.assertEqual(r["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", r["Cache-Control"])
            self.assertEqual(r.content, PDF)

    def test_another_candidate_is_refused(self):
        self.login("oth@x.com")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_header_value_cannot_be_injected_through_the_file_name(self):
        self.login("own@x.com")
        r = self.client.get(self.url)
        header = r["Content-Disposition"]
        self.assertNotIn("\n", header); self.assertNotIn("\r", header)
        self.assertEqual(header.count('"'), 2)

    def test_document_of_another_application_cannot_be_reached(self):
        job = self.app.job
        profile2 = Candidate.objects.create(
            user=self.other, full_name="P", email="p-cv@x.com")
        app2 = Application.objects.create(candidate=profile2, job=job)
        self.login("hr@x.com")
        r = self.client.get(reverse("supporting_document_file",
                                    args=[app2.id, self.doc.id]))
        self.assertEqual(r.status_code, 404)

    def test_non_pdf_bytes_are_downloaded_never_rendered(self):
        self.doc.pdf_bytes = b"<html><script>alert(1)</script></html>"
        self.doc.save()
        self.login("hr@x.com")
        r = self.client.get(self.url)
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    def test_old_document_without_stored_file_gives_a_clear_404(self):
        self.doc.pdf_bytes = None
        self.doc.save()
        self.login("hr@x.com")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)
        self.assertIn(b"not stored", r.content)

    def test_candidate_page_shows_view_link_only_when_file_exists(self):
        self.login("hr@x.com")
        page = self.client.get(
            reverse("candidate_detail", args=[self.app.id])).content.decode()
        self.assertIn(self.url, page)
        self.assertIn('target="_blank"', page)
        self.assertNotIn("File not stored", page)
        self.doc.pdf_bytes = None
        self.doc.save()
        page = self.client.get(
            reverse("candidate_detail", args=[self.app.id])).content.decode()
        self.assertNotIn(self.url, page)
        self.assertIn("File not stored", page)
