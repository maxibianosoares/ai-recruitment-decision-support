"""
TASK O (2026-10-13): a successful login lands on /jobs/ (job list).
The dashboard is still reachable from the navigation bar.
"""

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

STATIC_OK = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@override_settings(STORAGES=STATIC_OK)
class LoginRedirectTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="maria", email="maria@example.com",
            password="Str0ngP@ssw0rd!", is_verified=True,
        )
        self.creds = {
            "email": "maria@example.com", "password": "Str0ngP@ssw0rd!",
        }

    def test_login_redirects_to_jobs_url(self):
        resp = self.client.post(reverse("login"), self.creds)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/jobs/")

    def test_job_list_page_loads_after_login(self):
        resp = self.client.post(reverse("login"), self.creds, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.redirect_chain[-1][0], "/jobs/")

    def test_superuser_also_lands_on_jobs(self):
        User.objects.create_superuser(
            username="root", email="root@example.com",
            password="Str0ngP@ssw0rd!", is_verified=True,
        )
        resp = self.client.post(reverse("login"), {
            "email": "root@example.com", "password": "Str0ngP@ssw0rd!",
        })
        self.assertEqual(resp["Location"], "/jobs/")

    def test_failed_login_does_not_redirect(self):
        resp = self.client.post(reverse("login"), {
            "email": "maria@example.com", "password": "wrong",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unverified_user_is_not_logged_in(self):
        User.objects.filter(pk=self.user.pk).update(is_verified=False)
        resp = self.client.post(reverse("login"), self.creds)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_dashboard_still_works_when_opened_directly(self):
        self.client.post(reverse("login"), self.creds)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_django_default_login_redirect_matches(self):
        self.assertEqual(settings.LOGIN_REDIRECT_URL, "/jobs/")