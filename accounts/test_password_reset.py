"""
TASK K (2026-10-07): Forgot Password / Password Reset tests.

Covers the forgot-password page, registered vs unregistered email,
the reset link/token, a valid reset, invalid / expired / already-used
tokens, password-confirmation mismatch, logging in with the new
password, and the security / privacy behaviour (no account
enumeration, no Host-header poisoning, mail failure never changes the
response).
"""

import re
from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

OLD_PASSWORD = "OldPassw0rd!"
NEW_PASSWORD = "BrandNewPass1!"
SITE = "https://recruit.example.org"


def _link_from(message):
    """Extract the reset link (absolute URL) from an outgoing email."""
    match = re.search(r"https?://\S+/accounts/reset/\S+", message.body)
    assert match, f"no reset link in email body:\n{message.body}"
    return match.group(0)


def _path_of(link):
    return "/" + link.split("/", 3)[3]


@override_settings(SITE_URL=SITE, PASSWORD_RESET_TIMEOUT=3600)
class PasswordResetTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="maria",
            email="maria@example.com",
            password=OLD_PASSWORD,
            first_name="Maria",
            is_verified=True,
        )
        self.forgot_url = reverse("password_reset")

    # ---- helpers -------------------------------------------------
    def _request_link(self, email="maria@example.com"):
        self.client.post(self.forgot_url, {"email": email})
        self.assertEqual(len(mail.outbox), 1)
        return _link_from(mail.outbox[0])

    def _open_reset_form(self, link):
        """Follow the link; Django redirects to .../set-password/."""
        return self.client.get(_path_of(link), follow=True)

    # ---- forgot-password page -----------------------------------
    def test_forgot_password_page_renders(self):
        resp = self.client.get(self.forgot_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Forgot your password?")
        self.assertContains(resp, 'name="email"')
        self.assertContains(resp, "csrfmiddlewaretoken")

    def test_login_page_links_to_forgot_password(self):
        resp = self.client.get(reverse("login"))
        self.assertContains(resp, reverse("password_reset"))
        self.assertContains(resp, "Forgot your password?")

    def test_invalid_email_format_is_rejected_without_sending(self):
        resp = self.client.post(self.forgot_url, {"email": "not-an-email"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    # ---- registered / unregistered email ------------------------
    def test_registered_email_sends_one_reset_email(self):
        resp = self.client.post(self.forgot_url, {"email": "maria@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["maria@example.com"])
        self.assertIn("Reset your password", msg.subject)
        self.assertIn("Maria", msg.body)

    def test_email_lookup_is_case_insensitive(self):
        self.client.post(self.forgot_url, {"email": "MARIA@Example.COM"})
        self.assertEqual(len(mail.outbox), 1)

    def test_unregistered_email_sends_nothing(self):
        resp = self.client.post(self.forgot_url, {"email": "nobody@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_account_gets_no_email(self):
        self.user.is_active = False
        self.user.save()
        self.client.post(self.forgot_url, {"email": "maria@example.com"})
        self.assertEqual(len(mail.outbox), 0)

    # ---- the reset link / token ---------------------------------
    def test_email_link_uses_site_url_and_contains_uid_and_token(self):
        link = self._request_link()
        self.assertTrue(link.startswith(SITE + "/accounts/reset/"))
        self.assertRegex(
            link, r"/accounts/reset/[0-9A-Za-z_\-]+/[0-9a-z]+-[0-9a-f]+/?$"
        )

    def test_email_states_expiry_and_single_use(self):
        self._request_link()
        body = mail.outbox[0].body
        self.assertIn("60 minutes", body)
        self.assertIn("only once", body)

    def test_valid_link_shows_the_new_password_form(self):
        link = self._request_link()
        resp = self._open_reset_form(link)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["validlink"])
        self.assertContains(resp, "Choose a new password")
        self.assertContains(resp, 'name="new_password1"')
        self.assertContains(resp, 'name="new_password2"')

    # ---- valid reset + login with new password ------------------
    def test_valid_reset_changes_password_and_login_uses_it(self):
        link = self._request_link()
        form_page = self._open_reset_form(link)
        post_url = form_page.redirect_chain[-1][0]

        resp = self.client.post(post_url, {
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(resp, reverse("password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(OLD_PASSWORD))

        complete = self.client.get(reverse("password_reset_complete"))
        self.assertContains(complete, "Your password has been changed")

        # Old password no longer logs in ...
        self.client.logout()
        bad = self.client.post(reverse("login"), {
            "email": "maria@example.com", "password": OLD_PASSWORD,
        })
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(bad, "Invalid email or password.")

        # ... the new one does, through the real login view.
        good = self.client.post(reverse("login"), {
            "email": "maria@example.com", "password": NEW_PASSWORD,
        })
        self.assertRedirects(good, reverse("dashboard"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_reset_does_not_log_the_user_in(self):
        link = self._request_link()
        post_url = self._open_reset_form(link).redirect_chain[-1][0]
        self.client.post(post_url, {
            "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        self.assertNotIn("_auth_user_id", self.client.session)

    # ---- confirmation mismatch / weak password ------------------
    def test_password_confirmation_mismatch_is_rejected(self):
        link = self._request_link()
        post_url = self._open_reset_form(link).redirect_chain[-1][0]
        resp = self.client.post(post_url, {
            "new_password1": NEW_PASSWORD,
            "new_password2": "SomethingElse9!",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "didn")  # "didn't match"
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_too_short_password_is_rejected(self):
        link = self._request_link()
        post_url = self._open_reset_form(link).redirect_chain[-1][0]
        resp = self.client.post(post_url, {
            "new_password1": "abc", "new_password2": "abc",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "too short")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_mismatch_does_not_burn_the_link(self):
        """A typo on the form must not use up the one-time token."""
        link = self._request_link()
        post_url = self._open_reset_form(link).redirect_chain[-1][0]
        self.client.post(post_url, {
            "new_password1": NEW_PASSWORD, "new_password2": "nope-nope",
        })
        ok = self.client.post(post_url, {
            "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(ok, reverse("password_reset_complete"))

    # ---- invalid / expired / already-used tokens ----------------
    def test_garbage_token_shows_safe_invalid_page(self):
        uid = re.search(r"/reset/([^/]+)/", self.client.post(
            self.forgot_url, {"email": "maria@example.com"}) and
            _link_from(mail.outbox[0])).group(1)
        resp = self.client.get(
            reverse("password_reset_confirm",
                    kwargs={"uidb64": uid, "token": "abc-123"}),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["validlink"])
        self.assertContains(resp, "invalid or has expired")
        self.assertNotContains(resp, 'name="new_password1"')

    def test_garbage_uid_shows_safe_invalid_page(self):
        resp = self.client.get(
            reverse("password_reset_confirm",
                    kwargs={"uidb64": "zzzz", "token": "abc-123"}),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["validlink"])

    def test_nonexistent_user_uid_shows_safe_invalid_page(self):
        link = self._request_link()
        token = link.rstrip("/").rsplit("/", 1)[1]
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        ghost = urlsafe_base64_encode(force_bytes(999999))
        resp = self.client.get(
            reverse("password_reset_confirm",
                    kwargs={"uidb64": ghost, "token": token}),
            follow=True,
        )
        self.assertFalse(resp.context["validlink"])

    def test_token_for_one_user_does_not_work_for_another(self):
        other = User.objects.create_user(
            username="joao", email="joao@example.com",
            password="Another1Pass!", is_verified=True,
        )
        link = self._request_link()  # maria's token
        token = link.rstrip("/").rsplit("/", 1)[1]
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        resp = self.client.get(
            reverse("password_reset_confirm", kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(other.pk)),
                "token": token,
            }),
            follow=True,
        )
        self.assertFalse(resp.context["validlink"])

    def test_expired_token_is_rejected(self):
        link = self._request_link()
        later = datetime.now() + timedelta(seconds=3601)
        with mock.patch.object(
            PasswordResetTokenGenerator, "_now", return_value=later
        ):
            resp = self.client.get(_path_of(link), follow=True)
        self.assertFalse(resp.context["validlink"])
        self.assertContains(resp, "invalid or has expired")

    def test_token_still_valid_just_before_expiry(self):
        link = self._request_link()
        almost = datetime.now() + timedelta(seconds=3500)
        with mock.patch.object(
            PasswordResetTokenGenerator, "_now", return_value=almost
        ):
            resp = self.client.get(_path_of(link), follow=True)
        self.assertTrue(resp.context["validlink"])

    def test_link_cannot_be_used_twice(self):
        link = self._request_link()
        post_url = self._open_reset_form(link).redirect_chain[-1][0]
        self.client.post(post_url, {
            "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        # A fresh browser opening the same link again.
        self.client.logout()
        from django.test import Client
        again = Client().get(_path_of(link), follow=True)
        self.assertFalse(again.context["validlink"])
        self.assertContains(again, "invalid or has expired")

    def test_older_link_dies_after_a_newer_reset_completes(self):
        old_link = self._request_link()
        mail.outbox.clear()
        new_link = self._request_link()
        post_url = self._open_reset_form(new_link).redirect_chain[-1][0]
        self.client.post(post_url, {
            "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        from django.test import Client
        resp = Client().get(_path_of(old_link), follow=True)
        self.assertFalse(resp.context["validlink"])

    def test_token_dies_when_password_changed_elsewhere(self):
        link = self._request_link()
        self.user.set_password("ChangedElsewhere1!")
        self.user.save()
        resp = self.client.get(_path_of(link), follow=True)
        self.assertFalse(resp.context["validlink"])

    # ---- security / privacy -------------------------------------
    def test_registered_and_unregistered_responses_are_identical(self):
        known = self.client.post(self.forgot_url, {"email": "maria@example.com"})
        unknown = self.client.post(self.forgot_url, {"email": "ghost@example.com"})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        page_known = self.client.get(known.url).content
        page_unknown = self.client.get(unknown.url).content
        # Same page (only the per-request CSRF token may differ).
        strip = lambda b: re.sub(rb'csrfmiddlewaretoken" value="[^"]+"', b"", b)
        self.assertEqual(strip(page_known), strip(page_unknown))

    def test_done_page_does_not_echo_the_email(self):
        resp = self.client.post(
            self.forgot_url, {"email": "maria@example.com"}, follow=True
        )
        self.assertNotContains(resp, "maria@example.com")

    def test_mail_failure_does_not_change_the_response(self):
        """A 500 only for registered emails would reveal they exist."""
        with mock.patch(
            "django.core.mail.message.EmailMultiAlternatives.send",
            side_effect=RuntimeError("SMTP is down"),
        ):
            # Django itself logs the failure (django.contrib.auth)
            # and does not re-raise; our form adds a second safety net.
            with self.assertLogs("django.contrib.auth", "ERROR"):
                known = self.client.post(
                    self.forgot_url, {"email": "maria@example.com"})
        unknown = self.client.post(self.forgot_url, {"email": "ghost@example.com"})
        self.assertRedirects(known, reverse("password_reset_done"))
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)

    @override_settings(ALLOWED_HOSTS=["testserver", "evil.example.com"])
    def test_forged_host_header_cannot_poison_the_link(self):
        self.client.post(
            self.forgot_url, {"email": "maria@example.com"},
            HTTP_HOST="evil.example.com",
        )
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertNotIn("evil.example.com", body)
        self.assertIn(SITE + "/accounts/reset/", body)

    def test_token_is_not_left_in_the_address_bar_of_the_form(self):
        link = self._request_link()
        resp = self.client.get(_path_of(link))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("set-password", resp.url)
        self.assertNotIn(link.rstrip("/").rsplit("/", 1)[1], resp.url)

    def test_forgot_password_requires_csrf(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        resp = strict.post(self.forgot_url, {"email": "maria@example.com"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_get_does_not_send_email(self):
        self.client.get(self.forgot_url)
        self.assertEqual(len(mail.outbox), 0)

    def test_pages_are_reachable_when_logged_out_and_use_site_layout(self):
        for name in ("password_reset", "password_reset_done",
                     "password_reset_complete"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, "page-card", msg_prefix=name)
            self.assertContains(resp, "btn-tl", msg_prefix=name)