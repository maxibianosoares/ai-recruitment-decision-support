"""
TASK M (2026-10-12): every email sent through the Brevo backend is
recorded in accounts.EmailLog (pending -> sent / failed). All HTTP is
mocked -- no network. Metadata only: the body must never be stored.
"""

from types import SimpleNamespace
from unittest import mock

import requests
from django.core import mail
from django.core.mail import EmailMessage, get_connection, send_mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .email_context import current_email_context, email_context
from .models import EmailLog, User

BACKEND = "accounts.email_backends.BrevoAPIEmailBackend"
POST = "accounts.email_backends.requests.post"
SLEEP = "accounts.email_backends.time.sleep"


def _resp(status, body=b'{"messageId": "<abc@brevo>"}'):
    r = requests.Response()
    r.status_code = status
    r._content = body
    return r


def _err(status):
    return _resp(status, b'{"code": "c", "message": "m"}')


def _msg(to="user@example.com", body="Body text"):
    return EmailMessage("Subject", body, "sender@example.org", [to])


@override_settings(
    EMAIL_BACKEND=BACKEND,
    BREVO_API_KEY="secret-test-key",
    BREVO_MAX_ATTEMPTS=3,
    BREVO_RETRY_BACKOFF_SECONDS=1.0,
    BREVO_TOTAL_BUDGET_SECONDS=20,
)
class EmailLogBackendTests(TestCase):

    def _send(self, message=None, fail_silently=False):
        conn = get_connection(BACKEND, fail_silently=fail_silently)
        return conn.send_messages([message or _msg()])

    # ---- success -------------------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_success_is_logged_as_sent(self, post, sleep):
        self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.status, EmailLog.Status.SENT)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.recipient, "user@example.com")
        self.assertEqual(row.subject, "Subject")
        self.assertEqual(row.provider_message_id, "<abc@brevo>")
        self.assertIsNotNone(row.sent_at)
        self.assertEqual(row.error, "")
        self.assertEqual(row.kind, "other")

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_err(503), _resp(201)])
    def test_retry_then_success_records_two_attempts(self, post, sleep):
        self.assertEqual(self._send(), 1)
        row = EmailLog.objects.get()
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.attempts, 2)

    # ---- failure -------------------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_exhausted_retries_logged_as_failed(self, post, sleep):
        with self.assertRaises(RuntimeError):
            self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.status, EmailLog.Status.FAILED)
        self.assertEqual(row.attempts, 3)
        self.assertIn("HTTP 503", row.error)
        self.assertIsNone(row.sent_at)
        self.assertEqual(row.provider_message_id, "")

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(401))
    def test_permanent_error_logged_after_one_attempt(self, post, sleep):
        with self.assertRaises(RuntimeError):
            self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempts, 1)
        self.assertIn("HTTP 401", row.error)

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=requests.exceptions.ConnectTimeout())
    def test_timeout_logged_as_failed(self, post, sleep):
        with self.assertRaises(RuntimeError):
            self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempts, 3)

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(500))
    def test_fail_silently_still_logs_failure(self, post, sleep):
        self.assertEqual(self._send(fail_silently=True), 0)
        self.assertEqual(EmailLog.objects.get().status, "failed")

    @override_settings(BREVO_API_KEY="")
    def test_missing_api_key_is_logged_as_failed(self):
        with self.assertRaises(RuntimeError):
            self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempts, 0)
        self.assertIn("BREVO_API_KEY", row.error)

    # ---- privacy -------------------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(500))
    def test_body_and_api_key_are_never_stored(self, post, sleep):
        secret = "https://site/reset/abc/SECRET-TOKEN-123/"
        with self.assertRaises(RuntimeError):
            self._send(_msg(body=f"Open {secret}"))
        row = EmailLog.objects.get()
        dump = " ".join(
            str(getattr(row, f.name)) for f in EmailLog._meta.fields
        )
        self.assertNotIn("SECRET-TOKEN-123", dump)
        self.assertNotIn("secret-test-key", dump)

    # ---- logging must never block sending ------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_log_write_failure_does_not_stop_the_email(self, post, sleep):
        with mock.patch.object(
            EmailLog.objects, "create", side_effect=Exception("db down")
        ):
            self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 1)

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_log_update_failure_does_not_stop_the_email(self, post, sleep):
        with mock.patch.object(
            EmailLog, "save", side_effect=Exception("db down")
        ):
            self.assertEqual(self._send(), 1)

    # ---- multiple messages / kind labels -------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_each_message_gets_its_own_row(self, post, sleep):
        conn = get_connection(BACKEND)
        conn.send_messages([_msg("a@example.com"), _msg("b@example.com")])
        self.assertEqual(
            sorted(EmailLog.objects.values_list("recipient", flat=True)),
            ["a@example.com", "b@example.com"],
        )

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_email_context_sets_kind_and_application(self, post, sleep):
        with email_context("final_decision", related_application_id=42):
            self._send()
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "final_decision")
        self.assertEqual(row.related_application_id, 42)

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_unknown_kind_falls_back_to_other(self, post, sleep):
        with email_context("not-a-real-kind"):
            self._send()
        self.assertEqual(EmailLog.objects.get().kind, "other")

    def test_context_is_reset_after_the_with_block(self):
        with email_context("registration"):
            self.assertEqual(current_email_context()["kind"], "registration")
        self.assertEqual(current_email_context()["kind"], "other")

    def test_context_is_reset_even_if_the_block_raises(self):
        with self.assertRaises(ValueError):
            with email_context("registration"):
                raise ValueError("boom")
        self.assertEqual(current_email_context()["kind"], "other")


