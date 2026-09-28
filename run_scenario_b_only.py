import os
import time

os.environ["NEW_CANDIDATE_RAG"] = "True"

from django.core.management.base import OutputWrapper
from django.core.management import call_command
from django.db import transaction

from ai_engine.management.commands.benchmark_pipeline import (
    Command,
    JOB_PROFILE,
)

from talent.models import Job, Skill

cmd = Command()
cmd.stdout = OutputWrapper(__import__("sys").stdout)

created_candidates = []
created_jobs = []

try:
    print("\n" + "=" * 70)
    print("ISOLATED SCENARIO B -- NEW JOB ONLY")
    print("=" * 70)

    job_b = Job.objects.create(
        title="BENCHMARK - ICT Officer (isolated)",
        department="Benchmark (temporary)",
        description=(
            "The ICT Officer supports the Ministry's information "
            "systems, manages database infrastructure, and "
            "provides technical support to civil service staff. "
            "Requires a Bachelor's degree in Information "
            "Technology and at least 2 years of relevant "
            "experience."
        ),
        requirements="Bachelor's degree, 2+ years ICT experience.",
    )

    for skill_name in JOB_PROFILE["skills"]:
        skill, _ = Skill.objects.get_or_create(name=skill_name)
        job_b.skills.add(skill)

    created_jobs.append(job_b)

    print("\n[1] Running process_job() ...")

    with cmd.__class__.__dict__["_run_single_application"]:
        pass
