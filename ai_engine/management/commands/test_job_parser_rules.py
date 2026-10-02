"""
Task E (A+B) test: job-parser prompt rules and schema-on-first-attempt.

Usage:
    python manage.py test_job_parser_rules

Mocks the LLM (no Ollama needed). It checks the PROMPT and CALL SHAPE
only. Whether Gemma actually follows the rules must be checked with
`python manage.py reprocess_job <ID>` on a real job.
"""
from unittest import mock

from django.core.management.base import BaseCommand

from ai_engine.services import llm_job_parser as jp

GOOD = {
    "job_title": "Database Administrator", "education": "Bachelor",
    "skills": ["PostgreSQL"], "preferred_skills": ["SQL Server"],
    "languages": [], "certifications": [],
    "years_experience": 2, "professional_summary": "",
}


class Command(BaseCommand):
    help = "Task E A+B: job parser rules and schema on first attempt."

    def handle(self, *args, **options):
        results = []

        def check(name, cond):
            results.append(bool(cond))
            self.stdout.write(f"{'PASS' if cond else 'FAIL'}  {name}")

        calls = []

        def fake_ok(prompt, json_schema=None, **kw):
            calls.append({"prompt": prompt, "schema": json_schema})
            return dict(GOOD)

        with mock.patch.object(jp, "generate_json", fake_ok):
            out = jp.analyze_job_description("Database Administrator needed.")

        check("B: schema sent on the FIRST attempt", calls[0]["schema"] is jp.JOB_PROFILE_JSON_SCHEMA)
        check("B: valid first answer -> exactly 1 LLM call", len(calls) == 1)
        check("profile returned unchanged", out == GOOD)

        p = calls[0]["prompt"]
        check("A: rule - only REQUIRED skills in 'skills'", "ONLY skills that are REQUIRED" in p)
        check("A: rule - 'preferred/advantage' goes to preferred_skills",
              "preferred_skills" in p and "sei konsidera hanesan vantagem" in p)
        check("A: rule - certifications only if required", "ONLY certifications that are explicitly REQUIRED" in p)
        check("A: rule - 'at least one language' -> languages empty",
              "at least one" in p and "leave \"languages\" as an empty array" in p)
        check("A: rule - no duty verbs as skills", "Do not list job duties" in p)

        schema = jp.JOB_PROFILE_JSON_SCHEMA
        check("schema has preferred_skills (required)",
              "preferred_skills" in schema["properties"] and "preferred_skills" in schema["required"])
        check("'skills' key kept (Rule Engine / Skill Matching unchanged)", "skills" in jp.DEFAULT_JOB_PROFILE)

        # retry safety net still works: {} then valid
        seq = [{}, dict(GOOD)]
        calls2 = []

        def fake_retry(prompt, json_schema=None, **kw):
            calls2.append(json_schema)
            return seq[len(calls2) - 1]

        with mock.patch.object(jp, "generate_json", fake_retry):
            out2 = jp.analyze_job_description("x")
        check("retry kept: '{}' then valid -> 2 calls, valid result",
              len(calls2) == 2 and out2 == GOOD)

        self.stdout.write(f"\n{sum(results)}/{len(results)} passed")