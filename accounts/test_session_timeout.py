"""
Regression test for the 2026-09-27 session-security fix in
core/settings.py: SESSION_EXPIRE_AT_BROWSER_CLOSE, SESSION_COOKIE_AGE,
and SESSION_SAVE_EVERY_REQUEST were previously unset (Django defaults:
no browser-close logout, 2-week fixed session age, no idle-based
expiry reset). This confirms the settings actually take effect on a
real login response's session cookie, not just that they're present
in settings.py.

Does not touch login/authentication logic itself -- login_view() in
accounts/views.py is exercised as-is, unmodified.
"""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from .models import User


class SessionTimeoutSettingsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="sessiontestuser",
            password="Str0ngP@ssw0rd!",
            email="sessiontestuser@example.com",
            is_verified=True,
        )

    def test_settings_configured_as_expected(self):
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1200)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_login_session_cookie_has_no_persistent_expiry(self):
        """
        SESSION_EXPIRE_AT_BROWSER_CLOSE=True means Django sends the
        session cookie WITHOUT an explicit Expires/Max-Age attribute
        -- that is what makes it a browser "session cookie" that the
        browser discards on close, instead of a persistent cookie
        that survives a restart (the exact behavior reported: staying
        logged in after closing the browser).
        """
        response = self.client.post(
            reverse("login"),
            {"email": "sessiontestuser@example.com", "password": "Str0ngP@ssw0rd!"},
        )

        session_cookie = response.cookies.get("sessionid")

        self.assertIsNotNone(session_cookie)
        # A browser-session cookie has an empty max-age/expires --
        # Django's SessionMiddleware only sets these when the session
        # is meant to outlive the browser.
        self.assertEqual(session_cookie["max-age"], "")
        self.assertEqual(session_cookie["expires"], "")

    def test_session_expiry_age_matches_idle_timeout(self):
        """
        request.session.get_expiry_age() reflects SESSION_COOKIE_AGE
        when no per-session override is set -- this is the value that
        governs the 20-minute idle timeout end-to-end.
        """
        self.client.post(
            reverse("login"),
            {"email": "sessiontestuser@example.com", "password": "Str0ngP@ssw0rd!"},
        )

        session = self.client.session

        self.assertEqual(session.get_expiry_age(), 1200)