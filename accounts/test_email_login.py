"""
TASK F (2026-10-02): login by email + password only (no username
field on the login form anymore -- see login_view() in
accounts/views.py and accounts/templates/accounts/login.html).

The User model itself is UNCHANGED (still has `username`, still the
AUTH_USER_MODEL's USERNAME_FIELD) -- only the login view's lookup
changed: it resolves the submitted email to that account's username
before calling Django's existing authenticate(). This file is a
regression test for that resolution step specifically, so it does not
duplicate accounts/tests.py's existing unverified/verified-login
coverage (which already posts "email" to the login view).
"""

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import User


class EmailLoginTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="maria.candidate",
            password="Str0ngP@ssw0rd!",
            email="maria@example.com",
            is_verified=True,
        )

    def test_correct_email_and_password_logs_in(self):
        resp = self.client.post(reverse("login"), {
            "email": "maria@example.com",
            "password": "Str0ngP@ssw0rd!",
        })
        self.assertIn("_auth_user_id", self.client.session)
        self.assertRedirects(resp, reverse("dashboard"))

    def test_email_lookup_is_case_insensitive(self):
        resp = self.client.post(reverse("login"), {
            "email": "MARIA@Example.com",
            "password": "Str0ngP@ssw0rd!",
        })
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_rejected(self):
        resp = self.client.post(reverse("login"), {
            "email": "maria@example.com",
            "password": "wrong-password",
        })
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(resp, "Invalid email or password.")

    def test_unknown_email_rejected_with_generic_message(self):
        """
        Must fail the same way as a wrong password -- not reveal
        whether the email exists at all.
        """
        resp = self.client.post(reverse("login"), {
            "email": "nobody@example.com",
            "password": "Str0ngP@ssw0rd!",
        })
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(resp, "Invalid email or password.")

    def test_username_field_no_longer_accepted(self):
        """
        Posting the OLD field name ("username") must not log anyone
        in -- confirms the form was actually switched, not just the
        template label.
        """
        resp = self.client.post(reverse("login"), {
            "username": "maria.candidate",
            "password": "Str0ngP@ssw0rd!",
        })
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_email_rejected_at_the_database_level(self):
        """
        TASK F follow-up (2026-10-02): email is now USERNAME_FIELD and
        unique=True on the model (see models.py), so two accounts
        sharing an email can no longer exist at all -- this replaces
        the earlier version of this test, which exercised login's
        handling of an ambiguous duplicate back when email had no
        DB-level unique constraint yet.
        """
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="maria.second",
                    password="Other!Pass123",
                    email="maria@example.com",
                    is_verified=True,
                )

    def test_username_can_be_duplicated(self):
        """
        The actual TASK F follow-up ask: username must NOT be unique
        anymore (registration/user-creation was rejecting otherwise-
        valid accounts just because someone else already had that
        display name).
        """
        User.objects.create_user(
            username="maria.candidate",
            password="Other!Pass123",
            email="someoneelse@example.com",
            is_verified=True,
        )
        self.assertEqual(
            User.objects.filter(username="maria.candidate").count(), 2
        )

    def test_blank_email_rejected(self):
        resp = self.client.post(reverse("login"), {
            "email": "",
            "password": "Str0ngP@ssw0rd!",
        })
        self.assertNotIn("_auth_user_id", self.client.session)