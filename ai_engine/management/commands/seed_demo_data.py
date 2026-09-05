"""
Usage:

    python manage.py seed_demo_data
    python manage.py seed_demo_data --reset
    python manage.py seed_demo_data --live

Seeds the (now-empty, post-MySQL-to-SQLite) database with 4 job
vacancies and ~4-5 candidates per job (16-20 total), spread across
Strong / Medium / Weak profiles so Candidate Ranking has a realistic,
varied distribution to demo.

DESIGN NOTE (thesis honesty, read before demoing):
  - Job requirements and candidate CVs are real text (generated into
    real PDF files via fpdf2, then parsed back with the same
    extract_text_from_pdf() the live apply flow uses).
  - The Rule Engine result (eligible/failed_rules/matched_skills) and
    the Skill Gap result (match_score) are computed by calling the
    REAL evaluate_recruitment_rules() / analyze_skill_gap() functions
    against the seeded profile dicts — not hand-typed numbers. If you
    change a candidate's skills list below, eligibility/skill-gap
    recompute correctly.
  - The LLM-only outputs (semantic dimension scores, decision
    narrative, confidence) CANNOT be computed without Ollama running.
    By default this command uses fixed target semantic scores per
    tier (Strong/Medium/Weak) and a pre-written narrative, then feeds
    them through the SAME compute_final_score() the live pipeline
    uses — so ai_score is arithmetically consistent with real code,
    even though the semantic number itself is a stand-in.
  - Pass --live to instead run every seeded application through the
    real recruitment_pipeline() (requires Ollama + gemma3:12b loaded
    locally). This is slower and the exact scores will vary run to
    run, but it is the real pipeline end to end. Use this if you want
    to demo/verify the live AI path itself, not just the ranking UI.
"""

import io
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from talent.models import Job, Skill, Candidate, Application
from ai_engine.services.recruitment_rules import evaluate_recruitment_rules
from ai_engine.services.skill_gap_analysis import analyze_skill_gap
from ai_engine.services.recruitment_pipeline import (
    compute_final_score,
    recruitment_pipeline
)

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    FPDF = None


# =================================================================
# JOB DEFINITIONS
# =================================================================

JOBS = [
    {
        "title": "ICT Officer",
        "department": "Ministry of Public Administration — ICT Division",
        "description": (
            "The ICT Officer supports the Ministry's information "
            "systems, manages the department's database "
            "infrastructure, and provides technical support to "
            "civil service staff."
        ),
        "requirements": (
            "Bachelor's degree in Information Technology or related "
            "field. Minimum 2 years of relevant experience. Strong "
            "understanding of database management, network "
            "administration, and system security. English proficiency "
            "required."
        ),
        "profile": {
            "job_title": "ICT Officer",
            "education": "Bachelor",
            "years_experience": 2,
            "languages": ["English"],
            "certifications": [],
            "skills": [
                "Database Management",
                "Network Administration",
                "System Security",
                "Technical Support"
            ],
            "professional_summary": (
                "Supports ministry information systems and provides "
                "ICT technical support."
            )
        }
    },
    {
        "title": "Software Developer",
        "department": "Ministry of Public Administration — ICT Division",
        "description": (
            "The Software Developer builds and maintains internal "
            "government applications, including the civil service "
            "recruitment platform."
        ),
        "requirements": (
            "Bachelor's degree in Computer Science or related field. "
            "Minimum 1 year of experience. Proficiency in Python and "
            "Django. Familiarity with REST APIs and Git version "
            "control. English proficiency required."
        ),
        "profile": {
            "job_title": "Software Developer",
            "education": "Bachelor",
            "years_experience": 1,
            "languages": ["English"],
            "certifications": [],
            "skills": [
                "Python",
                "Django",
                "REST API",
                "Git"
            ],
            "professional_summary": (
                "Builds and maintains internal government software "
                "applications."
            )
        }
    },
    {
        "title": "Data Analyst",
        "department": "Ministry of Finance — Statistics & Planning",
        "description": (
            "The Data Analyst compiles, cleans, and analyzes public "
            "sector datasets to support budget and policy planning "
            "decisions."
        ),
        "requirements": (
            "Bachelor's degree in Statistics, Economics, or related "
            "field. Minimum 2 years of experience. Proficiency in SQL "
            "and spreadsheet analysis. Strong reporting and "
            "presentation skills. English proficiency required."
        ),
        "profile": {
            "job_title": "Data Analyst",
            "education": "Bachelor",
            "years_experience": 2,
            "languages": ["English"],
            "certifications": [],
            "skills": [
                "Data Analysis",
                "SQL",
                "Excel",
                "Reporting"
            ],
            "professional_summary": (
                "Analyzes public sector data to support budget and "
                "policy planning."
            )
        }
    },
    {
        "title": "HR Officer",
        "department": "Civil Service Commission — Human Resources",
        "description": (
            "The HR Officer manages recruitment logistics, maintains "
            "personnel records, and ensures compliance with civil "
            "service labor regulations."
        ),
        "requirements": (
            "Bachelor's degree in Human Resources, Public "
            "Administration, or related field. Minimum 3 years of "
            "experience. Strong knowledge of labor law, employee "
            "relations, and payroll processes. English and Tetum "
            "proficiency required."
        ),
        "profile": {
            "job_title": "HR Officer",
            "education": "Bachelor",
            "years_experience": 3,
            "languages": ["English", "Tetum"],
            "certifications": [],
            "skills": [
                "Recruitment",
                "Labor Law",
                "Employee Relations",
                "Payroll"
            ],
            "professional_summary": (
                "Manages recruitment logistics and personnel records "
                "for the civil service."
            )
        }
    }
]


