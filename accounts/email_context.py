"""
TASK M (2026-10-12): labels an outgoing email for the EmailLog.

Django's send_mail() has no place to say "this is a password reset".
Rather than guessing from the subject line (fragile) or rewriting every
caller, a caller wraps its send in a context manager:

    with email_context(EmailKind.REGISTRATION):
        send_mail(...)

BrevoAPIEmailBackend reads the label while it logs the message. A
ContextVar is used (not a global) so concurrent requests/threads never
see each other's label. Outside any `with` block the kind is "other".
"""

from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("email_log_context", default=None)


@contextmanager
def email_context(kind, related_application_id=None):
    token = _current.set(
        {"kind": kind, "related_application_id": related_application_id}
    )
    try:
        yield
    finally:
        _current.reset(token)


def current_email_context():
    return _current.get() or {"kind": "other", "related_application_id": None}
