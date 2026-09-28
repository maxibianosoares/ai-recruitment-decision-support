"""
PHASE 23 -- num_predict CONTROLLED PERFORMANCE EXPERIMENT (read-only,
diagnostic only -- no database writes, no commit/push/deploy implied).

Purpose
-------
Compares four configurations (Baseline / 512 / 384 / 350) for the
`num_predict` cap on Ollama generation, using the REAL production
functions (analyze_cv, generate_recruitment_assessment) against a real,
already-submitted Application -- so the numbers reflect the actual
pipeline, not a synthetic approximation.

This is possible without touching production BEHAVIOR because
`num_predict` is now an OPTIONAL parameter on generate_json() /
analyze_cv() / generate_recruitment_assessment() (Phase 23 change,
default None -- byte-identical request when not passed). This script is
the ONLY caller in the codebase that passes a non-None value; every
existing production call site (recruitment_pipeline.py) still calls
these functions with no num_predict argument at all, so production
behavior is completely unchanged by this experiment.

Scope discipline (per Phase 23 instructions):
  - Does NOT edit recruitment_pipeline.py, candidate_legal_rag.py,
    recruitment_rules.py, rag/*, compute_final_score(), DB schema, or
    production config.
  - Does NOT change the 45s timeout, the model, or the prompts.
  - Read-only DB access: fetches existing Application(s) by id and
    reads already-extracted data. Nothing is written back
    (no .save() anywhere in this script).
  - Lives entirely outside the production package.

What "FAIL" means here
-----------------------
A configuration/run is marked FAIL if:
  - CV parsing hits the same technical-failure condition
    recruitment_pipeline.py's correctness guard checks for (mirrored
    read-only here, not re-implemented as new logic), OR
  - fused reasoning falls into its own except-branch (empty/invalid
    JSON -- decision=="" and recommendation starts with "Reasoning
    unavailable"), OR
  - dimension_scores is missing any of the 6 required keys, OR
  - "LLM Error:" was logged by generate_json() during the run
    (its own existing exception log, unmodified -- a signal of
    invalid/truncated JSON that this script captures via stdout
    rather than re-parsing anything itself).
Speed is NEVER used to override a FAIL.

Usage
-----
    python phase23_num_predict_benchmark.py --application-ids 49 --runs 3
    python phase23_num_predict_benchmark.py --application-ids 49,52 --runs 5
"""

import argparse
import io
import json
import os
import re
import statistics
import sys
from contextlib import redirect_stdout
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402
django.setup()  # noqa: E402

# ---- Unmodified-behavior production imports (num_predict is opt-in) --
from ai_engine.services.llm_candidate_profile import analyze_cv, DEFAULT_PROFILE  # noqa: E402
from ai_engine.services.llm_reasoning import (  # noqa: E402
    generate_recruitment_assessment,
    DEFAULT_DIMENSION_SCORES,
)
from ai_engine.services.recruitment_rules import evaluate_recruitment_rules  # noqa: E402
from ai_engine.services.skill_gap_analysis import skill_gap_analysis  # noqa: E402
from ai_engine.services.model_config import NEW_CANDIDATE_RAG  # noqa: E402
from ai_engine.services.candidate_legal_rag import get_candidate_legal_evidence  # noqa: E402
from ai_engine.services.llm_service import generate_json  # noqa: E402
from ai_engine.services.model_config import OLLAMA_BASE_URL  # noqa: E402
from talent.models import Application  # noqa: E402

import requests  # noqa: E402


CONFIGS = [
    ("Baseline", None),
    ("512", 512),
    ("384", 384),
    ("350", 350),
]

_LOG_LINE_RE = re.compile(
    r"LLM response length: (\d+) chars \| "
    r"total_duration=(\S+)s load_duration=(\S+)s "
    r"prompt_eval_count=(\S+) prompt_eval_duration=(\S+)s "
    r"eval_count=(\S+) eval_duration=(\S+)s"
)
_ERROR_LINE_RE = re.compile(r"LLM Error: (.+)")


def _num(token):
    """Best-effort parse of a logged token ('n/a' / 'None' / int / float)."""
    if token in ("n/a", "None", None):
        return None
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            return None


