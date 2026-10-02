"""
TASK B validation command (2026-09-30).

Run this on YOUR OWN machine (the sandbox that wrote this code has no
network access to download the embedding model, so it cannot run this
itself):

    python manage.py test_skill_matching

What it does:
  1. Runs the 5 required example pairs from TASK B (Test 1-5) and
     prints the raw cosine-similarity score + resulting classification
     for each, next to the expected classification.
  2. Times the skill-matching call itself (Skill Matching Before/After
     in the FINAL REPORT needs this).
  3. Runs one real candidate from the demo dataset against one real
     job (Test 6), if any exist -- skipped with a clear message if
     your local DB has none.

Nothing here touches the database, apply_job, or any production data.
"""

import time

from django.core.management.base import BaseCommand

from ai_engine.services.skill_gap_analysis import (
    analyze_skill_gap,
    _normalize,
    _encode_all,
    _best_match_for_job_skill,
)


# (required_skill, candidate_skill, expected_classification) -- straight
# from TASK B's STEP 3 test list.
CASES = [
    ("Python", "Python", "STRONG_MATCH"),
    ("Network Administration", "Cisco Networking", "MATCH / RELATED"),
    ("Database Management", "PostgreSQL Database Administration", "MATCH / STRONG_MATCH"),
    ("Information Security", "Cybersecurity", "MATCH / RELATED"),
    ("Python", "Microsoft Word", "MISSING / NO_MATCH"),
]

# TASK C-0 multilingual check -- same job skill ("Network Administration"),
# same meaning written in 3 different languages. Only meaningful once
# EMBEDDING_MODEL is set to a multilingual model -- with the old
# English-only default these are expected to score low/MISSING.
# Tetum is intentionally left out here: no verified-correct Tetum
# translation was available to write into this file, and an invented
# one would be worse than no test at all. If you have a real Tetum CV
# or job posting with an equivalent skill phrase, run it through
# analyze_skill_gap() by hand and report the similarity score.
MULTILINGUAL_CASES = [
    ("Network Administration", "Network Administration", "English (control)"),
    ("Network Administration", "Administração de Redes", "Portuguese"),
    ("Network Administration", "Administrasi Jaringan", "Indonesian"),
]

class Command(BaseCommand):
    help = "TASK B: print real similarity scores + classifications for the required test cases."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("TASK B -- Skill Matching validation"))
        self.stdout.write("")

        # ---- Test 1-5: the required pairs, one skill vs one skill ----
        self.stdout.write(self.style.MIGRATE_HEADING("Test 1-5: required example pairs"))
        for i, (required, candidate, expected) in enumerate(CASES, start=1):
            job_norm = _normalize(required)
            cand_norm = _normalize(candidate)
            embeddings = _encode_all({job_norm, cand_norm})
            if not embeddings:
                self.stdout.write(self.style.ERROR(
                    "  Could not load the embedding model -- check your internet "
                    "connection (first run needs to download BAAI/bge-base-en-v1.5)."
                ))
                return
            _, level, similarity = _best_match_for_job_skill(job_norm, {cand_norm}, embeddings)
            self.stdout.write(
                f"  Test {i}: '{required}' vs '{candidate}'\n"
                f"           similarity={similarity}  ->  got={level}  (expected: {expected})"
            )
        self.stdout.write("")

                # ---- TASK C-0: same meaning, different language ----
        self.stdout.write(self.style.MIGRATE_HEADING("TASK C-0: multilingual check (Network Administration)"))
        import os
        current_model = os.getenv("EMBEDDING_MODEL", "(default -- English-only, BAAI/bge-base-en-v1.5)")
        self.stdout.write(f"  EMBEDDING_MODEL currently in use: {current_model}")
        for required, candidate, label in MULTILINGUAL_CASES:
            job_norm = _normalize(required)
            cand_norm = _normalize(candidate)
            embeddings = _encode_all({job_norm, cand_norm})
            _, level, similarity = _best_match_for_job_skill(job_norm, {cand_norm}, embeddings)
            self.stdout.write(
                f"  [{label}] '{required}' vs '{candidate}'\n"
                f"           similarity={similarity}  ->  got={level}"
            )
        self.stdout.write("")

        # ---- Full analyze_skill_gap() call, timed ----
        self.stdout.write(self.style.MIGRATE_HEADING("Skill Matching timing"))
        job_skills = ["Python", "Network Administration", "Database Management",
                      "Information Security", "Communication"]
        candidate_skills = ["Python", "Cisco Networking", "PostgreSQL Database Administration",
                             "Cybersecurity"]

        # First call includes model load time (one-time, happens once per
        # server process) -- report it separately from a warm call, which
        # is what every later application in the same process actually pays.
        t0 = time.perf_counter()
        result = analyze_skill_gap(candidate_skills, job_skills)
        cold_seconds = time.perf_counter() - t0

        t0 = time.perf_counter()
        analyze_skill_gap(candidate_skills, job_skills)
        warm_seconds = time.perf_counter() - t0

        self.stdout.write(f"  First call (includes model load): {cold_seconds:.3f}s")
        self.stdout.write(f"  Second call (model already loaded): {warm_seconds:.3f}s")
        self.stdout.write(f"  match_score for this 5-skill job: {result['match_score']}")
        self.stdout.write("")
        for detail in result["skill_details"]:
            self.stdout.write(f"    {detail}")
        self.stdout.write("")

        # ---- Test 6: one real candidate from the demo dataset, if any ----
        self.stdout.write(self.style.MIGRATE_HEADING("Test 6: real ICT Officer candidate (if present)"))
        try:
            from talent.models import Application
            app = (
                Application.objects
                .exclude(ai_profile={})
                .exclude(ai_job_profile={})
                .select_related("candidate", "job")
                .first()
            )
            if app is None:
                self.stdout.write("  No existing Application with parsed AI profiles found -- skipped.")
            else:
                # ai_profile / ai_job_profile are the EXACT dicts the real
                # apply_job pipeline already produced and saved for this
                # application (recruitment_pipeline.py) -- using them here
                # re-runs skill matching on real data without touching the
                # database or re-triggering the pipeline.
                cand_skills = (app.ai_profile or {}).get("skills", [])
                job_skills_real = (app.ai_job_profile or {}).get("skills", [])
                if not cand_skills or not job_skills_real:
                    self.stdout.write("  Found an application but skills lists are empty -- skipped.")
                else:
                    t0 = time.perf_counter()
                    real_result = analyze_skill_gap(cand_skills, job_skills_real)
                    real_seconds = time.perf_counter() - t0
                    self.stdout.write(f"  Application #{app.id} ({app.candidate}, job: {app.job})")
                    self.stdout.write(f"  match_score: {real_result['match_score']}  ({real_seconds:.3f}s)")
                    self.stdout.write(f"  matched_skills: {real_result['matched_skills']}")
                    self.stdout.write(f"  missing_skills: {real_result['missing_skills']}")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Skipped (could not query real data): {e}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done. Paste this whole output back to Claude."))