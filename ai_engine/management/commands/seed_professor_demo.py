"""
Usage (on Render, via Build Command, or locally):

    python manage.py seed_professor_demo
    python manage.py seed_professor_demo --reset

Seeds ONE job ("ICT Officer") with the exact requirements text given
for the Professor Jo demo, and THREE named candidates (Maria da
Costa, Joao Martins, Paulo Soares) with the exact profiles given --
a strong, a medium, and a weak/irrelevant fit, so Ranking/Human
Review has a realistic spread to walk through live.

DESIGN NOTE: this is a SEPARATE command from seed_demo_data.py on
purpose -- that command's Strong/Medium/Weak Candidate A/B/C dataset
is what Phase 17's `evaluate_screening` regression test checks
against fixed expected values (88/64/18). Reusing/editing that
command for this differently-named dataset would risk breaking that
regression check. This command touches nothing there.

Always runs through the REAL recruitment_pipeline() (real CV text ->
real extract_text_from_pdf() -> real LLM calls via whichever
LLM_PROVIDER is configured -- Ollama locally, online_gemma on
Render). No score is hand-typed; if Ollama/online_gemma is
unreachable, the pipeline degrades the same way it does for a real
applicant (see recruitment_pipeline.py's own error handling) -- this
command does not fake a result.
"""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, Permission
from talent.models import Job, Skill, Candidate, Application
from ai_engine.services.recruitment_pipeline import recruitment_pipeline
from ai_engine.services.job_pipeline import process_job

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    FPDF = None


JOB_TITLE = "ICT Officer"

JOB_DEPARTMENT = "Ministry of Public Administration"

JOB_DESCRIPTION = (
    "The Civil Service Commission of Timor-Leste is seeking a qualified "
    "ICT Officer to support information systems, networking, and "
    "technical operations across government offices."
)

JOB_REQUIREMENTS = (
    "- Bachelor degree in IT / Computer Science / Information Systems / "
    "Computer Engineering or related field\n"
    "- Minimum 2 years relevant ICT experience\n"
    "- Networking\n"
    "- Database\n"
    "- System administration\n"
    "- Information security\n"
    "- Troubleshooting\n"
    "- At least one official Timor-Leste language\n"
    "- ICT training/certification desirable\n"
    "- Digital government/public-sector information systems experience "
    "desirable\n"
    "- Objective and evidence-based selection"
)

SKILL_NAMES = [
    "Networking",
    "Database",
    "System Administration",
    "Information Security",
    "Troubleshooting",
    "Programming",
    "ICT",
    "Digital Government",
    "Public Sector Information Systems",
]

CANDIDATES = [
    {
        "full_name": "Maria da Costa",
        "email": "maria.dacosta@example.tl",
        "cv_text": (
            "Maria da Costa\n"
            "Bachelor of Computer Science\n\n"
            "Professional Experience: 5 years of ICT / government "
            "systems experience.\n"
            "Responsibilities: network administration, database "
            "administration (PostgreSQL/MySQL), Linux and Windows "
            "Server administration, information security, technical "
            "troubleshooting, supporting public-sector information "
            "systems.\n\n"
            "Skills: Networking, Database Administration (PostgreSQL, "
            "MySQL), System Administration (Linux, Windows Server), "
            "Information Security, Troubleshooting, Digital Government "
            "Systems.\n\n"
            "Certifications: CCNA, Database Administration Training.\n\n"
            "Languages: Tetum, Portuguese, English."
        ),
    },
    {
        "full_name": "Joao Martins",
        "email": "joao.martins@example.tl",
        "cv_text": (
            "Joao Martins\n"
            "Bachelor of Information Systems\n\n"
            "Professional Experience: 2 years of private-sector IT "
            "support.\n"
            "Responsibilities: network support, Windows administration, "
            "basic database support, technical troubleshooting.\n\n"
            "Skills: Networking, Windows Administration, Basic Database "
            "Support, Troubleshooting.\n\n"
            "Certifications: Microsoft Office Specialist.\n\n"
            "Languages: Tetum, English.\n\n"
            "Note: no government ICT experience. Limited information "
            "security experience."
        ),
    },
    {
        "full_name": "Paulo Soares",
        "email": "paulo.soares@example.tl",
        "cv_text": (
            "Paulo Soares\n"
            "Bachelor of Business Administration\n\n"
            "Professional Experience: 3 years as an administrative "
            "assistant.\n"
            "Responsibilities: office administration, customer service, "
            "documentation.\n\n"
            "Skills: Office Administration, Customer Service, "
            "Documentation.\n\n"
            "Certifications: Office Administration Certification.\n\n"
            "Languages: Tetum, Indonesian.\n\n"
            "Note: no relevant ICT skills or experience."
        ),
    },
]


