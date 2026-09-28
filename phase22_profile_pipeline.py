"""
PHASE 22 -- PERFORMANCE PROFILING INSTRUMENTATION (read-only, diagnostic only)

Purpose
-------
Measure ACTUAL wall-clock timing of each stage of recruitment_pipeline()
for a real, already-submitted Application, using the exact same
production functions, the same model (gemma3:4b via Ollama), the same
Candidate Legal RAG configuration/timeout (45s), and the same feature
flags -- without saving anything, without touching the database beyond
a read, and without modifying a single line of production code.

This script imports the real pipeline functions and calls them in the
same order recruitment_pipeline() does, wrapping each stage with
time.perf_counter(). It never calls application.save(), never creates
a migration, never changes scoring, RAG, or the model, and never
commits/pushes/deploys anything.

Scope discipline (per Phase 22 instructions):
  - Does NOT edit recruitment_pipeline.py, llm_candidate_profile.py,
    llm_reasoning.py, candidate_legal_rag.py, recruitment_rules.py,
    rag/*, compute_final_score(), DB schema, or production config.
  - Lives entirely outside the production package (this file is not
    imported by any production code path).
  - Read-only DB access: fetches an existing Application by id and
    reads its already-extracted candidate.extracted_text and
    job.ai_job_profile / job.ai_rag_context. Nothing is written back.

Honest limitations (stated up front, not hidden in the output):
  1. "CV extraction / OCR" already happened when the candidate
     originally uploaded their CV (Candidate.extracted_text is read
     from the DB here, already extracted) -- it is NOT part of
     recruitment_pipeline()'s runtime and is reported as N/A / 0.00s
     with this note, not silently omitted.
  2. analyze_cv()'s internal per-ATTEMPT timing (attempt 1 vs retry 2
     vs retry 3 individually) is not separately instrumented inside
     llm_candidate_profile.py (that would require editing production
     code, which this phase forbids). This script captures analyze_cv()'s
     own stdout (its existing "attempt X/3" print lines -- unchanged,
     already in production code) to report the RETRY COUNT accurately,
     and reports the TOTAL analyze_cv() wall time as one figure. It does
     NOT report a false per-attempt time breakdown.
  3. Likewise, generate_recruitment_assessment() (the fused reasoning
     call) is timed as one whole unit. A true breakdown into "prompt
     construction / Ollama inference / response parsing" would require
     instrumenting llm_reasoning.py internally, which is out of scope
     for this phase. This script reports prompt-construction time as
     "not separately observable without editing production code" rather
     than guessing a split.
  4. Rule Engine and Skill Gap Analysis run concurrently in production
     (ThreadPoolExecutor, max_workers=2). This script preserves that
     exact concurrency (same ThreadPoolExecutor call), and times each
     of the two callables individually via a non-mutating wrapper
     closure defined in THIS script only -- the wrapper adds a
     perf_counter() call around the unmodified production function, it
     does not alter the production function itself.

Usage
-----
    python phase22_profile_pipeline.py --application-id 49 --runs 3

See PART B in the chat reply for the exact PowerShell command.
"""

import argparse
import io
import json
import os
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402
django.setup()  # noqa: E402

# ---- Unmodified production imports (read-only usage) ----------------
from ai_engine.services.llm_candidate_profile import analyze_cv, DEFAULT_PROFILE  # noqa: E402
from ai_engine.services.llm_reasoning import generate_recruitment_assessment, split_assessment  # noqa: E402
from ai_engine.services.skill_gap_analysis import skill_gap_analysis  # noqa: E402
from ai_engine.services.recruitment_rules import evaluate_recruitment_rules  # noqa: E402
from ai_engine.services.model_config import NEW_CANDIDATE_RAG  # noqa: E402
from ai_engine.services.candidate_legal_rag import get_candidate_legal_evidence  # noqa: E402
from talent.models import Application  # noqa: E402


def timed(label, fn, *args, **kwargs):
    """Call fn(*args, **kwargs) unmodified, return (result, elapsed_seconds)."""
    t0 = perf_counter()
    result = fn(*args, **kwargs)
    elapsed = perf_counter() - t0
    return result, elapsed


