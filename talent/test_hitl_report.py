"""
Weekly Human-in-the-Loop report (talent/hitl_report.py and the
weekly_hitl_report command).

Unit tests build decisions directly with controlled timestamps.  The
integration test records decisions through the REAL candidate_detail
view, so the report is checked against what the application actually
stores.  No model, network or Ollama is involved.
"""

import json
from datetime import date, datetime, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from talent import statuses as S
from talent.hitl_report import (
    LOW_VOLUME_THRESHOLD, build_report, last_completed_week_start,
    render_markdown, week_bounds,
)
from talent.models import Application, Candidate, HumanDecision, Job
from talent.tests import _make_role

SECRET_NAME = "Zeta Secretname"
SECRET_EMAIL = "zeta.secret@example.org"
SECRET_REASON = "SECRET-REASON-do-not-leak"
SECRET_JOB = "Secret Job Title Q"

# Monday 2026-10-26 10:00 (Dili time) -> last completed week is 19..25 Oct
TZ = timezone.get_current_timezone()
NOW = timezone.make_aware(datetime(2026, 10, 26, 10, 0), TZ)
WEEK = date(2026, 10, 19)


def at(day, hour=12):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()), TZ) \
        + timedelta(hours=hour)


class ReportBase(TestCase):

    def setUp(self):
        self.job = Job.objects.create(
            title=SECRET_JOB, department="ICT", description="x",
            requirements="x", ai_job_profile={}, ai_processed=True)
        self.n = 0

    def decide(self, ai, decision, when, agreed=None, processed=None,
               status=S.SUCCESS):
        """Create one finished application + its human decision at `when`."""
        self.n += 1
        candidate = Candidate.objects.create(
            full_name=SECRET_NAME, email=f"c{self.n}-{SECRET_EMAIL}")
        app = Application.objects.create(
            candidate=candidate, job=self.job, ai_status=status,
            ai_decision=ai, ai_processed_at=processed)
        positive = (ai or "").lower() in ("highly recommended", "recommended", "consider")
        if agreed is None:
            agreed = ((decision == "approved" and positive)
                      or (decision == "rejected" and not positive))
        hd = HumanDecision.objects.create(
            application=app, decision=decision, reason=SECRET_REASON,
            agreed_with_ai=agreed)
        HumanDecision.objects.filter(pk=hd.pk).update(created_at=when)
        return app

    def waiting(self, ai="Recommended", processed=None, status=S.SUCCESS):
        self.n += 1
        candidate = Candidate.objects.create(
            full_name=SECRET_NAME, email=f"w{self.n}-{SECRET_EMAIL}")
        return Application.objects.create(
            candidate=candidate, job=self.job, ai_status=status,
            ai_decision=ai, ai_processed_at=processed)

    def report(self, **kw):
        kw.setdefault("now", NOW)
        return build_report(**kw)


# =====================================================================
# Counting
# =====================================================================

