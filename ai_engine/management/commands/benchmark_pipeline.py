"""
Usage:

    python manage.py benchmark_pipeline
    python manage.py benchmark_pipeline --scenario-a-runs 3
    python manage.py benchmark_pipeline --keep

INSTRUMENTATION ONLY. This command does not modify any pipeline
behavior, prompt, model, or Ollama configuration. It measures the
EXISTING code exactly as it runs today by:

  1. Timing black-box calls to the real, unmodified functions
     (extract_text_from_pdf, recruitment_pipeline, process_job) --
     zero lines changed in Phase 11-18 files.

  2. Monkey-patching (at runtime, in this process only -- nothing
     written to disk) the three HTTP entry points every LLM call in
     this codebase goes through: requests.post, requests.Session.post,
     and ollama.chat. The patch calls the REAL function and returns
     its REAL, unmodified result -- it only *observes* start/end time
     and reads Ollama's own response fields (total_duration,
     load_duration, prompt_eval_count, eval_count), which Ollama
     already includes in every response regardless of this script.

This lets "RAG retrieval / prompt building / post-processing" time be
computed honestly as (total wall time of a black-box call) minus
(sum of the LLM call durations captured inside it) -- without ever
touching rag_pipeline.py, question_decomposer.py, evidence_coverage.py,
groundedness.py, or recruitment_pipeline.py.

Two scenarios, measured and reported SEPARATELY as instructed:

  Scenario A: one candidate applying to a job whose RAG context is
  ALREADY cached (the common case -- second and later applicants to
  the same job). Run 3x by default so cold vs warm behavior is
  visible in the reported table, never averaged away.

  Scenario B: creating a brand-new job (which triggers job-description
  parsing + the full multi-call RAG pipeline to build its cached
  context), then one candidate applying to it.

All test data (job/candidate/application) is deleted at the end
unless --keep is passed.
"""

import time
import statistics

import requests

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from talent.models import Job, Skill, Candidate, Application
from talent.utils import extract_text_from_pdf
from ai_engine.services.recruitment_pipeline import recruitment_pipeline
from ai_engine.services.job_pipeline import process_job

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    FPDF = None


JOB_PROFILE = {
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
        "Supports ministry information systems and provides ICT "
        "technical support."
    )
}

CANDIDATE_CONTENT = {
    "education": "Bachelor of Information Technology",
    "years_experience": 4,
    "languages": ["English", "Tetum"],
    "certifications": [],
    "skills": [
        "Database Management",
        "Network Administration",
        "System Security",
        "Technical Support"
    ],
    "professional_summary": (
        "ICT professional with four years of experience supporting "
        "government information systems, network infrastructure, "
        "and technical support operations."
    )
}


# =====================================================================
# LLM CALL INTERCEPTOR (observation only -- never alters behavior)
# =====================================================================

