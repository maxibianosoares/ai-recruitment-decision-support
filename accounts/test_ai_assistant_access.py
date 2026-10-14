"""
TASK P (2026-10-14): the AI Assistant (RAG chat page + /api/rag/ask/)
is restricted to administrators (roles "Super Admin" and
"Administrator"). Everyone else -- Candidate, HR Officer, Reviewer,
Interviewer, a user with no role, a visitor who is not logged in --
must be refused SERVER-SIDE, not just have the link hidden.
"""

import json
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Permission, Role, User

STATIC_OK = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

ASK = "ai_engine.views.rag_pipeline"
ALLOWED = ["Super Admin", "Administrator"]
DENIED = ["HR Officer", "Reviewer", "Interviewer", "Candidate"]


def _user(role_name, n):
    role = Role.objects.get(name=role_name) if role_name else None
    return User.objects.create_user(
        username=f"u{n}", email=f"u{n}@example.com",
        password="Str0ngP@ssw0rd!", is_verified=True, role=role,
    )


@override_settings(STORAGES=STATIC_OK)
class AiAssistantAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", verbosity=0)

    def _post(self, question="What is the age limit?"):
        return self.client.post(
            reverse("ask_rag"),
            data=json.dumps({"question": question}),
            content_type="application/json",
        )

    # ---- seeding -------------------------------------------------
    def test_only_admin_roles_get_the_permission(self):
        perm = Permission.objects.get(code="ai_assistant_use")
        holders = set(
            Role.objects.filter(permissions=perm).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(holders, set(ALLOWED))

    def test_seed_roles_is_idempotent(self):
        call_command("seed_roles", verbosity=0)
        call_command("seed_roles", verbosity=0)
        self.assertEqual(
            Permission.objects.filter(code="ai_assistant_use").count(), 1
        )

    # ---- visitors not logged in ----------------------------------
    def test_anonymous_page_redirects_to_login(self):
        resp = self.client.get(reverse("rag_chat"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_anonymous_api_is_refused_and_pipeline_not_called(self):
        with mock.patch(ASK) as pipeline:
            resp = self._post()
        self.assertEqual(resp.status_code, 302)
        pipeline.ask.assert_not_called()

    # ---- everyone who must be refused ----------------------------
    def test_non_admin_roles_get_403_on_page_and_api(self):
        for i, role_name in enumerate(DENIED + [None]):
            with self.subTest(role=role_name):
                self.client.logout()
                self.client.force_login(_user(role_name, i))
                self.assertEqual(
                    self.client.get(reverse("rag_chat")).status_code, 403
                )
                with mock.patch(ASK) as pipeline:
                    resp = self._post()
                self.assertEqual(resp.status_code, 403)
                pipeline.ask.assert_not_called()

    def test_403_also_applies_to_wrong_http_method(self):
        # A candidate must get 403 (not 405 or the page) even when
        # using the "wrong" method: access is checked first.
        self.client.force_login(_user("Candidate", 1))
        self.assertEqual(
            self.client.get(reverse("ask_rag")).status_code, 403
        )

    # ---- administrators ------------------------------------------
    def test_admin_roles_can_open_the_page(self):
        for i, role_name in enumerate(ALLOWED):
            with self.subTest(role=role_name):
                self.client.logout()
                self.client.force_login(_user(role_name, 10 + i))
                resp = self.client.get(reverse("rag_chat"))
                self.assertEqual(resp.status_code, 200)

    def test_admin_roles_can_ask_a_question(self):
        for i, role_name in enumerate(ALLOWED):
            with self.subTest(role=role_name):
                self.client.logout()
                self.client.force_login(_user(role_name, 20 + i))
                with mock.patch(ASK) as pipeline:
                    pipeline.ask.return_value = {"answer": "42"}
                    resp = self._post()
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), {"answer": "42"})
                pipeline.ask.assert_called_once()

    def test_admin_still_gets_input_validation(self):
        self.client.force_login(_user("Administrator", 30))
        with mock.patch(ASK):
            self.assertEqual(self._post("").status_code, 400)
            self.assertEqual(self._post("x" * 1001).status_code, 400)

    def test_django_superuser_without_a_role_is_refused(self):
        # Same rule as every other permission-gated page in this app
        # (e.g. user management): access comes from the ROLE.
        su = User.objects.create_superuser(
            username="su", email="su@example.com",
            password="Str0ngP@ssw0rd!", is_verified=True,
        )
        self.client.force_login(su)
        self.assertEqual(
            self.client.get(reverse("rag_chat")).status_code, 403
        )

    def test_permission_can_be_granted_to_another_role_later(self):
        hr = Role.objects.get(name="HR Officer")
        hr.permissions.add(Permission.objects.get(code="ai_assistant_use"))
        self.client.force_login(_user("HR Officer", 40))
        self.assertEqual(
            self.client.get(reverse("rag_chat")).status_code, 200
        )

    # ---- the link ------------------------------------------------
    def test_sidebar_link_only_for_admins(self):
        link = reverse("rag_chat")
        for i, role_name in enumerate(ALLOWED):
            self.client.logout()
            self.client.force_login(_user(role_name, 50 + i))
            html = self.client.get(reverse("job_list")).content.decode()
            self.assertIn(f'href="{link}"', html, role_name)
        for i, role_name in enumerate(DENIED):
            self.client.logout()
            self.client.force_login(_user(role_name, 60 + i))
            html = self.client.get(reverse("job_list")).content.decode()
            self.assertNotIn(f'href="{link}"', html, role_name)

    def test_link_hidden_from_anonymous_visitors(self):
        link = reverse("rag_chat")
        for name in ("job_list", "home"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertNotIn(f'href="{link}"', html, name)

    def test_home_page_button_only_for_admins(self):
        link = reverse("rag_chat")
        self.client.force_login(_user("Administrator", 70))
        self.assertIn(
            f'href="{link}"',
            self.client.get(reverse("home")).content.decode(),
        )
        self.client.logout()
        self.client.force_login(_user("Candidate", 71))
        self.assertNotIn(
            f'href="{link}"',
            self.client.get(reverse("home")).content.decode(),
        )