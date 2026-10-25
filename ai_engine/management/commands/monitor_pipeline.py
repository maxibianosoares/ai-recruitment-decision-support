"""
Checks the screening pipeline and emails the administrator.

    python manage.py monitor_pipeline                # for a 30-minute schedule
    python manage.py monitor_pipeline --dry-run      # print, send nothing
    python manage.py monitor_pipeline --format json  # the numbers only

Two kinds of email, both counts only (see talent/pipeline_monitor.py):

  ALERT          sent only when something needs attention (queue stalled,
                 stuck application, AI failures). The same alert is not sent
                 again for --repeat-hours (default 6) unless the numbers in
                 it change.
  DAILY SUMMARY  one per day, the first time the command runs at or after
                 --digest-hour (local time, default 9), whether or not
                 anything is wrong.

Recipients: --to, else MONITOR_RECIPIENTS, else HITL_REPORT_RECIPIENTS.
Exit code is non-zero only if an email could not be sent; finding a problem
is not an error. Nothing is written except the normal EmailLog rows.
"""

import os
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.utils import timezone

from accounts.email_context import email_context
from accounts.models import EmailLog
from talent import pipeline_monitor as M


def _recipients(option_values):
    raw = option_values or (
        os.environ.get("MONITOR_RECIPIENTS", "")
        or os.environ.get("HITL_REPORT_RECIPIENTS", "")
    ).split(",")
    out = []
    for value in raw:
        value = value.strip()
        if value and value not in out:
            try:
                validate_email(value)
            except ValidationError:
                raise CommandError(f"Not a valid email address: {value!r}")
            out.append(value)
    return out


class Command(BaseCommand):

    help = "Check the screening pipeline; email the administrator on problems."

    def add_arguments(self, parser):
        parser.add_argument("--to", action="append", default=[])
        parser.add_argument("--queue-minutes", type=int,
                            default=M.DEFAULT_QUEUE_MINUTES)
        parser.add_argument("--stuck-minutes", type=int,
                            default=M.DEFAULT_STUCK_MINUTES)
        parser.add_argument("--repeat-hours", type=int, default=6)
        parser.add_argument("--digest-hour", type=int, default=9,
                            help="Local hour (0-23) of the daily summary.")
        parser.add_argument("--format", choices=["text", "json"],
                            default="text")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 0 <= options["digest_hour"] <= 23:
            raise CommandError("--digest-hour must be 0-23.")

        now = timezone.now()
        data = M.collect(now=now, queue_minutes=options["queue_minutes"],
                         stuck_minutes=options["stuck_minutes"])

        if options["dry_run"]:
            if options["format"] == "json":
                import json
                self.stdout.write(json.dumps(data, indent=2))
            else:
                self.stdout.write(M.render_text(data))
            return

        recipients = _recipients(options["to"])
        if not recipients:
            raise CommandError(
                "No recipient. Set MONITOR_RECIPIENTS (or "
                "HITL_REPORT_RECIPIENTS) or pass --to.")

        local = timezone.localtime(now)
        messages = []

        if data["alerts"]:
            messages.append((
                M.alert_subject(data),
                M.render_text(data, title="Screening pipeline ALERT"),
                timedelta(hours=options["repeat_hours"]),
            ))

        if local.hour >= options["digest_hour"]:
            messages.append((
                f"[Pipeline Daily Summary] {local.date().isoformat()}",
                M.render_text(data, title="Screening pipeline - daily summary"),
                timedelta(hours=24),
            ))

        failures = 0
        for subject, body, window in messages:
            for recipient in recipients:
                already = EmailLog.objects.filter(
                    recipient=recipient, subject=subject,
                    status__in=[EmailLog.Status.SENT, EmailLog.Status.PENDING],
                    created_at__gte=now - window,
                ).exists()
                if already:
                    self.stdout.write(f"Skipped {recipient}: '{subject}' "
                                      "was already sent recently.")
                    continue
                try:
                    with email_context("other"):
                        send_mail(
                            subject=subject, message=body,
                            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                            recipient_list=[recipient], fail_silently=False)
                    self.stdout.write(f"Sent '{subject}' to {recipient}.")
                except Exception as exc:
                    failures += 1
                    self.stderr.write(
                        f"FAILED for {recipient}: {type(exc).__name__}")

        if not messages:
            self.stdout.write("All normal; nothing to send.")
        if failures:
            raise CommandError(f"{failures} send(s) failed.")