class CountingTests(ReportBase):

    def test_agreed_and_overridden_counts_and_directions(self):
        d = date(2026, 10, 20)
        self.decide("Highly Recommended", "approved", at(d))      # agreed
        self.decide("Recommended", "approved", at(d))             # agreed
        self.decide("Not Recommended", "rejected", at(d))         # agreed
        self.decide("Not Recommended", "approved", at(d))         # override: AI neg -> approved
        self.decide("Recommended", "rejected", at(d))             # override: AI pos -> rejected
        self.decide("Consider", "rejected", at(d))                # override: AI pos -> rejected
        out = self.report(weeks=1)
        w = out["weekly"][0]
        self.assertEqual((w["decisions"], w["approved"], w["rejected"]), (6, 3, 3))
        self.assertEqual((w["agreed_with_ai"], w["overridden"]), (3, 3))
        self.assertEqual(w["agreement_rate"], 0.5)
        self.assertEqual(w["override_rate"], 0.5)
        self.assertEqual(w["overridden_breakdown"],
                         {"ai_negative_human_approved": 1,
                          "ai_positive_human_rejected": 2})
        cat = w["by_ai_recommendation"]
        self.assertEqual(cat["recommended"], {"decisions": 2, "agreed": 1, "overridden": 1})
        self.assertEqual(cat["not recommended"], {"decisions": 2, "agreed": 1, "overridden": 1})
        self.assertEqual(cat["highly recommended"]["decisions"], 1)
        self.assertEqual(cat["consider"]["overridden"], 1)
        self.assertEqual(sum(c["decisions"] for c in cat.values()), 6)
        self.assertEqual(out["period"]["decisions"], 6)
        self.assertEqual(out["data_integrity"]["agreement_flag_inconsistencies"], 0)

    def test_unknown_or_empty_ai_decision_goes_to_other(self):
        d = date(2026, 10, 21)
        self.decide("", "rejected", at(d))
        self.decide("Unclear", "approved", at(d))
        w = self.report(weeks=1)["weekly"][0]
        self.assertEqual(w["by_ai_recommendation"]["other / none"]["decisions"], 2)

    def test_empty_database(self):
        out = self.report()
        self.assertEqual(out["period"]["decisions"], 0)
        self.assertIsNone(out["period"]["agreement_rate"])
        self.assertIsNone(out["period"]["median_hours_ai_to_decision"])
        self.assertEqual(out["pending_now"]["awaiting_human_decision"], 0)
        self.assertEqual(len(out["weekly"]), 4)
        self.assertIn("n/a", render_markdown(out))

    def test_multiple_weeks_are_separate_and_ordered(self):
        self.decide("Recommended", "approved", at(date(2026, 10, 7)))    # week of 5 Oct
        self.decide("Recommended", "approved", at(date(2026, 10, 14)))   # week of 12 Oct
        self.decide("Recommended", "rejected", at(date(2026, 10, 21)))   # week of 19 Oct
        out = self.report(weeks=3)
        self.assertEqual([w["week_start"] for w in out["weekly"]],
                         ["2026-10-05", "2026-10-12", "2026-10-19"])
        self.assertEqual([w["decisions"] for w in out["weekly"]], [1, 1, 1])
        self.assertEqual(out["period"]["decisions"], 3)
        self.assertEqual(out["period"]["start"], "2026-10-05")
        self.assertEqual(out["period"]["end"], "2026-10-25")


# =====================================================================
# Week boundaries
# =====================================================================

class WeekTests(ReportBase):

    def test_default_week_is_the_last_completed_monday_to_sunday(self):
        self.assertEqual(last_completed_week_start(NOW), WEEK)
        sunday_evening = timezone.make_aware(datetime(2026, 10, 25, 23, 0), TZ)
        self.assertEqual(last_completed_week_start(sunday_evening), date(2026, 10, 12))
        out = self.report(weeks=1)
        self.assertEqual(out["weekly"][0]["week_start"], "2026-10-19")
        self.assertEqual(out["weekly"][0]["week_end"], "2026-10-25")

    def test_boundaries_are_half_open(self):
        lo, hi = week_bounds(WEEK)
        self.decide("Recommended", "approved", lo)                          # first instant: in
        self.decide("Recommended", "approved", hi - timedelta(seconds=1))   # last instant: in
        self.decide("Recommended", "approved", hi)                          # next week: out
        self.decide("Recommended", "approved", lo - timedelta(seconds=1))   # previous week: out
        out = self.report(weeks=1)
        self.assertEqual(out["weekly"][0]["decisions"], 2)

    def test_week_ending_accepts_any_day_in_the_week(self):
        self.decide("Recommended", "approved", at(date(2026, 10, 14)))
        out = self.report(weeks=1, week_ending=date(2026, 10, 15))
        self.assertEqual(out["weekly"][0]["week_start"], "2026-10-12")
        self.assertEqual(out["weekly"][0]["decisions"], 1)

    def test_invalid_weeks_value(self):
        for bad in (0, 53, -1):
            with self.assertRaises(ValueError):
                build_report(weeks=bad, now=NOW)


# =====================================================================
# Pending, timing, volume, integrity
# =====================================================================