def profile_one_run(application_id, run_index):
    """
    Run ONE profiling pass against a real, already-submitted
    Application. Read-only: application is fetched but never saved.
    Returns a dict of stage -> seconds, plus a few diagnostic counters.
    """

    stages = {}

    # =====================================================
    # DB READ (the only DB access this script performs; no writes)
    # =====================================================
    t0 = perf_counter()
    application = Application.objects.select_related(
        "candidate", "job"
    ).get(id=application_id)
    stages["db_read_application"] = perf_counter() - t0

    cv_text = application.candidate.extracted_text
    job_profile = application.job.ai_job_profile
    rag_context = application.job.ai_rag_context or {}

    if not cv_text:
        raise ValueError(
            f"Application {application_id}: candidate.extracted_text is "
            "empty -- pick an application whose candidate CV was already "
            "successfully extracted (this script does not perform OCR)."
        )
    if not job_profile:
        raise ValueError(
            f"Application {application_id}: job.ai_job_profile is empty -- "
            "pick a job that already has an AI profile generated."
        )

    # CV extraction/OCR already happened at upload time -- not part of
    # this pipeline run. Reported explicitly, not silently dropped.
    stages["cv_extraction_ocr"] = 0.0
    stages["cv_extraction_ocr_note"] = (
        "N/A for this run -- extracted_text was already stored on the "
        "Candidate record before this application was processed; OCR/"
        "extraction time is not part of recruitment_pipeline()'s runtime."
    )

    # =====================================================
    # STEP 1: CV parsing (analyze_cv) -- capture its own stdout
    # (unmodified production print statements) to count attempts,
    # without editing llm_candidate_profile.py.
    # =====================================================
    captured = io.StringIO()
    t0 = perf_counter()
    with redirect_stdout(captured):
        profile = analyze_cv(cv_text)
    stages["cv_parsing_total"] = perf_counter() - t0

    captured_text = captured.getvalue()
    sys.stdout.write(captured_text)  # still show the real logs live

    attempt_lines = re.findall(
        r"attempt (\d+)/(\d+)", captured_text, flags=re.IGNORECASE
    )
    stages["cv_parsing_attempts_observed"] = len(attempt_lines)
    stages["cv_parsing_max_attempts_seen"] = (
        int(attempt_lines[-1][1]) if attempt_lines else None
    )

    # Mirror (read-only, does not raise/stop the script) the SAME
    # correctness guard now live in recruitment_pipeline.py, purely to
    # report whether this particular run would have been routed to
    # ai_status="FAILED" in production -- does not call analyze_cv()
    # again, does not touch the DB, does not affect timing below.
    would_be_technical_failure = (
        not any(key in profile for key in DEFAULT_PROFILE)
        or "error" in profile
    )
    stages["cv_parsing_would_be_technical_failure"] = would_be_technical_failure

    if would_be_technical_failure:
        # Stop this run's timing here -- in production the pipeline
        # would raise and go straight to ai_status="FAILED", skipping
        # every step below. Report what we have and return early so
        # the numbers aren't misleading (we do NOT fabricate timings
        # for steps production would never have reached).
        stages["run_stopped_early"] = (
            "analyze_cv() returned a technical-failure profile on this "
            "run -- production would raise here (ai_status=FAILED). "
            "Steps below were not executed, consistent with production "
            "behavior; re-run to get a full profile for a successful "
            "parse."
        )
        return stages

    # =====================================================
    # STEP 2: Rule Engine + Skill Gap (same ThreadPoolExecutor call as
    # production; each callable individually timed via a local wrapper
    # closure -- the wrapper is new, the wrapped functions are not).
    # =====================================================
    rule_timing = {}
    gap_timing = {}

    def _timed_rule_engine():
        t = perf_counter()
        res = evaluate_recruitment_rules(profile, job_profile)
        rule_timing["seconds"] = perf_counter() - t
        return res

    def _timed_skill_gap():
        t = perf_counter()
        res = skill_gap_analysis(
            profile.get("skills", []), job_profile.get("skills", [])
        )
        gap_timing["seconds"] = perf_counter() - t
        return res

    t0 = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_rule = executor.submit(_timed_rule_engine)
        future_gap = executor.submit(_timed_skill_gap)
        rule_result = future_rule.result()
        gap_result = future_gap.result()
    stages["rule_engine_and_skill_gap_wallclock"] = perf_counter() - t0
    stages["rule_engine_only"] = rule_timing.get("seconds")
    stages["skill_gap_only"] = gap_timing.get("seconds")

    # =====================================================
    # STEP 2.5: Candidate Legal RAG (gated by NEW_CANDIDATE_RAG, same
    # as production; internal breakdown comes from its own returned
    # stats dict -- already exposed by production code, unmodified).
    # =====================================================
    stages["new_candidate_rag_flag"] = NEW_CANDIDATE_RAG
    candidate_legal_evidence = {}
    candidate_rag_stats = None

    if NEW_CANDIDATE_RAG:
        t0 = perf_counter()
        try:
            candidate_legal_evidence, candidate_rag_stats = (
                get_candidate_legal_evidence(
                    profile=profile,
                    job_profile=job_profile,
                    rule_result=rule_result,
                )
            )
        except Exception as e:
            candidate_rag_stats = {"error": str(e)}
        stages["candidate_legal_rag_wallclock"] = perf_counter() - t0
    else:
        stages["candidate_legal_rag_wallclock"] = 0.0
        candidate_rag_stats = {
            "note": "NEW_CANDIDATE_RAG is False -- step skipped, same as production."
        }

    stages["candidate_rag_stats"] = candidate_rag_stats

    # =====================================================
    # STEP 3: Fused semantic matching + explainable AI (timed as one
    # unit -- see module docstring limitation #3).
    # =====================================================
    t0 = perf_counter()
    assessment = generate_recruitment_assessment(
        profile=profile,
        job_profile=job_profile,
        rule_result=rule_result,
        gap_result=gap_result,
        rag_context=rag_context,
        candidate_legal_evidence=candidate_legal_evidence,
    )
    stages["fused_reasoning_llm_call"] = perf_counter() - t0

    t0 = perf_counter()
    semantic_result, report = split_assessment(assessment)
    stages["fused_reasoning_response_parsing"] = perf_counter() - t0

    stages["fused_reasoning_prompt_construction"] = None
    stages["fused_reasoning_prompt_construction_note"] = (
        "Not separately observable without instrumenting llm_reasoning.py "
        "internally (out of scope this phase) -- prompt construction is "
        "included inside fused_reasoning_llm_call above, not double-counted "
        "and not fabricated as a separate figure."
    )

    # No application.save() anywhere in this script. Read-only.
    stages["total"] = sum(
        stages[k] for k in TIMING_KEYS if stages.get(k) is not None
    )

    return stages


