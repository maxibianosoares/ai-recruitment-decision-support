"""
send_weekly_hitl_report: recipients, content, idempotency, failure.
The Django test mail backend (locmem) is used for sending; the Brevo
backend itself is already covered by accounts tests and is not re-tested.
"""

import os
from datetime import date, datetime, timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import EmailLog
from talent.hitl_report import render_text
from talent.test_hitl_report import (
    NOW, SECRET_EMAIL, SECRET_JOB, SECRET_NAME, SECRET_REASON, ReportBase, at,
)

ADMIN = "admin-report@example.org"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.org")
class EmailTests(ReportBase):

    def send(self, *args, **env):
        out, err = StringIO(), StringIO()
        with mock.patch.dict(os.environ, env, clear=False):
            call_command("send_weekly_hitl_report", *args, stdout=out, stderr=err)
        return out.getvalue()

    def seed(self):
        d = at(date(2026, 10, 20))
        self.decide("Recommended", "approved", d)
        self.decide("Not Recommended", "approved", d)
        self.decide("Recommended", "rejected", d)

    def test_sends_one_email_with_the_report_and_no_personal_data(self):
        self.seed()
        self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [ADMIN])
        self.assertTrue(m.subject.startswith("[Weekly HITL Report]"))
        self.assertIn("2026-10-19 - 2026-10-25", m.subject)
        self.assertIn("Committee decisions: 3", m.body)
        self.assertIn("Overrode the AI recommendation: 2", m.body)
        for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_REASON, SECRET_JOB):
            self.assertNotIn(secret, m.body + m.subject)

    def test_recipient_comes_from_the_environment_not_the_code(self):
        self.send("--week-ending", "2026-10-25",
                  HITL_REPORT_RECIPIENTS=f"{ADMIN}, second@example.org")
        self.assertEqual(sorted(m.to[0] for m in mail.outbox),
                         [ADMIN, "second@example.org"])
        import inspect
        from ai_engine.management.commands import send_weekly_hitl_report as mod
        self.assertNotIn("maxibianosoares", inspect.getsource(mod))
        self.assertNotIn("@gmail", inspect.getsource(mod))

    def test_no_recipient_is_an_error_and_sends_nothing(self):
        with mock.patch.dict(os.environ, {"HITL_REPORT_RECIPIENTS": ""}):
            with self.assertRaises(CommandError):
                call_command("send_weekly_hitl_report", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_address_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("send_weekly_hitl_report", "--to", "not-an-email",
                         stdout=StringIO())

    def test_second_run_for_the_same_week_does_not_send_again(self):
        self.seed()
        first = self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        # the real Brevo backend writes an EmailLog row; locmem does not
        EmailLog.objects.create(recipient=ADMIN, subject=mail.outbox[0].subject,
                                status=EmailLog.Status.SENT)
        second = self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        self.assertIn("Sent to", first)
        self.assertIn("already sent", second)
        self.assertEqual(len(mail.outbox), 1)

    def test_force_sends_again_and_next_week_is_a_new_email(self):
        self.seed()
        self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        EmailLog.objects.create(recipient=ADMIN, subject=mail.outbox[0].subject,
                                status=EmailLog.Status.SENT)
        self.send("--to", ADMIN, "--week-ending", "2026-10-25", "--force")
        self.assertEqual(len(mail.outbox), 2)
        self.send("--to", ADMIN, "--week-ending", "2026-11-01")   # different week
        self.assertEqual(len(mail.outbox), 3)

    def test_failed_earlier_attempt_is_retried(self):
        self.seed()
        self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        EmailLog.objects.create(recipient=ADMIN, subject=mail.outbox[0].subject,
                                status=EmailLog.Status.FAILED)
        self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        self.assertEqual(len(mail.outbox), 2)

    def test_dry_run_sends_and_logs_nothing(self):
        self.seed()
        out = self.send("--to", ADMIN, "--dry-run", "--week-ending", "2026-10-25")
        self.assertIn("Subject: [Weekly HITL Report]", out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_send_failure_gives_a_non_zero_exit(self):
        with mock.patch("ai_engine.management.commands.send_weekly_hitl_report.send_mail",
                        side_effect=RuntimeError("provider down")):
            with self.assertRaises(CommandError):
                call_command("send_weekly_hitl_report", "--to", ADMIN,
                             stdout=StringIO(), stderr=StringIO())

    def test_empty_week_still_sends_a_clear_report(self):
        self.send("--to", ADMIN, "--week-ending", "2026-10-25")
        self.assertIn("Committee decisions: 0", mail.outbox[0].body)
        self.assertIn("n/a", mail.outbox[0].body)

    def test_text_and_indonesian_rendering(self):
        from talent.hitl_report import build_report
        report = build_report(now=NOW)
        self.assertIn("Laporan mingguan", render_text(report, "id"))
        self.assertIn("Human-in-the-Loop weekly report", render_text(report, "en"))


@override_settings(EMAIL_BACKEND="accounts.email_backends.BrevoAPIEmailBackend",
                   BREVO_API_KEY="test-key", DEFAULT_FROM_EMAIL="noreply@example.org")
class RealBackendTests(ReportBase):
    """The production Brevo backend with only the HTTP call replaced."""

    def run_cmd(self, *args):
        call_command("send_weekly_hitl_report", *args, stdout=StringIO(), stderr=StringIO())

    def test_email_is_logged_and_a_rerun_does_not_send_again(self):
        self.decide("Recommended", "approved", at(date(2026, 10, 20)))
        response = mock.Mock(status_code=201)
        response.json.return_value = {"messageId": "<abc@brevo>"}
        with mock.patch("accounts.email_backends.requests.post",
                        return_value=response) as post:
            self.run_cmd("--to", ADMIN, "--week-ending", "2026-10-25")
            self.run_cmd("--to", ADMIN, "--week-ending", "2026-10-25")
        self.assertEqual(post.call_count, 1)                    # second run: skipped
        row = EmailLog.objects.get()
        self.assertEqual((row.recipient, row.status), (ADMIN, EmailLog.Status.SENT))
        self.assertIn("[Weekly HITL Report]", row.subject)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["to"], [{"email": ADMIN}])
        self.assertIn("Committee decisions: 1", sent["textContent"])
        for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_REASON, SECRET_JOB):
            self.assertNotIn(secret, sent["textContent"])
