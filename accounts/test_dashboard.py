"""
Regression test for the 2026-09-27 fix in accounts/views.py::dashboard():
the view previously rendered dashboard.html with NO context at all, so
its stat tiles (Total Candidates, Highly Recommended, Recommended,
Not Recommended) and the candidate table always rendered empty,
regardless of how many applications existed in the database.

Confirms the view now aggregates real data from talent.Application
(the model the AI pipeline actually writes ai_score/ai_decision/
ai_status to -- NOT recruitment.CandidateResult, which nothing in the
codebase ever populates).
"""

from django.test import TestCase
from django.urls import reverse

from .models import User
from talent.models import Candidate, Job, Application


class DashboardRealDataTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="dashboarduser",
            password="Str0ngP@ssw0rd!",
            email="dashboarduser@example.com",
            is_verified=True,
        )

        self.job = Job.objects.create(
            title="ICT Officer",
            department="ICT",
            description="desc",
            requirements="reqs",
        )

        def make_application(name, email, score, decision, status="SUCCESS"):
            candidate = Candidate.objects.create(
                full_name=name,
                email=email,
                cv_file="cv/dummy.pdf",
            )
            return Application.objects.create(
                candidate=candidate,
                job=self.job,
                ai_score=score,
                ai_decision=decision,
                ai_status=status,
            )

        self.app_highly = make_application(
            "Alice Highly", "alice@example.com", 90, "Highly Recommended"
        )
        self.app_recommended = make_application(
            "Bob Recommended", "bob@example.com", 70, "Recommended"
        )
        self.app_not_recommended = make_application(
            "Carol NotRec", "carol@example.com", 20, "Not Recommended"
        )
        # A still-pending / technically-failed application must NOT be
        # counted in the totals or decision breakdown.
        self.app_pending = make_application(
            "Dave Pending", "dave@example.com", 0, "", status="FAILED"
        )

        self.client.login(email="dashboarduser@example.com", password="Str0ngP@ssw0rd!")

    def test_dashboard_shows_real_counts_not_empty(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 3)  # excludes FAILED
        self.assertEqual(response.context["highly"], 1)
        self.assertEqual(response.context["recommended"], 1)
        self.assertEqual(response.context["not_recommended"], 1)

    def test_dashboard_candidate_table_has_real_rows(self):
        response = self.client.get(reverse("dashboard"))

        names = [c["candidate_name"] for c in response.context["candidates"]]

        self.assertIn("Alice Highly", names)
        self.assertIn("Bob Recommended", names)
        self.assertIn("Carol NotRec", names)
        self.assertNotIn("Dave Pending", names)

    def test_dashboard_candidates_ordered_by_score_descending(self):
        response = self.client.get(reverse("dashboard"))

        scores = [c["final_score"] for c in response.context["candidates"]]

        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_dashboard_with_no_applications_shows_zero_not_error(self):
        Application.objects.all().delete()

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 0)
        self.assertEqual(response.context["candidates"], [])