def _parse_llm_log(log_text, prefix):
    matches = _LOG_LINE_RE.findall(log_text)
    errors = _ERROR_LINE_RE.findall(log_text)
    out = {
        f"{prefix}_llm_calls_observed": len(matches),
        f"{prefix}_llm_error_count": len(errors),
    }
    if matches:
        last = matches[-1]
        out[f"{prefix}_response_length_chars"] = _num(last[0])
        out[f"{prefix}_prompt_eval_count"] = _num(last[3])
        out[f"{prefix}_eval_count"] = _num(last[5])
        out[f"{prefix}_eval_duration_s"] = _num(last[6])
    else:
        out[f"{prefix}_response_length_chars"] = None
        out[f"{prefix}_prompt_eval_count"] = None
        out[f"{prefix}_eval_count"] = None
        out[f"{prefix}_eval_duration_s"] = None
    return out


def check_ollama_reachable():
    """
    Fast connectivity check BEFORE anything else -- a plain GET to
    Ollama's own /api/tags endpoint (read-only, lists installed
    models, does not touch generation at all). Fails fast and loud if
    Ollama isn't running, instead of burning through the full 4-config
    x N-run x MAX_ATTEMPTS matrix only to discover every single call
    was a connection error (as happened when the pre-flight check
    below didn't catch this -- see note in validate_num_predict_values).
    """
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        print(f"--- Ollama reachable at {OLLAMA_BASE_URL} ---\n")
    except Exception as e:
        raise SystemExit(
            f"\nABORTING: Ollama is not reachable at {OLLAMA_BASE_URL} "
            f"({e}).\nStart Ollama first (open the Ollama app, or run "
            f"'ollama serve'), then re-run this script. No benchmark "
            f"calls were made."
        )


def validate_num_predict_values(values):
    """
    Pre-flight check (per Phase 23 instructions: "pastikan nilai-nilai
    tersebut valid untuk implementasi Ollama yang sedang digunakan")
    -- sends ONE trivial, minimal-cost call per non-baseline value
    directly through generate_json() (same function production uses)
    to confirm Ollama accepts the options.num_predict field without
    error, before spending time on the full benchmark matrix.

    IMPORTANT: generate_json() catches ALL exceptions internally
    (connection errors, timeouts, invalid JSON -- by design, so
    production never crashes on an LLM hiccup) and returns `default`
    instead of raising. That means a plain try/except around
    generate_json() here can NEVER see a connection failure -- it
    always looks like success. Fixed by capturing generate_json()'s
    own stdout (its unmodified "LLM Error: ..." print on any
    exception) and checking THAT instead of relying on a raised
    exception that will never come.
    """
    print("--- Pre-flight: validating num_predict values against this")
    print("    Ollama instance (trivial calls, not part of the benchmark) ---")
    for value in values:
        if value is None:
            print(f"  Baseline (no cap): OK (no options sent, current default behavior)")
            continue

        captured = io.StringIO()
        with redirect_stdout(captured):
            result = generate_json(
                prompt='Return exactly this JSON: {"ok": true}',
                default={},
                num_predict=value,
            )
        log = captured.getvalue()

        if "LLM Error:" in log:
            error_line = next(
                (line for line in log.splitlines() if "LLM Error:" in line), log
            )
            raise SystemExit(
                f"\nABORTING pre-flight: num_predict={value} call failed -- "
                f"{error_line}\nThis usually means Ollama isn't running or "
                f"isn't reachable, not that num_predict itself is invalid. "
                f"Fix connectivity and re-run. No benchmark calls were made."
            )

        print(f"  num_predict={value}: OK (Ollama accepted the request, "
              f"got response={result!r})")
    print()