@override_settings(
    EMAIL_BACKEND=BACKEND,
    BREVO_API_KEY="secret-test-key",
    DEFAULT_FROM_EMAIL="noreply@example.org",
    SITE_URL="https://example.org",
)
class EmailLogCallerTests(TestCase):
    """The real call sites label their emails correctly."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw123456"
        )

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_registration_email(self, post, sleep):
        from .views_auth import _send_verification_email

        request = RequestFactory().get("/")
        _send_verification_email(request, self.user)
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "registration")
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.recipient, "maria@example.com")

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_password_reset_email_success(self, post, sleep):
        resp = self.client.post(
            reverse("password_reset"), {"email": "maria@example.com"}
        )
        self.assertEqual(resp.status_code, 302)
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "password_reset")
        self.assertEqual(row.status, "sent")

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_password_reset_failure_is_logged_but_page_is_the_same(
        self, post, sleep
    ):
        resp = self.client.post(
            reverse("password_reset"), {"email": "maria@example.com"}
        )
        # The user still gets the neutral "sent" redirect ...
        self.assertEqual(resp.status_code, 302)
        # ... but the database now shows the truth.
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "password_reset")
        self.assertEqual(row.status, "failed")

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_password_reset_unknown_email_creates_no_log(self, post, sleep):
        self.client.post(
            reverse("password_reset"), {"email": "nobody@example.com"}
        )
        self.assertEqual(EmailLog.objects.count(), 0)
        post.assert_not_called()

    def _application(self):
        return SimpleNamespace(
            id=77,
            candidate=SimpleNamespace(
                email="maria@example.com", full_name="Maria"
            ),
            job=SimpleNamespace(title="ICT Officer"),
            ai_decision="Recommended",
            ai_feedback="Looks good.",
        )

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_ai_screening_notification(self, post, sleep):
        from talent.notifications import send_ai_screening_completed_email

        send_ai_screening_completed_email(self._application())
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "ai_screening_result")
        self.assertEqual(row.related_application_id, 77)
        self.assertEqual(row.status, "sent")

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(500))
    def test_document_issue_notification_failure(self, post, sleep):
        from talent.notifications import send_document_issue_email

        app = self._application()
        app.ai_feedback = "CV unreadable"
        with self.assertRaises(RuntimeError):
            send_document_issue_email(app)
        row = EmailLog.objects.get()
        self.assertEqual(row.kind, "document_issue")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.related_application_id, 77)


class EmailLogOtherBackendsTests(TestCase):

    def test_locmem_backend_still_works_and_writes_no_log(self):
        # Local development / the test runner use a non-Brevo backend:
        # nothing changes there.
        send_mail("s", "b", "a@example.org", ["u@example.com"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailLog.objects.count(), 0)


@override_settings(
    # The admin pages load static files; the production manifest
    # storage needs collectstatic, which a test run has not done.
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage"
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class EmailLogAdminTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw123456"
        )
        self.client.force_login(self.admin)
        EmailLog.objects.create(
            kind="registration", recipient="x@example.com",
            subject="S", status="failed", error="HTTP 503",
        )

    def test_changelist_loads_and_filters(self):
        url = reverse("admin:accounts_emaillog_changelist")
        resp = self.client.get(url, {"status__exact": "failed"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "x@example.com")

    def test_log_is_read_only(self):
        self.assertEqual(
            self.client.get(reverse("admin:accounts_emaillog_add")).status_code,
            403,
        )
        row = EmailLog.objects.get()
        self.assertEqual(
            self.client.post(
                reverse("admin:accounts_emaillog_change", args=[row.pk]),
                {"status": "sent"},
            ).status_code,
            403,
        )
