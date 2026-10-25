"""Pipeline monitor: numbers, alerts, no repeats, daily summary, privacy."""

import json
import os
from datetime import datetime, timedelta, timezone as dt_tz
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import EmailLog
from talent import pipeline_monitor as M
from talent import statuses as S
from talent.models import Application, Candidate, Job

ADMIN = "admin-monitor@example.org"
SECRET_NAME = "Zeta Secretname"
SECRET_EMAIL = "zeta-secret@example.org"
SECRET_JOB = "Secret Job Title 4711"

# 03:00 in Dili/Seoul (UTC+9) = 18:00 UTC the day before: before the digest.
EARLY = datetime(2026, 10, 24, 18, 0, tzinfo=dt_tz.utc)     # 03:00 local, 25 Oct
LATE = datetime(2026, 10, 25, 1, 0, tzinfo=dt_tz.utc)       # 10:00 local, 25 Oct


class Base(TestCase):

    def setUp(self):
        self.job = Job.objects.create(
            title=SECRET_JOB, department="ICT", description="x",
            requirements="x", ai_job_profile={}, ai_processed=True)
        self.n = 0

    def app(self, status, age_minutes=0, now=EARLY, processed_minutes_ago=None,
            decided=False):
        self.n += 1
        cand = Candidate.objects.create(
            full_name=SECRET_NAME, email=f"c{self.n}-{SECRET_EMAIL}")
        processed = (now - timedelta(minutes=processed_minutes_ago)
                     if processed_minutes_ago is not None else None)
        a = Application.objects.create(
            candidate=cand, job=self.job, ai_status=status,
            ai_processed_at=processed)
        Application.objects.filter(pk=a.pk).update(
            updated_at=now - timedelta(minutes=age_minutes))
        if decided:
            from talent.models import HumanDecision
            HumanDecision.objects.create(
                application=a, decision="approved", reason="r",
                agreed_with_ai=True)
        return a


class CollectTests(Base):

    def test_normal_system_has_no_alerts(self):
        self.app(S.QUEUED, age_minutes=5)
        self.app(S.PROCESSING, age_minutes=5)
        self.app(S.SUCCESS, processed_minutes_ago=60)
        d = M.collect(now=EARLY)
        self.assertEqual(d["alerts"], [])
        self.assertEqual(d["queue"]["queued"], 1)
        self.assertEqual(d["in_flight"]["count"], 1)
        self.assertEqual(d["last_24h"]["completed"], 1)

    def test_queue_stalled_when_oldest_waits_too_long(self):
        self.app(S.QUEUED, age_minutes=45)
        self.app(S.QUEUED, age_minutes=2)
        d = M.collect(now=EARLY, queue_minutes=30)
        self.assertIn("queue_stalled", d["alerts"])
        self.assertEqual(d["queue"]["oldest_waiting_minutes"], 45)
        self.assertNotIn("queue_stalled", M.collect(now=EARLY, queue_minutes=60)["alerts"])

    def test_stuck_in_flight(self):
        for status in S.IN_FLIGHT_STATUSES:
            self.app(status, age_minutes=40)
        self.app(S.PROCESSING, age_minutes=3)
        d = M.collect(now=EARLY, stuck_minutes=30)
        self.assertIn("stuck", d["alerts"])
        self.assertEqual(d["in_flight"]["stuck"], 3)
        self.assertEqual(d["in_flight"]["count"], 4)

    def test_ai_failures_alert_only_within_24_hours(self):
        self.app(S.FAILED, processed_minutes_ago=30)
        self.app(S.FAILED, processed_minutes_ago=60 * 30)      # 30 h ago
        d = M.collect(now=EARLY)
        self.assertEqual(d["last_24h"]["ai_failures"], 1)
        self.assertIn("ai_failures", d["alerts"])

    def test_unreadable_cv_is_information_not_an_alert(self):
        self.app(S.DOCUMENT_INVALID, processed_minutes_ago=10)
        self.app(S.EXTRACTION_FAILED, processed_minutes_ago=10)
        d = M.collect(now=EARLY)
        self.assertEqual(d["last_24h"]["unreadable_cv"], 2)
        self.assertEqual(d["alerts"], [])

    def test_waiting_for_human_decision_and_long_wait_note(self):
        self.app(S.SUCCESS, processed_minutes_ago=60 * 24 * 20)    # 20 days
        self.app(S.SUCCESS, processed_minutes_ago=60)
        self.app(S.SUCCESS, processed_minutes_ago=60, decided=True)
        d = M.collect(now=EARLY)
        p = d["awaiting_human_decision"]
        self.assertEqual(p["awaiting_human_decision"], 2)
        self.assertEqual(p["age"]["over_14_days"], 1)
        self.assertIn("long_wait", d["notes"])
        self.assertEqual(d["alerts"], [])        # long wait is a note, not an alert

    def test_empty_system(self):
        d = M.collect(now=EARLY)
        self.assertIsNone(d["queue"]["oldest_waiting_minutes"])
        self.assertIn("n/a", M.render_text(d))

    def test_no_personal_data_anywhere(self):
        self.app(S.QUEUED, age_minutes=45)
        self.app(S.FAILED, processed_minutes_ago=5)
        d = M.collect(now=EARLY)
        text = M.render_text(d) + json.dumps(d) + M.alert_subject(d)
        for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_JOB):
            self.assertNotIn(secret, text)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.org")
