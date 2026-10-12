"""
TASK L (2026-10-12): the Brevo email backend retries transient
failures (timeout, connection error, HTTP 429 / 5xx) and does NOT
retry permanent ones (HTTP 4xx). All HTTP is mocked -- no network.
"""

from unittest import mock

import requests
from django.core import mail
from django.core.mail import EmailMessage, get_connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

BACKEND = "accounts.email_backends.BrevoAPIEmailBackend"
POST = "accounts.email_backends.requests.post"
SLEEP = "accounts.email_backends.time.sleep"


def _resp(status, body=b'{"messageId": "<1@brevo>"}'):
    r = requests.Response()
    r.status_code = status
    r._content = body
    return r


def _err(status):
    return _resp(
        status, b'{"code": "some_code", "message": "some message"}'
    )


def _msg(to="user@example.com"):
    return EmailMessage(
        "Subject", "Body text", "sender@example.org", [to]
    )


@override_settings(
    EMAIL_BACKEND=BACKEND,
    BREVO_API_KEY="test-key",
    BREVO_MAX_ATTEMPTS=3,
    BREVO_RETRY_BACKOFF_SECONDS=1.0,
    BREVO_TOTAL_BUDGET_SECONDS=20,
)
class BrevoRetryTests(TestCase):

    def _send(self, message=None, fail_silently=False):
        conn = get_connection(BACKEND, fail_silently=fail_silently)
        return conn.send_messages([message or _msg()])

    # ---- success paths ------------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_success_first_try_posts_once_and_never_sleeps(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_err(503), _resp(201)])
    def test_503_then_success_is_delivered(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @mock.patch(SLEEP)
    @mock.patch(
        POST,
        side_effect=[requests.exceptions.ReadTimeout("slow"), _resp(201)],
    )
    def test_timeout_then_success_is_delivered(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 2)

    @mock.patch(SLEEP)
    @mock.patch(
        POST,
        side_effect=[
            requests.exceptions.ConnectionError("reset"), _resp(201)
        ],
    )
    def test_connection_error_then_success_is_delivered(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 2)

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_err(429), _resp(201)])
    def test_429_then_success_is_delivered(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 2)

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_err(500), _err(502), _resp(201)])
    def test_succeeds_on_the_last_allowed_attempt_with_backoff(self, post, sleep):
        self.assertEqual(self._send(), 1)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            [c.args[0] for c in sleep.call_args_list], [1.0, 2.0]
        )

    # ---- failure paths ------------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_persistent_5xx_gives_up_after_max_attempts(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError) as ctx:
                self._send()
        self.assertEqual(post.call_count, 3)
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertIn("3 attempt", str(ctx.exception))

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(401))
    def test_401_is_permanent_and_not_retried(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError) as ctx:
                self._send()
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertIn("some_code", str(ctx.exception))

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(400))
    def test_400_invalid_request_is_not_retried(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError):
                self._send()
        self.assertEqual(post.call_count, 1)

    @mock.patch(SLEEP)
    @mock.patch(
        POST, side_effect=requests.exceptions.ConnectTimeout("down")
    )
    def test_persistent_network_failure_reports_attempts(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError) as ctx:
                self._send()
        self.assertEqual(post.call_count, 3)
        self.assertIn("HTTP unknown", str(ctx.exception))

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_fail_silently_returns_zero_without_raising(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            self.assertEqual(self._send(fail_silently=True), 0)
        self.assertEqual(post.call_count, 3)

    @override_settings(BREVO_MAX_ATTEMPTS=1)
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_max_attempts_one_disables_retry(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError):
                self._send()
        self.assertEqual(post.call_count, 1)

    @override_settings(BREVO_TOTAL_BUDGET_SECONDS=0.5)
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_time_budget_stops_further_retries(self, post, sleep):
        with self.assertLogs("accounts.email_backends", "ERROR"):
            with self.assertRaises(RuntimeError):
                self._send()
        self.assertEqual(post.call_count, 1)

    @mock.patch(SLEEP)
    @mock.patch(POST)
    def test_missing_api_key_still_raises_clearly(self, post, sleep):
        with override_settings(BREVO_API_KEY=""):
            with self.assertRaises(RuntimeError) as ctx:
                self._send()
        self.assertIn("BREVO_API_KEY", str(ctx.exception))
        post.assert_not_called()

    # ---- request content ----------------------------------------
    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_resp(201))
    def test_payload_and_headers_are_unchanged(self, post, sleep):
        self._send(_msg("maria@example.com"))
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["api-key"], "test-key")
        self.assertEqual(kwargs["json"]["to"], [{"email": "maria@example.com"}])
        self.assertEqual(kwargs["json"]["textContent"], "Body text")
        self.assertEqual(kwargs["json"]["sender"], {"email": "sender@example.org"})
        self.assertLessEqual(kwargs["timeout"], 8)

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_resp(201), _err(503), _err(503), _err(503)])
    def test_each_message_is_retried_independently(self, post, sleep):
        conn = get_connection(BACKEND, fail_silently=True)
        with self.assertLogs("accounts.email_backends", "ERROR"):
            sent = conn.send_messages([_msg("a@example.com"), _msg("b@example.com")])
        self.assertEqual(sent, 1)  # first delivered, second exhausted
        self.assertEqual(post.call_count, 4)

    def test_empty_list_sends_nothing(self):
        self.assertEqual(get_connection(BACKEND).send_messages([]), 0)


@override_settings(
    EMAIL_BACKEND=BACKEND,
    BREVO_API_KEY="test-key",
    DEFAULT_FROM_EMAIL="sender@example.org",
    SITE_URL="https://recruit.example.org",
)
class PasswordResetSurvivesBrevoBlipTests(TestCase):
    """The real incident: first Brevo call fails, user still gets mail."""

    def setUp(self):
        User.objects.create_user(
            username="maria", email="maria@example.com",
            password="OldPassw0rd!", is_verified=True,
        )

    @mock.patch(SLEEP)
    @mock.patch(POST, side_effect=[_err(503), _resp(201)])
    def test_reset_email_is_delivered_after_one_transient_failure(self, post, sleep):
        resp = self.client.post(
            reverse("password_reset"), {"email": "maria@example.com"}
        )
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(post.call_count, 2)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["to"], [{"email": "maria@example.com"}])
        self.assertIn(
            "https://recruit.example.org/accounts/reset/", sent["textContent"]
        )

    @mock.patch(SLEEP)
    @mock.patch(POST, return_value=_err(503))
    def test_reset_page_response_is_identical_even_if_brevo_stays_down(self, post, sleep):
        """Privacy rule still holds: no leak when sending ultimately fails."""
        known = self.client.post(
            reverse("password_reset"), {"email": "maria@example.com"})
        unknown = self.client.post(
            reverse("password_reset"), {"email": "ghost@example.com"})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