def run_one_config_pass(config_name, num_predict, application_id, run_index):
    stages = {
        "config": config_name,
        "num_predict": num_predict,
        "application_id": application_id,
        "run": run_index,
    }

    application = Application.objects.select_related(
        "candidate", "job"
    ).get(id=application_id)

    cv_text = application.candidate.extracted_text
    job_profile = application.job.ai_job_profile
    rag_context = application.job.ai_rag_context or {}

    if not cv_text or not job_profile:
        raise ValueError(
            f"Application {application_id}: needs a non-empty "
            "candidate.extracted_text and job.ai_job_profile -- pick an "
            "application already used successfully in Phase 22 (e.g. 49)."
        )

    # ---- CV parsing -----------------------------------------------
    captured = io.StringIO()
    t0 = perf_counter()
    with redirect_stdout(captured):
        profile = analyze_cv(cv_text, num_predict=num_predict)
    stages["cv_parsing_latency"] = perf_counter() - t0

    cv_log = captured.getvalue()
    sys.stdout.write(cv_log)
    stages.update(_parse_llm_log(cv_log, "cv_parsing"))

    # Mirror (read-only) of recruitment_pipeline.py's existing
    # correctness guard -- not new logic, just checked here to report
    # whether this run would be routed to ai_status="FAILED" in
    # production. Does not call analyze_cv() again.
    stages["cv_parsing_technical_failure"] = (
        not any(key in profile for key in DEFAULT_PROFILE)
        or "error" in profile
    )

    if stages["cv_parsing_technical_failure"]:
        stages["status"] = "FAIL (CV parsing technical failure)"
        stages["decision"] = None
        stages["total_runtime"] = stages["cv_parsing_latency"]
        return stages

    # ---- Deterministic, non-LLM inputs to fused reasoning ----------
    rule_result = evaluate_recruitment_rules(profile, job_profile)
    gap_result = skill_gap_analysis(
        profile.get("skills", []), job_profile.get("skills", [])
    )

    candidate_legal_evidence = {}
    if NEW_CANDIDATE_RAG:
        try:
            candidate_legal_evidence, _ = get_candidate_legal_evidence(
                profile=profile, job_profile=job_profile, rule_result=rule_result
            )
        except Exception:
            candidate_legal_evidence = {}

    # ---- Fused reasoning --------------------------------------------
    captured2 = io.StringIO()
    t0 = perf_counter()
    with redirect_stdout(captured2):
        assessment = generate_recruitment_assessment(
            profile=profile,
            job_profile=job_profile,
            rule_result=rule_result,
            gap_result=gap_result,
            rag_context=rag_context,
            candidate_legal_evidence=candidate_legal_evidence,
            num_predict=num_predict,
        )
    stages["fused_reasoning_latency"] = perf_counter() - t0

    fused_log = captured2.getvalue()
    sys.stdout.write(fused_log)
    stages.update(_parse_llm_log(fused_log, "fused"))

    stages["decision"] = assessment.get("decision", "")
    stages["confidence"] = assessment.get("confidence")
    stages["overall_score"] = assessment.get("overall_score")

    dim_scores = assessment.get("dimension_scores", {}) or {}
    stages["dimension_scores_complete"] = all(
        k in dim_scores for k in DEFAULT_DIMENSION_SCORES
    )
    stages["strengths_count"] = len(assessment.get("strengths", []) or [])
    stages["weaknesses_count"] = len(assessment.get("weaknesses", []) or [])
    stages["reasoning_count"] = len(assessment.get("reasoning", []) or [])
    stages["risks_count"] = len(assessment.get("risks", []) or [])
    stages["recommendation_present"] = bool(assessment.get("recommendation"))

    recommendation_text = str(assessment.get("recommendation", ""))
    stages["fused_reasoning_failed"] = (
        stages["decision"] == ""
        or recommendation_text.startswith("Reasoning unavailable")
    )

    stages["total_runtime"] = (
        stages["cv_parsing_latency"] + stages["fused_reasoning_latency"]
    )

    if stages["fused_reasoning_failed"]:
        stages["status"] = "FAIL (fused reasoning empty/invalid JSON)"
    elif not stages["dimension_scores_complete"]:
        stages["status"] = "FAIL (incomplete dimension_scores)"
    elif stages.get("fused_llm_error_count", 0) > 0:
        stages["status"] = "FAIL (LLM Error logged during fused reasoning)"
    elif stages.get("cv_parsing_llm_error_count", 0) > 0:
        stages["status"] = "FAIL (LLM Error logged during CV parsing)"
    else:
        stages["status"] = "OK"

    return stages


def fmt(x, suffix="s"):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.2f}{suffix}"
    return f"{x}{suffix}"


