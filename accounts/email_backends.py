"""
Django email backend that sends via Brevo's HTTPS API instead of
SMTP -- necessary because Render's free web services block ALL
outbound SMTP ports (25, 465, 587), which would block Brevo's SMTP
relay exactly the same way it blocked Gmail's.

Drop-in replacement: works with Django's existing send_mail() /
EmailMessage as-is. accounts/views_auth.py needs ZERO changes --
it already calls send_mail(), which routes through whichever
EMAIL_BACKEND is configured.

Setup:
    EMAIL_BACKEND=accounts.email_backends.BrevoAPIEmailBackend
    BREVO_API_KEY=<your Brevo API key, from Brevo dashboard>

Brevo free tier: 300 emails/day, no expiration, works with any
verified sender address (does not require a custom domain), and
can send to arbitrary recipients -- unlike some competitors whose
free tier only delivers to the account owner's own address.

TASK L (2026-10-12): transient-failure retry.
    A single Brevo API call can fail for reasons that have nothing to
    do with the message itself (a timeout, a dropped connection, HTTP
    429 "slow down", HTTP 5xx on Brevo's side). Before this change
    such a blip meant the email was simply lost -- and for password
    reset the user is deliberately shown the same "check your inbox"
    page either way, so nobody noticed. Now each message is retried a
    few times with a short exponential back-off, inside a hard time
    budget (gunicorn's request timeout is 120 s; the budget keeps a
    web request well below it). Permanent errors (HTTP 400/401/403/
    422 ...: bad key, unverified sender, invalid address) are NOT
    retried -- retrying cannot fix them. Tunable, all optional:

        BREVO_MAX_ATTEMPTS              default 3
        BREVO_RETRY_BACKOFF_SECONDS     default 1.0  (1 s, 2 s, ...)
        BREVO_ATTEMPT_TIMEOUT_SECONDS   default 8
        BREVO_TOTAL_BUDGET_SECONDS      default 20

    Note: if an attempt times out AFTER Brevo already accepted the
    message, the retry can deliver a duplicate. For the emails this
    system sends (verification, password reset, screening result) a
    rare duplicate is far better than a lost email.

TASK M (2026-10-12): delivery log.
    Every message handled by this backend is recorded in
    accounts.EmailLog (pending -> sent / failed, attempts, error,
    Brevo messageId). Metadata only -- never the body. See
    accounts/email_context.py for how callers label the kind.
"""

import logging
import time

import requests

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils import timezone

from .email_context import current_email_context


logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

# HTTP statuses worth retrying: request timeout, too many requests,
# and every server-side (5xx) error. Everything else (4xx) is a
# permanent problem with the request or the account.
RETRYABLE_STATUS_CODES = frozenset({408, 429})


class BrevoSendError(RuntimeError):
    """RuntimeError (so existing handlers keep working) that also
    remembers how many attempts were made, for the EmailLog."""

    def __init__(self, message, attempts=0):
        super().__init__(message)
        self.attempts = attempts


def _setting(name, default):
    return getattr(settings, name, default)


