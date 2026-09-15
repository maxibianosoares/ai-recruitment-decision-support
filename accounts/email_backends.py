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
"""

import requests

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoAPIEmailBackend(BaseEmailBackend):

    def send_messages(self, email_messages):

        if not email_messages:
            return 0

        api_key = getattr(settings, "BREVO_API_KEY", "")

        if not api_key:
            if not self.fail_silently:
                raise RuntimeError(
                    "BREVO_API_KEY is not set, but EMAIL_BACKEND is "
                    "configured to use Brevo."
                )
            return 0

        sent_count = 0

        for message in email_messages:

            payload = {
                "sender": {"email": message.from_email},
                "to": [{"email": addr} for addr in message.to],
                "subject": message.subject,
                "textContent": message.body,
            }

            try:

                response = requests.post(
                    BREVO_SEND_URL,
                    headers={
                        "api-key": api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=10,
                )

                response.raise_for_status()

                sent_count += 1

            except requests.exceptions.RequestException as e:

                if not self.fail_silently:
                    # Unlike model_config.py's online-Gemma backend,
                    # the API key here has always been sent via the
                    # "api-key" HEADER, never the URL -- so unlike
                    # that case, it's safe to surface Brevo's actual
                    # JSON error body (it only ever contains Brevo's
                    # own error code/message, never the key itself).
                    # Withholding it was over-cautious and made this
                    # 401 undiagnosable from logs alone.
                    status = getattr(e.response, "status_code", "unknown")

                    brevo_detail = ""
                    if e.response is not None:
                        try:
                            body = e.response.json()
                            brevo_detail = (
                                f" Brevo response: code={body.get('code')} "
                                f"message={body.get('message')}"
                            )
                        except ValueError:
                            brevo_detail = f" Brevo response: {e.response.text[:200]}"

                    raise RuntimeError(
                        f"Brevo email send failed (HTTP {status})."
                        f"{brevo_detail}"
                    ) from None

        return sent_count