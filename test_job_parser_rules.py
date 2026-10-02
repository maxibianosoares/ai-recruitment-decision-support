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

        # ---- safety net: advantage / "at least one" must not become mandatory
        job30_text = (
            "Education Requirements\n"
            "* Must hold a Bachelor's degree in Information Technology, Computer Science.\n"
            "* Training or certification in database administration will be considered an advantage.\n"
            "Language\n"
            "* Candidates must be able to speak and write at least one of the official languages of Timor-Leste.\n"
            "* Knowledge of Portuguese or English will be considered an advantage.\n"
            "Selection Criteria\n"
            "* Relevant certification or training.\n"
        )
        p1 = jp._drop_non_required(
            {"languages": ["Portuguese", "English"],
             "certifications": ["Training or certification related to database administration"]},
            job30_text)
        check("guard: job-30 text -> languages emptied", p1["languages"] == [])
        check("guard: job-30 text -> advantage-only certification removed", p1["certifications"] == [])

        p2 = jp._drop_non_required({"languages": ["English"], "certifications": []}, "Candidates must speak English.")
        check("guard: mandatory language kept", p2["languages"] == ["English"])

        p3 = jp._drop_non_required({"languages": ["English", "Portuguese"], "certifications": []},
                                   "Fluency in English is required; Portuguese is an advantage.")
        check("guard: required kept, advantage removed (same line)", p3["languages"] == ["English"])

        p4 = jp._drop_non_required({"languages": ["Tetum", "Portuguese"], "certifications": []},
                                   "Must speak at least one of Tetum or Portuguese.")
        check("guard: 'at least one of' -> not individual requirements", p4["languages"] == [])

        p5 = jp._drop_non_required({"languages": [], "certifications": ["CCNA"]}, "CCNA certification is required.")
        check("guard: mandatory certification kept", p5["certifications"] == ["CCNA"])

        p6 = jp._drop_non_required({"languages": ["Tetum"], "certifications": ["PMP"]}, "Some unrelated text.")
        check("guard: not mentioned in text -> kept (cannot verify)",
              p6["languages"] == ["Tetum"] and p6["certifications"] == ["PMP"])

        p7 = jp._drop_non_required({"languages": None, "certifications": 5}, "x")
        check("guard: odd input never raises", isinstance(p7, dict))

        self.stdout.write(f"\n{sum(results)}/{len(results)} passed")
