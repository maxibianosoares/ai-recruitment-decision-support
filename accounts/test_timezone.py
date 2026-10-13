"""
TASK N (2026-10-13): dates/times are displayed in the viewer's own
timezone (browser cookie `user_tz`), while the database keeps UTC.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .middleware import (
    TIMEZONE_COOKIE, UserTimezoneMiddleware, parse_timezone,
)
from .models import EmailLog, User

# 2026-10-13 04:48 UTC == 13:48 in Seoul (UTC+9). Dili is also UTC+9,
# so tests that must tell zones apart also use London and Sao Paulo.
UTC_MOMENT = dt.datetime(2026, 10, 13, 4, 48, tzinfo=dt.timezone.utc)

STATIC_OK = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _render(request_tz_cookie):
    """Run the middleware and render a datetime inside the request."""
    request = RequestFactory().get("/")
    if request_tz_cookie is not None:
        request.COOKIES[TIMEZONE_COOKIE] = request_tz_cookie
    out = {}

    def view(req):
        out["text"] = Template(
            '{{ t|date:"Y-m-d H:i" }}'
        ).render(Context({"t": UTC_MOMENT}))
        out["tz"] = str(timezone.get_current_timezone())
        from django.http import HttpResponse
        return HttpResponse("ok")

    UserTimezoneMiddleware(view)(request)
    return out


class ParseTimezoneTests(TestCase):

    def test_valid_names(self):
        for name in ("Asia/Seoul", "Asia/Dili", "UTC",
                     "America/Argentina/Buenos_Aires", "Etc/GMT+9"):
            self.assertIsNotNone(parse_timezone(name), name)

    def test_invalid_or_hostile_values_are_rejected(self):
        for bad in (None, "", "Not/AZone", "../../etc/passwd",
                    "Asia/Seoul; evil", "Asia//Seoul", "a" * 100,
                    "<script>", "Asia/Seoul\n", "/etc/localtime"):
            self.assertIsNone(parse_timezone(bad), repr(bad))


class MiddlewareTests(TestCase):

    def test_cookie_zone_is_used_for_display(self):
        self.assertEqual(
            _render("Asia/Seoul")["text"], "2026-10-13 13:48"
        )
        self.assertEqual(
            _render("America/Sao_Paulo")["text"], "2026-10-13 01:48"
        )
        self.assertEqual(
            _render("Europe/London")["text"], "2026-10-13 05:48"
        )

    @override_settings(TIME_ZONE="Asia/Dili")
    def test_missing_cookie_uses_default_zone(self):
        res = _render(None)
        self.assertEqual(res["tz"], "Asia/Dili")
        self.assertEqual(res["text"], "2026-10-13 13:48")  # Dili = UTC+9

    @override_settings(TIME_ZONE="UTC")
    def test_invalid_cookie_falls_back_without_error(self):
        res = _render("../../etc/passwd")
        self.assertEqual(res["tz"], "UTC")
        self.assertEqual(res["text"], "2026-10-13 04:48")

    def test_zone_does_not_leak_into_the_next_request(self):
        _render("Asia/Seoul")
        self.assertNotEqual(
            str(timezone.get_current_timezone()), "Asia/Seoul"
        )
        self.assertEqual(
            _render("Europe/London")["text"], "2026-10-13 05:48"
        )

    def test_zone_is_reset_even_if_the_view_raises(self):
        request = RequestFactory().get("/")
        request.COOKIES[TIMEZONE_COOKIE] = "Asia/Seoul"

        def boom(req):
            raise ValueError("x")

        with self.assertRaises(ValueError):
            UserTimezoneMiddleware(boom)(request)
        self.assertNotEqual(
            str(timezone.get_current_timezone()), "Asia/Seoul"
        )

    def test_database_value_stays_utc(self):
        row = EmailLog.objects.create(recipient="a@example.com")
        EmailLog.objects.filter(pk=row.pk).update(created_at=UTC_MOMENT)
        row.refresh_from_db()
        self.assertEqual(row.created_at.utcoffset(), dt.timedelta(0))
        self.assertEqual(row.created_at, UTC_MOMENT)


@override_settings(STORAGES=STATIC_OK, TIME_ZONE="UTC")
class PageAndAdminTests(TestCase):

    def test_page_shows_the_zone_and_includes_the_cookie_script(self):
        self.client.cookies[TIMEZONE_COOKIE] = "Asia/Seoul"
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn("Times shown in Asia/Seoul", html)
        self.assertIn("user_tz=", html)
        self.assertIn("Intl.DateTimeFormat", html)

    def test_page_without_cookie_shows_default_zone(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn("Times shown in UTC", html)

    def test_admin_email_log_shows_viewer_local_time(self):
        admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw123456"
        )
        self.client.force_login(admin)
        row = EmailLog.objects.create(
            kind="password_reset", recipient="seen@example.com"
        )
        EmailLog.objects.filter(pk=row.pk).update(created_at=UTC_MOMENT)
        url = reverse("admin:accounts_emaillog_changelist")

        self.client.cookies[TIMEZONE_COOKIE] = "Asia/Seoul"
        seoul = self.client.get(url).content.decode()
        self.assertIn("1:48 p.m.", seoul)
        self.assertNotIn("4:48 a.m.", seoul)

        self.client.cookies[TIMEZONE_COOKIE] = "UTC"
        utc = self.client.get(url).content.decode()
        self.assertIn("4:48 a.m.", utc)