class OtherMetricTests(ReportBase):

    def test_pending_counts_and_age_buckets(self):
        self.waiting(processed=NOW - timedelta(days=2))
        self.waiting(processed=NOW - timedelta(days=10))
        self.waiting(processed=NOW - timedelta(days=30))
        self.waiting(processed=NOW - timedelta(days=30), status=S.FAILED)   # AI not done
        self.waiting(processed=NOW - timedelta(days=3), status=S.QUEUED)    # AI not done
        self.decide("Recommended", "approved", at(date(2026, 10, 20)),
                    processed=NOW - timedelta(days=9))                      # decided: not waiting
        p = self.report()["pending_now"]
        self.assertEqual(p["awaiting_human_decision"], 3)
        self.assertEqual(p["age"], {"up_to_7_days": 1, "8_to_14_days": 1,
                                    "over_14_days": 1})

    def test_median_hours_from_ai_result_to_decision(self):
        d = at(date(2026, 10, 20), 12)
        for hours in (2, 4, 30):
            self.decide("Recommended", "approved", d, processed=d - timedelta(hours=hours))
        self.decide("Recommended", "approved", d)           # no ai_processed_at: ignored
        w = self.report(weeks=1)["weekly"][0]
        self.assertEqual(w["median_hours_ai_to_decision"], 4.0)

    def test_low_volume_flag(self):
        d = at(date(2026, 10, 20))
        for _ in range(LOW_VOLUME_THRESHOLD - 1):
            self.decide("Recommended", "approved", d)
        self.assertTrue(self.report(weeks=1)["weekly"][0]["low_volume"])
        self.decide("Recommended", "approved", d)
        self.assertFalse(self.report(weeks=1)["weekly"][0]["low_volume"])

    def test_low_volume_is_visible_in_the_markdown(self):
        self.decide("Recommended", "approved", at(date(2026, 10, 20)))
        self.assertIn("low volume", render_markdown(self.report(weeks=1)))

    def test_inconsistent_stored_flag_is_reported_not_hidden(self):
        d = at(date(2026, 10, 20))
        self.decide("Recommended", "approved", d)
        self.decide("Recommended", "approved", d, agreed=False)   # flag contradicts the rule
        out = self.report(weeks=1)
        self.assertEqual(out["data_integrity"]["agreement_flag_inconsistencies"], 1)
        self.assertIn("do not match", render_markdown(out))
        # the report still uses the stored flag, as the application does
        self.assertEqual(out["weekly"][0]["overridden"], 1)


# =====================================================================
# Privacy
# =====================================================================

class PrivacyTests(ReportBase):

    FORBIDDEN_KEYS = {"name", "full_name", "email", "reason", "id", "pk",
                      "username", "job", "title", "candidate", "decided_by",
                      "application"}

    def walk(self, node, found):
        if isinstance(node, dict):
            for k, v in node.items():
                found.add(k)
                self.walk(v, found)
        elif isinstance(node, list):
            for v in node:
                self.walk(v, found)

    def test_no_personal_data_in_json_or_markdown(self):
        d = at(date(2026, 10, 20))
        for ai, dec in (("Recommended", "approved"), ("Not Recommended", "approved"),
                        ("Recommended", "rejected")):
            self.decide(ai, dec, d)
        self.waiting()
        out = self.report()
        text = json.dumps(out) + render_markdown(out, "en") + render_markdown(out, "id")
        for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_REASON, SECRET_JOB,
                       "Zeta", "example.org"):
            self.assertNotIn(secret, text)
        keys = set()
        self.walk(out, keys)
        self.assertFalse(keys & self.FORBIDDEN_KEYS, keys & self.FORBIDDEN_KEYS)

    def test_report_is_read_only(self):
        d = at(date(2026, 10, 20))
        self.decide("Recommended", "approved", d)
        self.waiting()
        before = (list(HumanDecision.objects.values_list("pk", "updated_at", "agreed_with_ai")),
                  list(Application.objects.values_list("pk", "updated_at", "status", "ai_status")))
        self.report()
        call_command("weekly_hitl_report", stdout=StringIO())
        after = (list(HumanDecision.objects.values_list("pk", "updated_at", "agreed_with_ai")),
                 list(Application.objects.values_list("pk", "updated_at", "status", "ai_status")))
        self.assertEqual(before, after)