# Explicit whitelist of keys that represent SECONDS -- used for the
# total/aggregate math instead of duck-typing on isinstance(v, (int,
# float)), which would incorrectly sum in non-timing integer fields
# such as cv_parsing_attempts_observed or cv_parsing_max_attempts_seen
# (caught during self-verification before this script was delivered).
TIMING_KEYS = [
    "db_read_application",
    "cv_extraction_ocr",
    "cv_parsing_total",
    "rule_engine_and_skill_gap_wallclock",
    "candidate_legal_rag_wallclock",
    "fused_reasoning_llm_call",
    "fused_reasoning_response_parsing",
]


def fmt(seconds):
    if seconds is None:
        return "n/a"
    return f"{seconds:.2f}s"


def pct(part, total):
    if part is None or not total:
        return "n/a"
    return f"{(part / total) * 100:.1f}%"


def print_run_report(run_index, stages):
    total = stages.get("total", 0.0)

    print(f"\n{'=' * 60}")
    print(f"PHASE 22 PERFORMANCE PROFILE -- RUN {run_index}")
    print(f"{'=' * 60}\n")

    if stages.get("run_stopped_early"):
        print("!! RUN STOPPED EARLY (matches production behavior) !!")
        print(stages["run_stopped_early"])
        print(f"\nStages actually executed before stopping:")
        print(f"  db_read_application : {fmt(stages['db_read_application'])}")
        print(f"  cv_extraction_ocr   : {fmt(stages['cv_extraction_ocr'])} "
              f"({stages['cv_extraction_ocr_note']})")
        print(f"  cv_parsing_total    : {fmt(stages['cv_parsing_total'])}  "
              f"(attempts observed: {stages['cv_parsing_attempts_observed']})")
        return

    print(f"Total runtime: {fmt(total)}\n")

    print(f"DB read (application)         : {fmt(stages['db_read_application'])}  "
          f"({pct(stages['db_read_application'], total)})")
    print(f"CV extraction/OCR             : {fmt(stages['cv_extraction_ocr'])}  "
          f"(N/A -- see note)")
    print(f"CV parsing (analyze_cv total) : {fmt(stages['cv_parsing_total'])}  "
          f"({pct(stages['cv_parsing_total'], total)})")
    print(f"  Attempts observed            : {stages['cv_parsing_attempts_observed']}"
          f" (retry count = attempts - 1)")
    print(f"Rule Engine + Skill Gap (wall) : {fmt(stages['rule_engine_and_skill_gap_wallclock'])}  "
          f"({pct(stages['rule_engine_and_skill_gap_wallclock'], total)})")
    print(f"  Rule Engine only (thread)     : {fmt(stages['rule_engine_only'])}")
    print(f"  Skill Gap only (thread)       : {fmt(stages['skill_gap_only'])}")
    print(f"Candidate Legal RAG            : {fmt(stages['candidate_legal_rag_wallclock'])}  "
          f"({pct(stages['candidate_legal_rag_wallclock'], total)})")
    if isinstance(stages.get("candidate_rag_stats"), dict):
        print(f"  {json.dumps(stages['candidate_rag_stats'], indent=2)}")
    print(f"Fused reasoning (LLM call)     : {fmt(stages['fused_reasoning_llm_call'])}  "
          f"({pct(stages['fused_reasoning_llm_call'], total)})")
    print(f"  Prompt construction           : {stages['fused_reasoning_prompt_construction_note']}")
    print(f"Fused reasoning (parse result) : {fmt(stages['fused_reasoning_response_parsing'])}  "
          f"({pct(stages['fused_reasoning_response_parsing'], total)})")
    measured_sum = sum(
        stages[k] for k in TIMING_KEYS if stages.get(k) is not None
    )
    print(f"\nOther/unaccounted overhead (total - sum of measured stages): "
          f"{fmt(total - measured_sum)}")