def _is_retryable(error, status):
    if isinstance(
        error,
        (requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    ):
        return True
    if status is None:
        return False
    return status in RETRYABLE_STATUS_CODES or status >= 500


def _brevo_detail(error):
    """Brevo's own error code/message (never contains the API key --
    the key travels in the "api-key" header, not the URL or body)."""
    response = error.response
    if response is None:
        return f" Error: {type(error).__name__}."
    try:
        body = response.json()
        return (
            f" Brevo response: code={body.get('code')} "
            f"message={body.get('message')}"
        )
    except ValueError:
        return f" Brevo response: {response.text[:200]}"


def _provider_message_id(response):
    try:
        return str(response.json().get("messageId", ""))[:255]
    except (ValueError, AttributeError):
        return ""


# --- TASK M: EmailLog bookkeeping -----------------------------------
# Logging must NEVER be the reason an email is not sent, so every
# database write below is wrapped: if the log cannot be written, the
# problem is logged and sending carries on exactly as before.

def _log_start(message):
    try:
        from .models import EmailLog

        ctx = current_email_context()
        kind = ctx["kind"]
        if kind not in EmailLog.Kind.values:
            kind = EmailLog.Kind.OTHER
        return EmailLog.objects.create(
            kind=kind,
            recipient=", ".join(message.to)[:254],
            subject=(message.subject or "")[:255],
            related_application_id=ctx["related_application_id"],
        )
    except Exception:
        logger.exception("EmailLog: could not create log row")
        return None


def _log_finish(entry, *, ok, attempts, error="", provider_id=""):
    if entry is None:
        return
    try:
        from .models import EmailLog

        entry.attempts = attempts
        if ok:
            entry.status = EmailLog.Status.SENT
            entry.sent_at = timezone.now()
            entry.provider_message_id = provider_id
            entry.error = ""
        else:
            entry.status = EmailLog.Status.FAILED
            entry.error = error[:2000]
        entry.save()
    except Exception:
        logger.exception("EmailLog: could not update log row")


class BrevoAPIEmailBackend(BaseEmailBackend):

    def _post_with_retry(self, message, api_key):
        """
        Send one message. Returns (attempts_made, provider_message_id)
        on success; raises BrevoSendError (a RuntimeError) once the
        failure is permanent or the attempts / time budget are used up.
        """
        max_attempts = max(1, int(_setting("BREVO_MAX_ATTEMPTS", 3)))
        backoff = float(_setting("BREVO_RETRY_BACKOFF_SECONDS", 1.0))
        attempt_timeout = float(_setting("BREVO_ATTEMPT_TIMEOUT_SECONDS", 8))
        budget = float(_setting("BREVO_TOTAL_BUDGET_SECONDS", 20))

        payload = {
            "sender": {"email": message.from_email},
            "to": [{"email": addr} for addr in message.to],
            "subject": message.subject,
            "textContent": message.body,
        }

        started = time.monotonic()
        attempts_made = 0
        last_error = None
        last_status = None

        for attempt in range(1, max_attempts + 1):

            remaining = budget - (time.monotonic() - started)

            if attempt > 1 and remaining <= 1:
                break  # out of time budget -- stop retrying

            attempts_made = attempt

            try:
                response = requests.post(
                    BREVO_SEND_URL,
                    headers={
                        "api-key": api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=max(1.0, min(attempt_timeout, remaining)),
                )
                response.raise_for_status()
                if attempt > 1:
                    logger.info(
                        "Brevo email sent on attempt %d/%d",
                        attempt, max_attempts,
                    )
                return attempt, _provider_message_id(response)

            except requests.exceptions.RequestException as e:

                last_error = e
                last_status = (
                    e.response.status_code
                    if e.response is not None else None
                )

                if not _is_retryable(e, last_status):
                    break  # permanent -- retrying cannot help

                if attempt < max_attempts:
                    remaining = budget - (time.monotonic() - started)
                    delay = min(
                        backoff * (2 ** (attempt - 1)),
                        max(0.0, remaining - 1),
                    )
                    logger.warning(
                        "Brevo send attempt %d/%d failed (%s); "
                        "retrying in %.1fs",
                        attempt, max_attempts,
                        last_status or type(e).__name__, delay,
                    )
                    if delay > 0:
                        time.sleep(delay)

        status = last_status if last_status is not None else "unknown"
        raise BrevoSendError(
            f"Brevo email send failed (HTTP {status}) after "
            f"{attempts_made} attempt(s)."
            f"{_brevo_detail(last_error)}",
            attempts=attempts_made,
        ) from None

    def send_messages(self, email_messages):

        if not email_messages:
            return 0

        api_key = getattr(settings, "BREVO_API_KEY", "")

        if not api_key:
            error = (
                "BREVO_API_KEY is not set, but EMAIL_BACKEND is "
                "configured to use Brevo."
            )
            for message in email_messages:
                _log_finish(
                    _log_start(message), ok=False, attempts=0, error=error
                )
            if not self.fail_silently:
                raise RuntimeError(error)
            return 0

        sent_count = 0

        for message in email_messages:

            entry = _log_start(message)

            try:
                attempts, provider_id = self._post_with_retry(
                    message, api_key
                )
                _log_finish(
                    entry, ok=True, attempts=attempts,
                    provider_id=provider_id,
                )
                sent_count += 1

            except RuntimeError as e:

                logger.error("%s", e)
                _log_finish(
                    entry, ok=False,
                    attempts=getattr(e, "attempts", 0), error=str(e),
                )

                if not self.fail_silently:
                    raise

        return sent_count