# =====================================================================
# Command
# =====================================================================

class CommandTests(ReportBase):

    def run_cmd(self, *args):
        out = StringIO()
        call_command("weekly_hitl_report", *args, stdout=out)
        return out.getvalue()

    def test_json_output_is_valid_and_matches_the_function(self):
        self.decide("Recommended", "approved", timezone.now() - timedelta(days=8))
        data = json.loads(self.run_cmd("--format", "json", "--weeks", "2"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(len(data["weekly"]), 2)
        self.assertEqual(data["period"]["weeks"], 2)
        self.assertIn("definitions", data)
        self.assertIn("privacy", data)

    def test_markdown_output_in_both_languages(self):
        en = self.run_cmd("--week-ending", "2026-10-25")
        idn = self.run_cmd("--week-ending", "2026-10-25", "--lang", "id")
        self.assertIn("# Human-in-the-Loop weekly report", en)
        self.assertIn("| Week |", en)
        self.assertIn("# Laporan mingguan Human-in-the-Loop", idn)
        self.assertIn("| Minggu |", idn)

    def test_bad_arguments(self):
        with self.assertRaises(CommandError):
            self.run_cmd("--week-ending", "not-a-date")
        with self.assertRaises(CommandError):
            self.run_cmd("--weeks", "0")


# =====================================================================
# Integration: decisions recorded through the REAL view
# =====================================================================

class ViewIntegrationTests(TestCase):

    def test_report_matches_decisions_recorded_by_the_real_view(self):
        role = _make_role("Administrator", ["recruitment_manage"])
        admin = User.objects.create_user(
            username="adm", password="pass12345", email="adm@x.com",
            role=role, is_verified=True)
        job = Job.objects.create(title="T", department="D", description="x",
                                 requirements="x", ai_job_profile={}, ai_processed=True)
        plan = [("Highly Recommended", "approved"), ("Recommended", "rejected"),
                ("Consider", "approved"), ("Not Recommended", "rejected"),
                ("Not Recommended", "approved"), ("", "rejected"), ("", "approved")]
        self.client.login(email="adm@x.com", password="pass12345")
        for i, (ai, decision) in enumerate(plan):
            cand = Candidate.objects.create(full_name=f"N{i}", email=f"n{i}@x.com")
            app = Application.objects.create(
                candidate=cand, job=job, ai_status=S.SUCCESS, ai_decision=ai,
                ai_processed_at=timezone.now() - timedelta(hours=3))
            with mock.patch("talent.views._send_candidate_outcome_email"):
                resp = self.client.post(
                    reverse("candidate_detail", kwargs={"application_id": app.id}),
                    {"form_type": "human_decision", "decision": decision,
                     "reason": f"reason {i}"})
            self.assertEqual(resp.status_code, 302)

        out = build_report(week_ending=timezone.localdate(), weeks=1)
        w = out["weekly"][0]
        self.assertEqual(w["decisions"], 7)
        self.assertEqual(w["approved"], 4)
        self.assertEqual(w["rejected"], 3)
        # stored flags written by the view and the report's own rule agree
        self.assertEqual(out["data_integrity"]["agreement_flag_inconsistencies"], 0)
        self.assertEqual(w["agreed_with_ai"] + w["overridden"], 7)
        self.assertEqual(w["agreed_with_ai"],
                         HumanDecision.objects.filter(agreed_with_ai=True).count())
        # Recommended->rejected = 1; Not Recommended->approved and ""->approved = 2
        self.assertEqual(w["overridden_breakdown"]["ai_positive_human_rejected"], 1)
        self.assertEqual(w["overridden_breakdown"]["ai_negative_human_approved"], 2)
        self.assertEqual(w["median_hours_ai_to_decision"], 3.0)
        self.assertEqual(out["pending_now"]["awaiting_human_decision"], 0)