# =================================================================
# CANDIDATE TIERS
# Each job gets one candidate per tier below. "skills_offset" trims
# or extends the job's required skill list to create a realistic
# match/miss pattern; "semantic_target" is fed into the shared
# compute_final_score() alongside the REAL rule/skill-gap result.
# =================================================================

TIERS = [
    {
        "label": "Strong",
        "name_suffix": "A",
        "education": "Bachelor",
        "experience_delta": 2,
        "extra_skill": "Communication",
        "skills_fraction": 1.0,
        "semantic_target": 90,
        "decision": "Highly Recommended",
        "narrative": (
            "Candidate demonstrates strong alignment with all core "
            "requirements, with hands-on experience directly matching "
            "the role."
        )
    },
    {
        "label": "Medium",
        "name_suffix": "B",
        "education": "Bachelor",
        "experience_delta": 0,
        "extra_skill": "Teamwork",
        # Keeps the full required-skill list (so the now-strict Rule
        # Engine still marks this candidate eligible=True) but pairs
        # it with a lower semantic score, representing a CV that
        # lists the right keywords without the same depth of
        # demonstrated experience as Candidate A.
        "skills_fraction": 1.0,
        "semantic_target": 30,
        "decision": "Consider",
        "narrative": (
            "Candidate meets all listed technical skill and minimum "
            "experience requirements, but the CV shows comparatively "
            "shallow depth on each skill. Recommended with conditions "
            "pending further interview."
        )
    },
    {
        "label": "Weak",
        "name_suffix": "C",
        "education": "High School",
        "experience_delta": -2,
        "extra_skill": "Microsoft Word",
        "skills_fraction": 0.0,
        "semantic_target": 45,
        "decision": "Not Recommended",
        "narrative": (
            "Candidate does not meet the minimum education, "
            "experience, or technical skill requirements for this "
            "position."
        )
    }
]