def build_cv_pdf_bytes(text):

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    for line in text.split("\n"):
        pdf.multi_cell(0, 7, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output(dest="S"))


class Command(BaseCommand):

    help = (
        "Seeds the 'ICT Officer' job and the Maria/Joao/Paulo demo "
        "candidates for the Professor Jo demo, via the real pipeline."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete any existing job/candidates with these exact "
                 "names first, then reseed.",
        )

    def _ensure_admin_user(self):
        """
        Idempotent -- safe to call on every single deploy (this is
        the whole point: no more editing Build Command to add this
        temporarily then remove it again). Only creates/updates
        anything if ADMIN_USERNAME is actually set as an environment
        variable; does nothing otherwise, so this is also safe to
        leave in place for local development where those variables
        are never set.
        """

        username = os.environ.get("ADMIN_USERNAME", "").strip()

        if not username:
            return

        email = os.environ.get("ADMIN_EMAIL", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "").strip()

        if not password:
            self.stdout.write(
                self.style.WARNING(
                    "ADMIN_USERNAME is set but ADMIN_PASSWORD is not -- "
                    "skipping admin user setup."
                )
            )
            return

        User = get_user_model()

        role, _ = Role.objects.get_or_create(name="Super Admin")

        permission, _ = Permission.objects.get_or_create(
            code="recruitment_manage",
            defaults={"name": "Manage Recruitment"}
        )

        role.permissions.add(permission)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email}
        )

        user.set_password(password)
        user.is_verified = True
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.role = role

        if email:
            user.email = email

        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Admin user '{username}' ready (created={created})."
            )
        )

    def handle(self, *args, **options):

        if FPDF is None:
            self.stderr.write(
                self.style.ERROR(
                    "fpdf2 is not installed -- cannot generate demo CVs."
                )
            )
            return

        self._ensure_admin_user()

        if options["reset"]:
            Job.objects.filter(title=JOB_TITLE).delete()
            Candidate.objects.filter(
                email__in=[c["email"] for c in CANDIDATES]
            ).delete()
            self.stdout.write("Existing demo job/candidates removed.")

        with transaction.atomic():

            skills = []

            for name in SKILL_NAMES:
                skill, _ = Skill.objects.get_or_create(name=name)
                skills.append(skill)

            job, created = Job.objects.get_or_create(
                title=JOB_TITLE,
                defaults={
                    "department": JOB_DEPARTMENT,
                    "description": JOB_DESCRIPTION,
                    "requirements": JOB_REQUIREMENTS,
                },
            )

            job.skills.set(skills)
            job.save()

        self.stdout.write(
            f"Job '{JOB_TITLE}' ready (created={created})."
        )

        if job.ai_processed:
            self.stdout.write(
                "  -> ai_job_profile already generated, skipping "
                "process_job() to avoid an unnecessary LLM call "
                "(use --reset to force regeneration)."
            )
        else:
            self.stdout.write(
                "  -> Running process_job() to generate ai_job_profile "
                "and job-level RAG evidence (real LLM call + real "
                "retrieval, cached for every candidate below)..."
            )
            try:
                process_job(job)
                job.refresh_from_db()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  -> job.ai_processed={job.ai_processed}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"  -> process_job did not complete: {e}"
                    )
                )

        for candidate_data in CANDIDATES:

            existing = Candidate.objects.filter(
                email=candidate_data["email"]
            ).first()

            if existing:
                self.stdout.write(
                    f"Candidate '{candidate_data['full_name']}' already "
                    f"exists, skipping creation (use --reset to rebuild)."
                )
                continue

            pdf_bytes = build_cv_pdf_bytes(candidate_data["cv_text"])

            candidate = Candidate.objects.create(
                full_name=candidate_data["full_name"],
                email=candidate_data["email"],
            )

            candidate.cv_file.save(
                f"{candidate_data['full_name'].replace(' ', '_')}.pdf",
                ContentFile(pdf_bytes),
                save=False,
            )

            candidate.extracted_text = candidate_data["cv_text"]
            candidate.save()

            application = Application.objects.create(
                candidate=candidate,
                job=job,
            )

            self.stdout.write(
                f"Running real pipeline for {candidate.full_name}..."
            )

            try:
                recruitment_pipeline(application)
                application.refresh_from_db()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  -> score={application.ai_score} "
                        f"decision={application.ai_decision}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"  -> pipeline did not complete "
                        f"(ai_status={application.ai_status}): {e}"
                    )
                )

        self.stdout.write(self.style.SUCCESS("Done."))