class LLMCallRecorder:
    """
    Wraps the three HTTP entry points every LLM call goes through in
    this codebase. Each wrapped function still calls the REAL
    original and returns its REAL result completely unmodified --
    this class only records timing and reads fields Ollama already
    puts in its own response.
    """

    LABEL_RULES = [
        ("decision\":\"\",\"confidence", "explainable_report"),
        ("recruitment expert", "semantic_match_or_job_parse"),
        ("skill_gap", "job_or_cv_extraction"),
        ("years_experience", "cv_or_job_extraction"),
        ("claim", "rag_claim_verification"),
        ("groundedness", "rag_groundedness"),
        ("decompose", "rag_decompose"),
    ]

    def __init__(self):
        self.calls = []
        self._orig_requests_post = None
        self._orig_session_post = None
        self._orig_ollama_chat = None

    def _label_for(self, prompt_text):

        text = (prompt_text or "").lower()

        if "reasoning" in text and "risks" in text and "decision" in text:
            return "explainable_report"

        if "dimension_scores" in text:
            return "semantic_match"

        if "claims" in text and "evidence" in text and "supported" in text:
            return "rag_claim_verification"

        if "groundedness" in text or "unsupported claims" in text:
            return "rag_groundedness"

        if "decompose" in text or "independent requests" in text:
            return "rag_decompose"

        if "job description" in text or "job posting" in text:
            return "job_description_parse"

        if "cv" in text or "resume" in text or "curriculum" in text:
            return "cv_extraction"

        return "rag_answer_generation_or_other"

    def _record(self, label, duration, response_json):

        entry = {
            "label": label,
            "duration": duration,
            "total_duration_ns": response_json.get("total_duration"),
            "load_duration_ns": response_json.get("load_duration"),
            "prompt_eval_count": response_json.get("prompt_eval_count"),
            "eval_count": response_json.get("eval_count"),
        }

        self.calls.append(entry)

    def _wrapped_requests_post(self, url, *args, **kwargs):

        prompt = ""

        json_body = kwargs.get("json")

        if isinstance(json_body, dict):
            prompt = json_body.get("prompt", "")

        start = time.perf_counter()

        response = self._orig_requests_post(url, *args, **kwargs)

        duration = time.perf_counter() - start

        try:
            data = response.json()
        except Exception:
            data = {}

        self._record(self._label_for(prompt), duration, data)

        return response

    def _wrapped_session_post(self, session_self, url, *args, **kwargs):

        prompt = ""

        json_body = kwargs.get("json")

        if isinstance(json_body, dict):
            prompt = json_body.get("prompt", "")

        start = time.perf_counter()

        response = self._orig_session_post(session_self, url, *args, **kwargs)

        duration = time.perf_counter() - start

        try:
            data = response.json()
        except Exception:
            data = {}

        self._record(self._label_for(prompt), duration, data)

        return response

    def _wrapped_ollama_chat(self, *args, **kwargs):

        messages = kwargs.get("messages") or (args[1] if len(args) > 1 else [])

        prompt = ""

        if messages:
            prompt = messages[0].get("content", "")

        start = time.perf_counter()

        response = self._orig_ollama_chat(*args, **kwargs)

        duration = time.perf_counter() - start

        response_dict = (
            response if isinstance(response, dict) else dict(response)
        )

        self._record(self._label_for(prompt), duration, response_dict)

        return response

    def __enter__(self):

        self.calls = []

        self._orig_requests_post = requests.post
        requests.post = self._wrapped_requests_post

        self._orig_session_post = requests.Session.post
        requests.Session.post = self._wrapped_session_post

        try:
            import ollama
            self._orig_ollama_chat = ollama.chat
            ollama.chat = self._wrapped_ollama_chat
        except ImportError:
            self._orig_ollama_chat = None

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):

        requests.post = self._orig_requests_post
        requests.Session.post = self._orig_session_post

        if self._orig_ollama_chat is not None:
            import ollama
            ollama.chat = self._orig_ollama_chat


def build_cv_pdf_bytes(candidate_name, content):

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, candidate_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=11)

    lines = [
        f"Education: {content['education']}",
        f"Years of Experience: {content['years_experience']}",
        f"Languages: {', '.join(content['languages'])}",
        f"Skills: {', '.join(content['skills'])}",
        f"Summary: {content['professional_summary']}"
    ]

    for line in lines:
        pdf.multi_cell(0, 8, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output(dest="S"))