class CommandTests(Base):

    def run_cmd(self, now, *args, env=None):
        out, err = StringIO(), StringIO()
        with mock.patch("django.utils.timezone.now", return_value=now), \
                mock.patch.dict(os.environ, env or {}, clear=False):
            call_command("monitor_pipeline", *args, stdout=out, stderr=err)
        return out.getvalue()

    def logged(self, subject, created, status=EmailLog.Status.SENT):
        row = EmailLog.objects.create(recipient=ADMIN, subject=subject, status=status)
        EmailLog.objects.filter(pk=row.pk).update(created_at=created)

    def test_normal_and_before_digest_hour_sends_nothing(self):
        self.app(S.QUEUED, age_minutes=1)
        out = self.run_cmd(EARLY, "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("nothing to send", out)

    def test_problem_sends_an_alert_with_counts_only(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        self.run_cmd(EARLY, "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [ADMIN])
        self.assertTrue(m.subject.startswith("[Pipeline Alert]"))
        self.assertIn("worker", m.body)
        for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_JOB):
            self.assertNotIn(secret, m.body + m.subject)

    def test_same_alert_is_not_repeated_within_the_window(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        self.run_cmd(EARLY, "--to", ADMIN)
        subject = mail.outbox[0].subject
        self.logged(subject, EARLY)
        mail.outbox.clear()
        self.run_cmd(EARLY + timedelta(minutes=30), "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 0)

    def test_alert_is_sent_again_after_the_window(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        self.run_cmd(EARLY, "--to", ADMIN)
        subject = mail.outbox[0].subject
        self.logged(subject, EARLY)
        mail.outbox.clear()
        self.run_cmd(EARLY + timedelta(hours=7), "--to", ADMIN, "--repeat-hours", "6",
                     "--digest-hour", "23")
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith("[Pipeline Alert]"))

    def test_alert_is_sent_again_when_the_numbers_change(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        self.run_cmd(EARLY, "--to", ADMIN)
        self.logged(mail.outbox[0].subject, EARLY)
        mail.outbox.clear()
        self.app(S.FAILED, processed_minutes_ago=1, now=EARLY)
        self.run_cmd(EARLY + timedelta(minutes=30), "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("AI failure", mail.outbox[0].subject)

    def test_daily_summary_after_digest_hour_even_when_all_is_normal(self):
        self.app(S.SUCCESS, processed_minutes_ago=10, now=LATE)
        self.run_cmd(LATE, "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject,
                         "[Pipeline Daily Summary] 2026-10-25")

    def test_daily_summary_only_once_per_day(self):
        self.run_cmd(LATE, "--to", ADMIN)
        self.logged(mail.outbox[0].subject, LATE)
        mail.outbox.clear()
        self.run_cmd(LATE + timedelta(minutes=30), "--to", ADMIN)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_recipient_is_an_error(self):
        with mock.patch.dict(os.environ, {"MONITOR_RECIPIENTS": "",
                                          "HITL_REPORT_RECIPIENTS": ""}):
            with self.assertRaises(CommandError):
                call_command("monitor_pipeline", stdout=StringIO())

    def test_recipient_falls_back_to_hitl_variable(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        self.run_cmd(EARLY, env={"MONITOR_RECIPIENTS": "",
                                 "HITL_REPORT_RECIPIENTS": ADMIN})
        self.assertEqual(mail.outbox[0].to, [ADMIN])

    def test_invalid_address_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(EARLY, "--to", "not-an-address")

    def test_dry_run_prints_and_sends_nothing(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        out = self.run_cmd(LATE, "--dry-run")
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("NEEDS ATTENTION", out)
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_json_format_is_valid(self):
        out = self.run_cmd(EARLY, "--dry-run", "--format", "json")
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_send_failure_gives_a_non_zero_exit(self):
        self.app(S.QUEUED, age_minutes=45, now=EARLY)
        with mock.patch("ai_engine.management.commands.monitor_pipeline.send_mail",
                        side_effect=RuntimeError("smtp down")):
            with self.assertRaises(CommandError):
                self.run_cmd(EARLY, "--to", ADMIN)

    def test_address_is_not_in_the_source(self):
        import inspect
        from ai_engine.management.commands import monitor_pipeline as mod
        src = inspect.getsource(mod) + inspect.getsource(M)
        self.assertNotIn("@gmail", src)
        self.assertNotIn("portalvagas", src)
