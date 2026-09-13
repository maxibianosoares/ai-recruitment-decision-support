"""
Tahap 2 -- multilingual prompt understanding tests.

Usage:
    python manage.py test_multilingual_prompts

INSTRUMENTATION ONLY -- calls the REAL, unmodified
generate_recruitment_assessment() and analyze_cv() functions with
real Ollama. Does not touch the RAG architecture, embedding model,
or OCR. Prints results for human judgment -- semantic quality is not
something a script can self-grade, so this reports what the model
actually said rather than a pass/fail verdict.

Tests 1-4 mirror the same structure: one job requirement stated in
one language, one piece of candidate evidence stated in the SAME or
a DIFFERENT language, both referring to the same underlying skill
(computer networking). Test 5 is a single mixed-language CV run
through analyze_cv() to check the extracted profile stays
well-formed with no hallucinated fields.
"""

from django.core.management.base import BaseCommand

from ai_engine.services.llm_reasoning import generate_recruitment_assessment
from ai_engine.services.llm_candidate_profile import analyze_cv
from ai_engine.services.recruitment_rules import evaluate_recruitment_rules
from ai_engine.services.skill_gap_analysis import skill_gap_analysis


JOB_PROFILE_TEMPLATE = {
    "job_title": "ICT Officer",
    "education": "Bachelor",
    "years_experience": 2,
    "languages": [],
    "certifications": [],
    "skills": ["Computer Networks"]
}

TESTS = [
    {
        "label": "Test 1 -- English vs English",
        "job_skill_text": "Computer Networks",
        "candidate_summary": (
            "Candidate has professional experience in network "
            "administration."
        ),
        "candidate_skills": ["Network Administration"]
    },
    {
        "label": "Test 2 -- Portuguese vs Portuguese",
        "job_skill_text": "Administra\u00e7\u00e3o de Redes",
        "candidate_summary": (
            "Experi\u00eancia profissional em redes de computadores."
        ),
        "candidate_skills": ["Administra\u00e7\u00e3o de Redes de Computadores"]
    },
    {
        "label": "Test 3 -- Indonesian vs Indonesian",
        "job_skill_text": "Administrasi jaringan komputer",
        "candidate_summary": (
            "Memiliki pengalaman dalam pengelolaan jaringan komputer."
        ),
        "candidate_skills": ["Administrasi Jaringan"]
    },
    {
        "label": "Test 4 -- Tetum vs Tetum (realistic recruitment wording)",
        "job_skill_text": "Administrasaun rede komputadór",
        "candidate_summary": (
            "Iha esperi\u00e9nsia iha administrasaun rede iha instituisaun "
            "governu durante 3 tinan."
        ),
        "candidate_skills": ["Administrasaun Rede"]
    },
    {
        "label": "Test (cross-language) -- English job vs Portuguese candidate",
        "job_skill_text": "Computer Networks",
        "candidate_summary": (
            "Experi\u00eancia profissional em administra\u00e7\u00e3o de redes "
            "de computadores em ag\u00eancia governamental."
        ),
        "candidate_skills": ["Administra\u00e7\u00e3o de Redes"]
    },
]

MIXED_CV_TEXT = """
Curriculum Vitae

Education: Bachelor of Computer Science

Experi\u00eancia Profisional: 5 years working as a network technician for a
government agency in Dili.

Compet\u00eancias: Administra\u00e7\u00e3o de Redes, Database Management

Languages: Tetum, Portugu\u00eas, English

Habilita\u00e7\u00f5es Acad\u00e9micas: Licenciatura em Inform\u00e1tica, Instituto
Nacional de Ci\u00eancia e Tecnologia, 2018
"""


class Command(BaseCommand):

    help = (
        "Tahap 2 -- run the 5 multilingual semantic-understanding "
        "tests against the real, live LLM (requires Ollama)."
    )

    def handle(self, *args, **options):

        self.stdout.write(self.style.NOTICE(
            "\n" + "=" * 70 +
            "\nTESTS 1-4 + cross-language -- semantic equivalence via "
            "generate_recruitment_assessment()" +
            "\n" + "=" * 70
        ))

        for test in TESTS:

            job_profile = dict(JOB_PROFILE_TEMPLATE)
            job_profile["skills"] = [test["job_skill_text"]]

            candidate_profile = {
                "education": "Bachelor",
                "years_experience": 3,
                "languages": [],
                "certifications": [],
                "skills": test["candidate_skills"],
                "professional_summary": test["candidate_summary"]
            }

            rule_result = evaluate_recruitment_rules(
                candidate_profile, job_profile
            )

            gap_result = skill_gap_analysis(
                candidate_profile["skills"], job_profile["skills"]
            )

            assessment = generate_recruitment_assessment(
                profile=candidate_profile,
                job_profile=job_profile,
                rule_result=rule_result,
                gap_result=gap_result,
                rag_context=None
            )

            self.stdout.write(f"\n{test['label']}")
            self.stdout.write(f"  Job requirement   : {test['job_skill_text']}")
            self.stdout.write(f"  Candidate evidence: {test['candidate_summary']}")
            self.stdout.write(
                f"  -> technical_skills score: "
                f"{assessment['dimension_scores'].get('technical_skills')}"
            )
            self.stdout.write(f"  -> overall_score: {assessment['overall_score']}")
            self.stdout.write(f"  -> reasoning: {assessment.get('reasoning')}")
            self.stdout.write(
                f"  -> weaknesses: {assessment.get('weaknesses')}"
            )
            self.stdout.write(
                "  (exact-string skill_gap match_score, for comparison: "
                f"{gap_result['match_score']} -- if this is 0 but the "
                "semantic score above is high, that demonstrates semantic "
                "matching catching what exact-string matching misses)"
            )

        self.stdout.write(self.style.NOTICE(
            "\n" + "=" * 70 +
            "\nTEST 5 -- mixed-language CV via analyze_cv()" +
            "\n" + "=" * 70
        ))

        profile = analyze_cv(MIXED_CV_TEXT)

        self.stdout.write(f"\nExtracted profile:\n{profile}")

        expected_keys = {
            "education", "skills", "languages", "certifications",
            "years_experience", "professional_summary"
        }

        actual_keys = set(profile.keys())

        self.stdout.write(
            f"\nSchema check -- expected keys present: "
            f"{expected_keys.issubset(actual_keys)}"
        )

        unexpected = actual_keys - expected_keys - {"error"}

        if unexpected:
            self.stdout.write(
                self.style.WARNING(
                    f"Unexpected extra keys in output: {unexpected}"
                )
            )

        self.stdout.write(
            "\nManually check above: does 'skills' include both "
            "Administra\u00e7\u00e3o de Redes AND Database Management? Does "
            "'languages' include Tetum, Portuguese, AND English? Does "
            "'education' reflect the Licenciatura entry? Is anything "
            "invented that isn't in the source text above?"
        )
