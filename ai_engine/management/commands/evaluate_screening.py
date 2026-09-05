"""
Usage:

    python manage.py evaluate_screening

Phase 17 — validates the core screening pipeline guarantees using
the 12 seeded candidates (talent/seed_demo_data.py: 3 tiers x 4
jobs) as a known-answer test set, since each tier was deliberately
constructed with a known expected outcome. This is a system
validation check, not a replacement for the RAG benchmark
(rag/evaluation/ — run via `run_benchmark`), which covers a
different layer (policy Q&A, not candidate screening).

Checks, per job:
  1. Eligibility gate: Strong/Medium tiers (full required skills)
     must be eligible=True; Weak tier (no required skills) must be
     eligible=False.
  2. Score ranking: Strong > Medium > Weak.
  3. Hard-cap enforcement: an ineligible candidate's score must
     never exceed 49.
  4. Evidence completeness: Requirement-Evidence matrix (Phase 14)
     and RAG legal evidence (Phase 12/13) must both be non-empty for
     every application.

Prints a pass/fail table and a summary count. Exits non-zero if any
check fails, so it can be re-run as a quick regression check any
time the pipeline code changes.
"""

from django.core.management.base import BaseCommand

from talent.models import Application


class Command(BaseCommand):

    help = (
        "Phase 17 — validate the screening pipeline's core "
        "guarantees against the seeded known-answer candidates."
    )

    def handle(self, *args, **options):

        jobs = (
            Application.objects
            .values_list("job__title", flat=True)
            .distinct()
        )

        if not jobs:

            self.stderr.write(
                self.style.ERROR(
                    "No applications found. Run "
                    "`python manage.py seed_demo_data --reset` first."
                )
            )

            return

        results = []

        for job_title in jobs:

            apps = list(
                Application.objects
                .filter(job__title=job_title)
                .select_related("candidate")
                .order_by("candidate__full_name")
            )

            by_tier = {}

            for app in apps:

                name = app.candidate.full_name

                if name.endswith(" A"):
                    by_tier["strong"] = app
                elif name.endswith(" B"):
                    by_tier["medium"] = app
                elif name.endswith(" C"):
                    by_tier["weak"] = app

            if len(by_tier) != 3:
                continue

            strong = by_tier["strong"]
            medium = by_tier["medium"]
            weak = by_tier["weak"]

            checks = [
                (
                    "Strong eligible",
                    strong.ai_rule_result.get("eligible") is True
                ),
                (
                    "Medium eligible",
                    medium.ai_rule_result.get("eligible") is True
                ),
                (
                    "Weak ineligible",
                    weak.ai_rule_result.get("eligible") is False
                ),
                (
                    "Score ranking (Strong > Medium > Weak)",
                    strong.ai_score > medium.ai_score > weak.ai_score
                ),
                (
                    "Weak score capped <=49",
                    weak.ai_score <= 49
                ),
                (
                    "Requirement matrix populated (all 3)",
                    all(
                        a.ai_rule_result.get("matrix")
                        for a in (strong, medium, weak)
                    )
                ),
                (
                    "RAG legal evidence populated (all 3)",
                    all(
                        a.ai_rag_context.get("evidence")
                        for a in (strong, medium, weak)
                    )
                ),
            ]

            results.append((job_title, checks))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.NOTICE("SCREENING PIPELINE VALIDATION"))
        self.stdout.write("=" * 70)

        total_checks = 0
        total_passed = 0

        for job_title, checks in results:

            self.stdout.write(f"\n{job_title}")

            for label, passed in checks:

                total_checks += 1

                if passed:
                    total_passed += 1
                    self.stdout.write(self.style.SUCCESS(f"  [PASS] {label}"))
                else:
                    self.stdout.write(self.style.ERROR(f"  [FAIL] {label}"))

        self.stdout.write("\n" + "-" * 70)

        self.stdout.write(
            f"TOTAL: {total_passed}/{total_checks} checks passed "
            f"across {len(results)} job(s)"
        )

        if total_passed < total_checks:

            self.stderr.write(
                self.style.ERROR(
                    "\nSome checks failed — see [FAIL] lines above."
                )
            )

            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS("\nAll screening pipeline checks passed.")
        )