def print_aggregate_report(all_runs):
    complete_runs = [r for r in all_runs if "total" in r]

    print(f"\n{'=' * 60}")
    print("PHASE 22 -- AGGREGATE ACROSS RUNS (no outliers removed)")
    print(f"{'=' * 60}\n")

    if len(complete_runs) < len(all_runs):
        print(f"NOTE: {len(all_runs) - len(complete_runs)} of {len(all_runs)} "
              "run(s) stopped early (CV parsing technical failure) and are "
              "EXCLUDED from the numeric aggregate below, but are reported "
              "individually above. This is not outlier removal -- those "
              "runs never reached the later stages, so there is nothing to "
              "average for them.\n")

    if not complete_runs:
        print("No complete runs to aggregate.")
        return

    keys_of_interest = [
        "db_read_application",
        "cv_parsing_total",
        "rule_engine_and_skill_gap_wallclock",
        "candidate_legal_rag_wallclock",
        "fused_reasoning_llm_call",
        "fused_reasoning_response_parsing",
        "total",
    ]

    header = f"{'Stage':35s} {'mean':>8s} {'median':>8s} {'min':>8s} {'max':>8s}"
    print(header)
    print("-" * len(header))

    for key in keys_of_interest:
        values = [r[key] for r in complete_runs if r.get(key) is not None]
        if not values:
            continue
        print(
            f"{key:35s} "
            f"{statistics.mean(values):8.2f} "
            f"{statistics.median(values):8.2f} "
            f"{min(values):8.2f} "
            f"{max(values):8.2f}"
        )

    per_run_bits = [
        f"run{i + 1}={fmt(r.get('total'))}"
        for i, r in enumerate(all_runs) if "total" in r
    ]
    print(f"\nPer-run totals: {', '.join(per_run_bits)}")
    print(f"\nReference baselines (from earlier live application runs, NOT "
          f"produced by this script): normal ~98.97s, previous slow ~230.25s.")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 22 read-only pipeline profiling (diagnostic only)."
    )
    parser.add_argument(
        "--application-id", type=int, required=True,
        help="ID of an existing Application whose candidate CV was "
             "already successfully extracted and whose job already has "
             "an AI profile (e.g. the Joao Martins or Maria da Costa "
             "application from earlier testing)."
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Number of repeated profiling passes (default 3, per Phase "
             "22 reproducibility requirement)."
    )
    args = parser.parse_args()

    print("PHASE 22 INSTRUMENTATION -- read-only, diagnostic only.")
    print("No database writes. No production code modified. No commit/push.")
    print(f"application_id={args.application_id}  runs={args.runs}\n")

    all_runs = []

    for i in range(1, args.runs + 1):
        stages = profile_one_run(args.application_id, i)
        print_run_report(i, stages)
        all_runs.append(stages)

    print_aggregate_report(all_runs)


if __name__ == "__main__":
    main()