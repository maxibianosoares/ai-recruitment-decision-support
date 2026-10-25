"""
Weekly Human-in-the-Loop report (anonymous, read-only).

    python manage.py weekly_hitl_report                     # markdown, last 4 weeks
    python manage.py weekly_hitl_report --format json       # for an agent such as Hermes
    python manage.py weekly_hitl_report --weeks 8 --week-ending 2026-10-25
    python manage.py weekly_hitl_report --lang id

All numbers are computed here (talent/hitl_report.py); no model is
called and nothing is written.  Output contains counts only -- no
names, emails, ids, reasons or document text.
"""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from talent.hitl_report import build_report, render_markdown


class Command(BaseCommand):

    help = ("Anonymous weekly report: how many AI recommendations the "
            "committee agreed with or overrode. Read-only.")

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["markdown", "json"],
                            default="markdown")
        parser.add_argument("--weeks", type=int, default=4,
                            help="Number of weeks to include (1-52).")
        parser.add_argument("--week-ending", default=None,
                            help="YYYY-MM-DD, any date in the last week to "
                                 "report (default: last completed week).")
        parser.add_argument("--lang", choices=["en", "id"], default="en",
                            help="Language of the markdown labels.")

    def handle(self, *args, **options):
        week_ending = None
        if options["week_ending"]:
            try:
                week_ending = date.fromisoformat(options["week_ending"])
            except ValueError:
                raise CommandError("--week-ending must be YYYY-MM-DD.")

        try:
            report = build_report(week_ending=week_ending,
                                  weeks=options["weeks"])
        except ValueError as exc:
            raise CommandError(str(exc))

        if options["format"] == "json":
            self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(render_markdown(report, lang=options["lang"]))
