"""
TASK N (2026-10-13): show every date/time in the viewer's own timezone.

The database always stores UTC (USE_TZ = True) -- that is correct and
stays. What was wrong is only the DISPLAY: Django formats times in
settings.TIME_ZONE, which was 'UTC', so a user in Seoul who acted at
13:48 saw 04:48.

How it works
    1. A tiny script in templates/base.html reads the browser's IANA
       timezone (e.g. "Asia/Seoul") and stores it in the cookie
       `user_tz`.
    2. This middleware validates that cookie and calls
       timezone.activate() for the request. Django then converts every
       template date/time ({{ x|date:... }}), every form and the whole
       Django Admin to that zone automatically.
    3. A missing / unknown / tampered cookie falls back to
       settings.TIME_ZONE (Asia/Dili by default), never an error.

Security: the cookie value is only ever passed to zoneinfo.ZoneInfo
after a strict character/length check, so it can't be used for path
tricks, and an invalid value is silently ignored.
"""

import re
from zoneinfo import ZoneInfo

from django.utils import timezone

TIMEZONE_COOKIE = "user_tz"

# IANA names look like "Asia/Seoul", "America/Argentina/Buenos_Aires",
# "Etc/GMT+9". Nothing else is accepted.
_TZ_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$")


def parse_timezone(value):
    """Return a ZoneInfo for a valid IANA name, else None."""
    if not value or len(value) > 64 or not _TZ_NAME.match(value):
        return None
    try:
        return ZoneInfo(value)
    except Exception:  # unknown key, or no tz database on this host
        return None


class UserTimezoneMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz = parse_timezone(request.COOKIES.get(TIMEZONE_COOKIE))
        if tz is not None:
            timezone.activate(tz)
        else:
            # Threads are reused: never inherit the previous request's
            # timezone.
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
