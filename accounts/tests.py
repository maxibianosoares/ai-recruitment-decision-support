from django.test import TestCase
from django.urls import reverse

from .models import User, Role, Permission
from .tokens import email_verification_token


def _make_role(name, permission_codes=None):

    role, _ = Role.objects.get_or_create(name=name)

    for code in (permission_codes or []):
        perm, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code}
        )
        role.permissions.add(perm)

    return role


class RegistrationTests(TestCase):

    def test_valid_registration_creates_unverified_candidate(self):

        resp = self.client.post(reverse("register"), {
            "username": "newcandidate",
            "first_name": "New Candidate",
            "email": "newcandidate@example.com",
            "password1": "S3cure!Passw0rd",
            "password2": "S3cure!Passw0rd",
        })

        self.assertEqual(resp.status_code, 200)

        user = User.objects.get(username="newcandidate")

        self.assertFalse(user.is_verified)
        self.assertEqual(user.role.name, "Candidate")

    def test_cannot_self_assign_privileged_role(self):
        """Even if a malicious POST includes a 'role' field, the
        registration form has no such field, so it is silently
        ignored -- role is always set server-side to Candidate."""

        admin_role = _make_role("Administrator")

        resp = self.client.post(reverse("register"), {
            "username": "sneaky",
            "first_name": "Sneaky User",
            "email": "sneaky@example.com",
            "password1": "S3cure!Passw0rd",
            "password2": "S3cure!Passw0rd",
            "role": admin_role.id,
            "is_verified": "True",
            "is_active": "True",
        })

        self.assertEqual(resp.status_code, 200)

        user = User.objects.get(username="sneaky")

        self.assertEqual(user.role.name, "Candidate")
        self.assertFalse(user.is_verified)

    def test_unverified_account_cannot_login(self):

        self.client.post(reverse("register"), {
            "username": "unverified1",
            "first_name": "Unverified One",
            "email": "unverified1@example.com",
            "password1": "S3cure!Passw0rd",
            "password2": "S3cure!Passw0rd",
        })

        resp = self.client.post(reverse("login"), {
            "username": "unverified1",
            "password": "S3cure!Passw0rd",
        })

        self.assertContains(resp, "verify your email")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verification_link_activates_and_allows_login(self):

        self.client.post(reverse("register"), {
            "username": "verifyme",
            "first_name": "Verify Me",
            "email": "verifyme@example.com",
            "password1": "S3cure!Passw0rd",
            "password2": "S3cure!Passw0rd",
        })

        user = User.objects.get(username="verifyme")

        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)

        resp = self.client.get(
            reverse("verify_email", kwargs={"uidb64": uidb64, "token": token})
        )

        self.assertEqual(resp.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.assertIsNotNone(user.email_verified_at)

        login_resp = self.client.post(reverse("login"), {
            "username": "verifyme",
            "password": "S3cure!Passw0rd",
        })

        self.assertIn("_auth_user_id", self.client.session)

    def test_invalid_verification_token_rejected(self):

        self.client.post(reverse("register"), {
            "username": "badtoken",
            "first_name": "Bad Token",
            "email": "badtoken@example.com",
            "password1": "S3cure!Passw0rd",
            "password2": "S3cure!Passw0rd",
        })

        user = User.objects.get(username="badtoken")

        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

        resp = self.client.get(
            reverse(
                "verify_email",
                kwargs={"uidb64": uidb64, "token": "not-a-real-token"}
            )
        )

        self.assertContains(resp, "invalid or has expired")

        user.refresh_from_db()
        self.assertFalse(user.is_verified)


class RoleBasedAccessTests(TestCase):

    def setUp(self):

        self.candidate_role = _make_role("Candidate")

        self.hr_role = _make_role("HR Officer", ["recruitment_manage"])

        self.candidate_user = User.objects.create_user(
            username="cand1", password="pass12345", email="cand1@x.com",
            role=self.candidate_role, is_verified=True
        )

        self.hr_user = User.objects.create_user(
            username="hr1", password="pass12345", email="hr1@x.com",
            role=self.hr_role, is_verified=True
        )

    def test_candidate_forbidden_from_create_job(self):

        self.client.login(username="cand1", password="pass12345")

        resp = self.client.get(reverse("create_job"))

        self.assertEqual(resp.status_code, 403)

    def test_candidate_forbidden_from_ranking(self):

        self.client.login(username="cand1", password="pass12345")

        for url_name in ("candidate_ranking", "ranking_jobs"):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403, url_name)

    def test_hr_can_access_create_job(self):

        self.client.login(username="hr1", password="pass12345")

        resp = self.client.get(reverse("create_job"))

        self.assertEqual(resp.status_code, 200)

    def test_hr_can_access_ranking(self):

        self.client.login(username="hr1", password="pass12345")

        resp = self.client.get(reverse("candidate_ranking"))

        self.assertEqual(resp.status_code, 200)