def print_run(stages):
    print(
        f"[{stages['config']:>8}] app={stages['application_id']} "
        f"run={stages['run']} status={stages['status']} "
        f"cv={fmt(stages.get('cv_parsing_latency'))} "
        f"fused={fmt(stages.get('fused_reasoning_latency'))} "
        f"total={fmt(stages.get('total_runtime'))} "
        f"cv_eval_count={stages.get('cv_parsing_eval_count')} "
        f"fused_eval_count={stages.get('fused_eval_count')} "
        f"decision={stages.get('decision')!r}"
    )


def print_final_table(all_results):
    print(f"\n{'=' * 100}")
    print("PHASE 23 -- FINAL COMPARISON TABLE (all runs, all applications, actual measured data)")
    print(f"{'=' * 100}\n")

    header = (
        f"{'Config':>8} {'Total(s)':>9} {'CV(s)':>7} {'Fused(s)':>9} "
        f"{'CV tok':>7} {'Fused tok':>9} {'JSON':>6} {'Complete':>9} {'FAIL#':>6} {'n':>4}"
    )
    print(header)
    print("-" * len(header))

    for config_name, _ in CONFIGS:
        rows = [r for r in all_results if r["config"] == config_name]
        ok_rows = [r for r in rows if r["status"] == "OK"]
        fail_count = len(rows) - len(ok_rows)

        def _mean(key, source=ok_rows):
            vals = [r[key] for r in source if r.get(key) is not None]
            return statistics.mean(vals) if vals else None

        total_mean = _mean("total_runtime")
        cv_mean = _mean("cv_parsing_latency")
        fused_mean = _mean("fused_reasoning_latency")
        cv_tok_mean = _mean("cv_parsing_eval_count")
        fused_tok_mean = _mean("fused_eval_count")
        json_ok_rate = (
            f"{len(ok_rows)}/{len(rows)}" if rows else "n/a"
        )
        complete_rate = (
            f"{sum(1 for r in ok_rows if r.get('dimension_scores_complete'))}/{len(ok_rows)}"
            if ok_rows else "n/a"
        )

        print(
            f"{config_name:>8} {fmt(total_mean,''):>9} {fmt(cv_mean,''):>7} "
            f"{fmt(fused_mean,''):>9} {fmt(cv_tok_mean,''):>7} "
            f"{fmt(fused_tok_mean,''):>9} {json_ok_rate:>6} {complete_rate:>9} "
            f"{fail_count:>6} {len(rows):>4}"
        )

    print(
        "\nJSON column = runs that completed without CV-parsing technical "
        "failure or fused-reasoning empty/invalid JSON (out of all runs for "
        "that config). Complete column = of those OK runs, how many had all "
        "6 dimension_scores present. FAIL# = runs marked FAIL for ANY reason "
        "(truncation, missing fields, LLM Error logged), regardless of speed."
    )

    print("\nPer-config decisions observed (for correctness/regression comparison):")
    for config_name, _ in CONFIGS:
        rows = [r for r in all_results if r["config"] == config_name and r["status"] == "OK"]
        decisions = [r.get("decision") for r in rows]
        print(f"  {config_name:>8}: {decisions}")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 23 controlled num_predict benchmark (read-only)."
    )
    parser.add_argument(
        "--application-ids", type=str, default="49",
        help="Comma-separated Application id(s) to test against, e.g. "
             "'49' or '49,52'. Use the same applications for every "
             "configuration (default: 49, the one used throughout Phase 22)."
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Repeated passes per (config, application) pair (default 3)."
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip the num_predict validation pre-flight calls."
    )
    args = parser.parse_args()

    application_ids = [
        int(x.strip()) for x in args.application_ids.split(",") if x.strip()
    ]

    print("PHASE 23 -- num_predict controlled benchmark. Diagnostic only.")
    print("No database writes. No production code path changed (num_predict")
    print("stays None for every existing production caller). No commit/push.")
    print(f"application_ids={application_ids}  runs={args.runs}  "
          f"configs={[c[0] for c in CONFIGS]}\n")

    check_ollama_reachable()

    if not args.skip_preflight:
        validate_num_predict_values([v for _, v in CONFIGS])

    all_results = []

    for config_name, num_predict in CONFIGS:
        for application_id in application_ids:
            for run_index in range(1, args.runs + 1):
                stages = run_one_config_pass(
                    config_name, num_predict, application_id, run_index
                )
                print_run(stages)
                all_results.append(stages)

    print_final_table(all_results)


if __name__ == "__main__":
    main()