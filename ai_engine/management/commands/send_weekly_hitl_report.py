"""
Emails the anonymous weekly Human-in-the-Loop report to the administrator.

    python manage.py send_weekly_hitl_report                 # last completed week
    python manage.py send_weekly_hitl_report --dry-run       # print, send nothing
    python manage.py send_weekly_hitl_report --to a@b.org    # override recipients
    python manage.py send_weekly_hitl_report --force         # send again

Recipients come from --to, otherwise from the HITL_REPORT_RECIPIENTS
environment variable (comma-separated). The address is deliberately NOT
written in the code. The email carries counts only (see
talent/hitl_report.py); nothing is written except the normal EmailLog row
made by the existing Brevo backend.

Safe to schedule: it sends at most ONE email per recipient per reported
week. If the schedule fires twice, or the command is re-run, the second run
finds the earlier EmailLog row and does nothing (use --force to override).
Exit code is non-zero if any send fails, so the scheduler shows the failure.
"""

import os
from datetime import date

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from accounts.email_context import email_context
from accounts.models import EmailLog
from talent.hitl_report import build_report, render_text, LABELS

PREFIX = "[Weekly HITL Report]"


def _recipients(option_values):
    raw = option_values or [
        part for part in os.environ.get("HITL_REPORT_RECIPIENTS", "").split(",")
    ]
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

    help = "Email the anonymous weekly Human-in-the-Loop report (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--to", action="append", default=[],
                            help="Recipient (repeatable). Default: the "
                                 "HITL_REPORT_RECIPIENTS environment variable.")
        parser.add_argument("--weeks", type=int, default=4)
        parser.add_argument("--week-ending", default=None,
                            help="YYYY-MM-DD, any date in the week to report "
                                 "(default: last completed week).")
        parser.add_argument("--lang", choices=["en", "id"], default="en")
        parser.add_argument("--dry-run", action="store_true",
                            help="Print the email; send nothing, log nothing.")
        parser.add_argument("--force", action="store_true",
                            help="Send even if this week was already sent.")

    def handle(self, *args, **options):
        recipients = _recipients(options["to"])
        if not recipients:
            raise CommandError(
                "No recipient. Set HITL_REPORT_RECIPIENTS or pass --to.")

        week_ending = None
        if options["week_ending"]:
            try:
                week_ending = date.fromisoformat(options["week_ending"])
            except ValueError:
                raise CommandError("--week-ending must be YYYY-MM-DD.")

        try:
            report = build_report(week_ending=week_ending, weeks=options["weeks"])
        except ValueError as exc:
            raise CommandError(str(exc))

        last = report["weekly"][-1]
        subject = (f"{PREFIX} {LABELS[options['lang']]['title']} "
                   f"{last['week_start']} - {last['week_end']}")
        body = render_text(report, lang=options["lang"])

        if options["dry_run"]:
            self.stdout.write(f"To: {', '.join(recipients)}\nSubject: {subject}\n\n{body}")
            return

        failures = 0
        for recipient in recipients:
            already = EmailLog.objects.filter(
                recipient=recipient, subject=subject,
                status__in=[EmailLog.Status.SENT, EmailLog.Status.PENDING],
            ).exists()
            if already and not options["force"]:
                self.stdout.write(
                    f"Skipped {recipient}: this week's report was already sent.")
                continue
            try:
                with email_context("other"):
                    send_mail(
                        subject=subject, message=body,
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                        recipient_list=[recipient], fail_silently=False)
                self.stdout.write(f"Sent to {recipient}.")
            except Exception as exc:
                failures += 1
                self.stderr.write(
                    f"FAILED for {recipient}: {type(exc).__name__}")
        if failures:
            raise CommandError(f"{failures} send(s) failed.")