class Command(BaseCommand):

    help = (
        "Phase: Performance baseline. Pure instrumentation -- times "
        "the existing pipeline exactly as-is, changes nothing."
    )

    def add_arguments(self, parser):

        parser.add_argument("--scenario-a-runs", type=int, default=3)
        parser.add_argument("--keep", action="store_true")

    def handle(self, *args, **options):

        if FPDF is None:
            self.stderr.write(self.style.ERROR("fpdf2 is not installed."))
            return

        created_candidates = []
        created_jobs = []

        try:

            # =========================================================
            # SCENARIO A: existing job, RAG context already cached
            # =========================================================

            self.stdout.write(self.style.NOTICE(
                "\n" + "=" * 70 +
                "\nSCENARIO A -- existing job, cached RAG context" +
                "\n" + "=" * 70
            ))

            job_a = Job.objects.create(
                title="BENCHMARK - ICT Officer (existing)",
                department="Benchmark (temporary)",
                description="Temporary job for performance benchmarking.",
                requirements="See ai_job_profile.",
                ai_job_profile=JOB_PROFILE,
                ai_processed=True,
                ai_processed_at=timezone.now(),
                ai_rag_context={
                    "query": "benchmark placeholder query",
                    "answer": "benchmark placeholder answer",
                    "evidence": [{
                        "document": "Civil Service Commission Law",
                        "chunk_id": "benchmark-1",
                        "score": 0.61,
                        "excerpt": (
                            "The Commission shall ensure that "
                            "recruitment and selection for the "
                            "Public Service is based on merit."
                        )
                    }],
                    "best_evidence_score": 0.61,
                    "grounded": True,
                    "error": None
                }
            )

            for skill_name in JOB_PROFILE["skills"]:
                skill, _ = Skill.objects.get_or_create(name=skill_name)
                job_a.skills.add(skill)

            created_jobs.append(job_a)

            scenario_a_rows = []

            for run_number in range(1, options["scenario_a_runs"] + 1):

                row = self._run_single_application(
                    job_a, run_number, created_candidates
                )

                scenario_a_rows.append(row)

                cold_tag = "COLD" if run_number == 1 else "warm"

                self.stdout.write(
                    f"  Run {run_number} [{cold_tag}]: "
                    f"pdf={row['pdf_time']:.2f}s "
                    f"total={row['total_time']:.2f}s "
                    f"llm_calls={len(row['llm_calls'])} "
                    f"llm_time={row['llm_time_sum']:.2f}s "
                    f"other={row['other_time']:.2f}s"
                )

            self._print_scenario_a_table(scenario_a_rows)

            # =========================================================
            # SCENARIO B: brand-new job (must build RAG context)
            # =========================================================

            self.stdout.write(self.style.NOTICE(
                "\n" + "=" * 70 +
                "\nSCENARIO B -- new job, RAG context built from scratch" +
                "\n" + "=" * 70
            ))

            job_b = Job.objects.create(
                title="BENCHMARK - ICT Officer (new)",
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

            with LLMCallRecorder() as recorder:

                start = time.perf_counter()

                process_job(job_b)

                process_job_time = time.perf_counter() - start

            job_creation_llm_time = sum(c["duration"] for c in recorder.calls)

            self.stdout.write(
                f"  process_job() total: {process_job_time:.2f}s "
                f"| LLM calls: {len(recorder.calls)} "
                f"| LLM time: {job_creation_llm_time:.2f}s "
                f"| non-LLM (retrieval/decompose-glue): "
                f"{process_job_time - job_creation_llm_time:.2f}s"
            )

            for i, call in enumerate(recorder.calls, 1):
                self.stdout.write(
                    f"    [job-creation call {i}] {call['label']}: "
                    f"{call['duration']:.2f}s "
                    f"(prompt_tokens={call['prompt_eval_count']}, "
                    f"output_tokens={call['eval_count']}, "
                    f"load_duration="
                    f"{(call['load_duration_ns'] or 0) / 1e9:.2f}s)"
                )

            candidate_row = self._run_single_application(
                job_b, "post-job-creation", created_candidates
            )

            self.stdout.write(
                f"\n  First applicant to the new job: "
                f"total={candidate_row['total_time']:.2f}s "
                f"(should be close to Scenario A's warm runs, since "
                f"the RAG context is now cached from process_job() above)"
            )

            self._print_summary(
                scenario_a_rows, process_job_time, job_creation_llm_time,
                candidate_row
            )

        finally:

            if not options["keep"]:

                for c in created_candidates:
                    c.delete()

                for j in created_jobs:
                    j.delete()

                self.stdout.write(
                    "\n(Benchmark job/candidate data deleted. "
                    "Pass --keep to inspect in the UI instead.)"
                )

    def _run_single_application(self, job, run_label, created_candidates):

        candidate_name = f"Benchmark Candidate {run_label}"

        pdf_bytes = build_cv_pdf_bytes(candidate_name, CANDIDATE_CONTENT)

        # ---- PDF / text processing (timed as a real black-box call) ----

        candidate = Candidate.objects.create(
            full_name=candidate_name,
            email=f"benchmark.{run_label}@example.test",
            education=CANDIDATE_CONTENT["education"],
            years_experience=CANDIDATE_CONTENT["years_experience"],
            languages=", ".join(CANDIDATE_CONTENT["languages"]),
            certifications="",
            candidate_skills=", ".join(CANDIDATE_CONTENT["skills"]),
            professional_summary=CANDIDATE_CONTENT["professional_summary"]
        )

        candidate.cv_file.save(
            f"benchmark_{run_label}.pdf",
            ContentFile(pdf_bytes),
            save=False
        )

        candidate.save()

        created_candidates.append(candidate)

        pdf_start = time.perf_counter()

        extracted_text = extract_text_from_pdf(candidate.cv_file.path)

        pdf_time = time.perf_counter() - pdf_start

        candidate.extracted_text = extracted_text

        candidate.save()

        application = Application.objects.create(
            candidate=candidate,
            job=job
        )

        # ---- Full pipeline, timed as a whole, LLM calls intercepted ----

        with LLMCallRecorder() as recorder:

            total_start = time.perf_counter()

            recruitment_pipeline(application)

            total_time = time.perf_counter() - total_start

        llm_time_sum = sum(c["duration"] for c in recorder.calls)

        other_time = total_time - llm_time_sum

        return {
            "run": run_label,
            "pdf_time": pdf_time,
            "total_time": total_time,
            "llm_calls": recorder.calls,
            "llm_time_sum": llm_time_sum,
            "other_time": other_time,
            "final_score": application.ai_score,
            "decision": application.ai_decision
        }

    def _print_scenario_a_table(self, rows):

        self.stdout.write("\n--- Scenario A: per-run breakdown ---\n")

        header = f"{'Run':<12}{'PDF':>8}{'LLM calls':>12}{'LLM time':>12}{'Other':>10}{'Total':>10}"
        self.stdout.write(header)

        for r in rows:

            tag = "(COLD)" if r["run"] == 1 else "(warm)"

            self.stdout.write(
                f"{str(r['run']) + ' ' + tag:<12}"
                f"{r['pdf_time']:>7.2f}s"
                f"{len(r['llm_calls']):>12}"
                f"{r['llm_time_sum']:>11.2f}s"
                f"{r['other_time']:>9.2f}s"
                f"{r['total_time']:>9.2f}s"
            )

        totals = [r["total_time"] for r in rows]
        warm_totals = totals[1:] if len(totals) > 1 else totals

        self.stdout.write(
            f"\nAll runs   -- min={min(totals):.2f}s max={max(totals):.2f}s "
            f"avg={statistics.mean(totals):.2f}s"
        )

        if len(warm_totals) > 1:
            self.stdout.write(
                f"Warm only  -- min={min(warm_totals):.2f}s "
                f"max={max(warm_totals):.2f}s "
                f"avg={statistics.mean(warm_totals):.2f}s"
            )

        self.stdout.write("\nPer-call detail, each run:")

        for r in rows:
            self.stdout.write(f"  Run {r['run']}:")
            for i, c in enumerate(r["llm_calls"], 1):
                self.stdout.write(
                    f"    LLM call #{i} [{c['label']}]: "
                    f"{c['duration']:.2f}s "
                    f"(prompt_tokens={c['prompt_eval_count']}, "
                    f"output_tokens={c['eval_count']}, "
                    f"load_duration="
                    f"{(c['load_duration_ns'] or 0) / 1e9:.2f}s)"
                )

    def _print_summary(
        self, scenario_a_rows, process_job_time, job_creation_llm_time,
        candidate_row
    ):

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("BASELINE SUMMARY"))
        self.stdout.write("=" * 70)

        warm_rows = (
            scenario_a_rows[1:] if len(scenario_a_rows) > 1
            else scenario_a_rows
        )

        avg_warm_total = statistics.mean(r["total_time"] for r in warm_rows)
        avg_warm_llm = statistics.mean(r["llm_time_sum"] for r in warm_rows)
        avg_warm_llm_calls = statistics.mean(
            len(r["llm_calls"]) for r in warm_rows
        )

        cold_extra = (
            scenario_a_rows[0]["total_time"] - avg_warm_total
            if len(scenario_a_rows) > 1 else 0
        )

        self.stdout.write(
            f"\nScenario A (existing job), warm-run average:"
        )
        self.stdout.write(f"  Total runtime: {avg_warm_total:.2f}s")
        self.stdout.write(
            f"  LLM calls: {avg_warm_llm_calls:.1f} "
            f"| LLM time: {avg_warm_llm:.2f}s "
            f"({100 * avg_warm_llm / avg_warm_total:.0f}% of total)"
        )
        self.stdout.write(
            f"  Non-LLM overhead (PDF + prompt-build + retrieval-glue "
            f"+ post-processing): {avg_warm_total - avg_warm_llm:.2f}s"
        )

        if len(scenario_a_rows) > 1:
            self.stdout.write(
                f"  Cold-run extra cost vs warm average: "
                f"{cold_extra:+.2f}s"
            )

        self.stdout.write(f"\nScenario B (new job):")
        self.stdout.write(
            f"  process_job() (job parse + RAG context build): "
            f"{process_job_time:.2f}s, of which "
            f"{job_creation_llm_time:.2f}s is LLM time "
            f"({100 * job_creation_llm_time / process_job_time:.0f}%)"
        )
        self.stdout.write(
            f"  First applicant after that: "
            f"{candidate_row['total_time']:.2f}s"
        )
        self.stdout.write(
            f"  Total cold end-to-end (new job + first candidate): "
            f"{process_job_time + candidate_row['total_time']:.2f}s"
        )

        self.stdout.write(
            "\nRead these numbers, don't let me interpret them for you "
            "-- see the report I'll write once you share this output."
        )