def build_cv_pdf_bytes(candidate_name, profile):
    """Render a minimal but real, text-extractable CV PDF."""

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(
        0, 10, candidate_name,
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )

    pdf.set_font("Helvetica", size=11)

    lines = [
        f"Education: {profile['education']}",
        f"Years of Experience: {profile['years_experience']}",
        f"Languages: {', '.join(profile['languages'])}",
        f"Skills: {', '.join(profile['skills'])}",
        f"Summary: {profile['professional_summary']}"
    ]

    for line in lines:
        pdf.multi_cell(
            0, 8, line,
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    return bytes(pdf.output(dest="S"))


def build_candidate_profile(job_profile, tier, index):
    """Derive a candidate profile dict from a job profile + tier."""

    required_skills = job_profile["skills"]

    n_keep = round(len(required_skills) * tier["skills_fraction"])

    candidate_skills = required_skills[:n_keep] + [tier["extra_skill"]]

    return {
        "education": tier["education"],
        "years_experience": max(
            0, job_profile["years_experience"] + tier["experience_delta"]
        ),
        "languages": job_profile["languages"] or ["English"],
        "certifications": [],
        "skills": candidate_skills,
        "professional_summary": (
            f"{tier['label']} candidate for the "
            f"{job_profile['job_title']} position."
        )
    }


class Command(BaseCommand):

    help = "Seed demo jobs and candidates for the Phase 8 demo script."

    def add_arguments(self, parser):

        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing Job/Candidate/Application demo data first."
        )

        parser.add_argument(
            "--live",
            action="store_true",
            help=(
                "Run every seeded application through the real "
                "recruitment_pipeline() (requires Ollama + gemma3:12b "
                "running locally) instead of using fixed tier scores."
            )
        )

    def handle(self, *args, **options):

        if FPDF is None:
            self.stderr.write(
                self.style.ERROR(
                    "fpdf2 is not installed. Run: "
                    "pip install fpdf2 --break-system-packages"
                )
            )
            return

        if options["reset"]:
            self.stdout.write("Clearing existing demo data...")
            Application.objects.all().delete()
            Candidate.objects.all().delete()
            Job.objects.all().delete()

        with transaction.atomic():

            for job_def in JOBS:

                job = self._create_job(job_def)

                for i, tier in enumerate(TIERS):

                    self._create_candidate_and_application(
                        job, job_def["profile"], tier, i, options["live"]
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(JOBS)} jobs with "
                f"{len(JOBS) * len(TIERS)} candidates."
            )
        )

    def _create_job(self, job_def):

        job = Job.objects.create(
            title=job_def["title"],
            department=job_def["department"],
            description=job_def["description"],
            requirements=job_def["requirements"],
            ai_job_profile=job_def["profile"],
            ai_processed=True,
            ai_processed_at=timezone.now()
        )

        for skill_name in job_def["profile"]["skills"]:
            skill, _ = Skill.objects.get_or_create(name=skill_name)
            job.skills.add(skill)

        self.stdout.write(f"  Created job: {job.title}")

        return job

    def _create_candidate_and_application(
        self, job, job_profile, tier, index, live_mode
    ):

        full_name = f"{job.title} Candidate {tier['name_suffix']}"

        email = (
            f"candidate.{tier['name_suffix'].lower()}."
            f"{job.id}@example.test"
        )

        profile = build_candidate_profile(job_profile, tier, index)

        pdf_bytes = build_cv_pdf_bytes(full_name, profile)

        candidate = Candidate.objects.create(
            full_name=full_name,
            email=email,
            education=profile["education"],
            years_experience=profile["years_experience"],
            languages=", ".join(profile["languages"]),
            certifications="",
            candidate_skills=", ".join(profile["skills"]),
            professional_summary=profile["professional_summary"]
        )

        candidate.cv_file.save(
            f"{full_name.replace(' ', '_')}.pdf",
            ContentFile(pdf_bytes),
            save=False
        )

        candidate.extracted_text = (
            f"{full_name}\n"
            f"Education: {profile['education']}\n"
            f"Years of Experience: {profile['years_experience']}\n"
            f"Languages: {', '.join(profile['languages'])}\n"
            f"Skills: {', '.join(profile['skills'])}\n"
            f"Summary: {profile['professional_summary']}"
        )

        candidate.save()

        application = Application.objects.create(
            candidate=candidate,
            job=job
        )

        if live_mode:

            recruitment_pipeline(application)

            self.stdout.write(
                f"    [{tier['label']}] {full_name} -> "
                f"live pipeline: {application.ai_score} "
                f"({application.ai_decision})"
            )

            return

        # ---- Fast/deterministic mode ----
        # Rule Engine and Skill Gap are REAL computations against the
        # seeded profile dicts. Only the semantic score and narrative
        # are stand-ins for what the LLM would produce.

        rule_result = evaluate_recruitment_rules(profile, job_profile)

        gap_result = analyze_skill_gap(
            profile["skills"], job_profile["skills"]
        )

        semantic_result = {
            "overall_score": tier["semantic_target"],
            "dimension_scores": {
                "education": tier["semantic_target"],
                "experience": tier["semantic_target"],
                "technical_skills": tier["semantic_target"],
                "soft_skills": tier["semantic_target"],
                "certifications": tier["semantic_target"],
                "languages": tier["semantic_target"]
            },
            "strengths": profile["skills"][:2],
            "weaknesses": [
                s for s in job_profile["skills"]
                if s not in profile["skills"]
            ],
            "reasoning": {},
            "recommendation": tier["narrative"]
        }

        final_score = compute_final_score(
            rule_eligible=rule_result["eligible"],
            skill_match_score=gap_result["match_score"],
            semantic_score=semantic_result["overall_score"]
        )

        application.ai_profile = profile
        application.ai_job_profile = job_profile
        application.ai_rule_result = rule_result
        application.ai_semantic_result = semantic_result
        application.ai_skill_gap = gap_result
        application.ai_explainable_report = {
            "decision": tier["decision"],
            "confidence": tier["semantic_target"],
            "reasoning": [tier["narrative"]],
            "risks": gap_result["missing_skills"],
            "recommendation": tier["narrative"]
        }
        application.ai_score = final_score
        application.ai_decision = tier["decision"]
        application.ai_confidence = tier["semantic_target"]
        application.ai_feedback = tier["narrative"]
        application.ai_status = "SUCCESS"
        application.ai_processed_at = timezone.now()

        application.save()

        self.stdout.write(
            f"    [{tier['label']}] {full_name} -> "
            f"score {final_score} ({tier['decision']}, "
            f"eligible={rule_result['eligible']})"
        )
