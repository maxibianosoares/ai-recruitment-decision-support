"""
TASK C validation command (2026-09-30).

Run this on YOUR OWN machine (same reason as test_skill_matching --
this sandbox cannot reach the embedding model):

    python manage.py test_rule_engine

What it does:
  1. Prints the graded Education classification for TASK C's 3
     required examples (needs the embedding model -- the part this
     sandbox could not verify itself).
  2. Re-prints the graded Experience classification for the 5
     required examples (already verified in-sandbox since it's pure
     math, included here again so everything is in one place).
  3. Runs 4 full synthetic candidates (Strong / Near-requirement /
     Partial / Clearly unqualified) through the REAL
     evaluate_recruitment_rules(), end to end, and prints the
     resulting eligible flag + matrix -- proves the whole graded
     Rule Engine behaves sensibly together, not just each piece in
     isolation.

Nothing here touches the database, apply_job, or any production data.
"""

from django.core.management.base import BaseCommand

from ai_engine.services.recruitment_rules import (
    evaluate_recruitment_rules,
    _graded_text_match,
    _graded_experience_match,
)


EDUCATION_REQUIRED = "Bachelor in IT / Computer Science / related field"

EDUCATION_CASES = [
    ("Bachelor of Computer Science", "STRONG_MATCH"),
    ("Bachelor of Information Systems", "MATCH"),
    ("Bachelor of Business Administration", "PARTIAL / MISSING"),
]

EXPERIENCE_CASES = [
    (2, 5, "STRONG_MATCH"),
    (2, 2, "MATCH"),
    (2, 22 / 12, "NEAR_REQUIREMENT"),
    (2, 0.5, "PARTIAL / MISSING"),
    (2, 0, "MISSING"),
]

SYNTHETIC_JOB = {
    "education": EDUCATION_REQUIRED,
    "years_experience": 2,
    "languages": ["English"],
    "skills": ["Python", "Database Management"],
}

SYNTHETIC_CANDIDATES = [
    ("Candidate A (strong)", {
        "education": "Bachelor of Computer Science",
        "years_experience": 5,
        "languages": ["English", "Tetum"],
        "skills": ["Python", "PostgreSQL Database Administration"],
    }),
    ("Candidate B (near-requirement)", {
        "education": "Bachelor of Information Systems",
        "years_experience": 22 / 12,
        "languages": ["English"],
        "skills": ["Python", "Database Management"],
    }),
    ("Candidate C (partial)", {
        "education": "Bachelor of Business Administration",
        "years_experience": 0.5,
        "languages": ["Tetum"],
        "skills": ["Python"],
    }),
    ("Candidate D (clearly unqualified)", {
        "education": "High School Diploma",
        "years_experience": 0,
        "languages": [],
        "skills": ["Microsoft Word"],
    }),
]


class Command(BaseCommand):
    help = "TASK C: print real graded Rule Engine results for the required test cases."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("TASK C -- Rule Engine validation"))
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING(f"Education (required: '{EDUCATION_REQUIRED}')"))
        for candidate_text, expected in EDUCATION_CASES:
            level, similarity = _graded_text_match(EDUCATION_REQUIRED, candidate_text)
            self.stdout.write(
                f"  '{candidate_text}'\n"
                f"           similarity={similarity}  ->  got={level}  (expected: {expected})"
            )
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("Experience (re-check, pure math -- no model needed)"))
        for required, candidate, expected in EXPERIENCE_CASES:
            level, ratio = _graded_experience_match(required, candidate)
            self.stdout.write(
                f"  {candidate:.2f}y vs {required}y required: ratio={ratio}  ->  got={level}  (expected: {expected})"
            )
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("Full synthetic candidates (end-to-end evaluate_recruitment_rules)"))
        for label, profile in SYNTHETIC_CANDIDATES:
            result = evaluate_recruitment_rules(profile, SYNTHETIC_JOB)
            self.stdout.write(f"  {label}: eligible={result['eligible']}")
            for row in result["matrix"]:
                self.stdout.write(
                    f"      {row['requirement']:<45} met={row['met']!s:<6} level={row.get('level')}"
                )
            if result["failed_rules"]:
                self.stdout.write(f"      failed_rules: {result['failed_rules']}")
            if result["warnings"]:
                self.stdout.write(f"      warnings: {result['warnings']}")
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("Done. Paste this whole output back to Claude."))