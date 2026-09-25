"""
Usage:

    python manage.py benchmark_candidate_rag --dataset path/to/dataset.jsonl
    python manage.py benchmark_candidate_rag --dataset path/to/dataset.jsonl --limit 10

Phase 21 (research) -- generic OLD_RAG vs NEW_CANDIDATE_RAG comparison
harness for candidate_legal_rag.py. Built because no "80-example"
candidate dataset was found anywhere in this repository (jsonl/csv,
seed_demo_data.py [12 seeded candidates, a different fixture], docs) --
per instruction, no dataset is invented here. This command accepts
ANY dataset the user points it at, in the format below, whenever one
is ready. Nothing about this command creates or balances data.

DOES NOT MODIFY ANY PRODUCTION CODE. It composes the same functions
recruitment_pipeline.py already calls (analyze_cv, evaluate_recruitment_rules,
skill_gap_analysis, get_candidate_legal_evidence, generate_recruitment_assessment,
compute_final_score) directly, OUTSIDE the Django ORM/Application model, so:
  - it never writes to the database (no seed data required, no cleanup needed)
  - it never depends on NEW_CANDIDATE_RAG's value in the environment --
    it always runs BOTH conditions for every record and reports both,
    regardless of what model_config.NEW_CANDIDATE_RAG is set to.
  - analyze_cv() and the deterministic rule/gap steps run ONCE per
    candidate and are reused for both conditions (no duplicate work,
    per instruction #13); only generate_recruitment_assessment() runs
    twice (once per condition), since its output is exactly what
    differs between OLD_RAG and NEW_CANDIDATE_RAG.

Dataset format (JSONL, one record per line):
    {
        "cv_text": "...",                       (required)
        "job_profile": {                        (required -- see
            "job_title": "...",                  llm_job_parser.py's
            "education": "...",                  DEFAULT_JOB_PROFILE
            "years_experience": 0,               shape)
            "languages": [],
            "certifications": [],
            "skills": []
        },
        "job_rag_context": { ... },              (optional -- job.ai_rag_context
                                                   shape; if omitted, the
                                                   job-level RAG_POLICY_SCORE_
                                                   PLACEHOLDER is used, same
                                                   fallback the real pipeline
                                                   uses when job RAG failed)
        "expected_decision": "Recommended"        (optional -- if present,
                                                    accuracy is computed for
                                                    both conditions; if
                                                    absent, only score/
                                                    decision deltas and
                                                    evidence-availability
                                                    stats are reported --
                                                    this script never invents
                                                    a ground-truth label)
    }

Reports, per condition (OLD_RAG / NEW_CANDIDATE_RAG), NOT averaged
into a single number the way instruction #21/#26 asks for:
    - accuracy (only if expected_decision present in the dataset)
    - mean/P50/P95 latency (candidate legal RAG step + fused reasoning
      call, separately, plus total)
    - retrieval calls / verification calls per candidate (NEW only)
    - cache hit rate (NEW only, across the whole run -- run twice in
      the same process to see warm-cache latency)
    - dimensions with evidence_found / evidence_not_found /
      evidence_insufficient / not_applicable, aggregated
    - decision-changed count (NEW vs OLD disagreement rate) -- this is
      the key "does candidate-specific evidence change anything"
      signal even without ground-truth labels
"""

import json
import statistics
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError

from ai_engine.services.llm_candidate_profile import analyze_cv
from ai_engine.services.recruitment_rules import evaluate_recruitment_rules
from ai_engine.services.skill_gap_analysis import skill_gap_analysis
from ai_engine.services.candidate_legal_rag import get_candidate_legal_evidence
from ai_engine.services.llm_reasoning import (
    generate_recruitment_assessment,
    split_assessment,
)
from ai_engine.services.recruitment_pipeline import (
    compute_final_score,
    normalize_decision,
    RAG_POLICY_SCORE_PLACEHOLDER,
)


def _load_dataset(path, limit=None):

    records = []

    with open(path, "r", encoding="utf-8") as f:

        for line_number, line in enumerate(f, start=1):

            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise CommandError(
                    f"Invalid JSON on line {line_number} of {path}: {e}"
                )

            if "cv_text" not in record or "job_profile" not in record:
                raise CommandError(
                    f"Line {line_number} of {path} is missing required "
                    f"'cv_text' or 'job_profile' field."
                )

            records.append(record)

            if limit and len(records) >= limit:
                break

    return records


def _percentile(values, pct):

    if not values:
        return 0.0

    ordered = sorted(values)

    index = min(
        len(ordered) - 1,
        int(round((pct / 100) * (len(ordered) - 1)))
    )

    return ordered[index]


class Command(BaseCommand):

    help = (
        "Phase 21 -- compare OLD_RAG vs NEW_CANDIDATE_RAG on a "
        "user-supplied JSONL dataset. Creates no DB rows, invents no "
        "data. See this file's module docstring for the dataset format."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--dataset", required=True,
            help="Path to a JSONL dataset file (see module docstring for format)."
        )

        parser.add_argument(
            "--limit", type=int, default=None,
            help="Only process the first N records (for a quick smoke test)."
        )

        parser.add_argument(
            "--warm-cache-pass", action="store_true",
            help=(
                "After the first pass, run candidate-specific RAG again "
                "on the same records to measure warm-cache latency and "
                "cache hit rate (Django's default cache backend, "
                "in-process for the local dev/manage.py runserver case)."
            )
        )

    def handle(self, *args, **options):

        records = _load_dataset(options["dataset"], options.get("limit"))

        if not records:
            raise CommandError("Dataset is empty.")

        self.stdout.write(f"Loaded {len(records)} record(s) from {options['dataset']}")

        old_results = []
        new_results = []

        decision_changed = 0

        old_correct = 0
        new_correct = 0
        has_ground_truth = 0

        dimension_status_counts = {}

        for i, record in enumerate(records, start=1):

            cv_text = record["cv_text"]
            job_profile = record["job_profile"]
            job_rag_context = record.get("job_rag_context") or {}
            expected_decision = record.get("expected_decision")

            self.stdout.write(f"\n[{i}/{len(records)}] processing...")

            # Shared, deterministic-or-single-LLM-call steps -- run
            # ONCE, reused by both conditions (instruction #13: no
            # duplicate work).
            t0 = perf_counter()
            profile = analyze_cv(cv_text)
            profile_latency = perf_counter() - t0

            rule_result = evaluate_recruitment_rules(profile, job_profile)
            gap_result = skill_gap_analysis(
                profile.get("skills", []), job_profile.get("skills", [])
            )

            rule_eligible = rule_result.get("eligible", False)
            skill_match_score = gap_result.get("match_score", 0)

            if job_rag_context.get("error") or not job_rag_context.get("evidence"):
                job_rag_score = RAG_POLICY_SCORE_PLACEHOLDER
            else:
                job_rag_score = job_rag_context.get("best_evidence_score", 0) * 100

            # =========================================
            # CONDITION: OLD_RAG (candidate_legal_evidence={})
            # =========================================

            t0 = perf_counter()
            old_assessment = generate_recruitment_assessment(
                profile=profile, job_profile=job_profile,
                rule_result=rule_result, gap_result=gap_result,
                rag_context=job_rag_context, candidate_legal_evidence={}
            )
            old_reasoning_latency = perf_counter() - t0

            old_semantic, old_report = split_assessment(old_assessment)

            old_score = compute_final_score(
                rule_eligible=rule_eligible,
                skill_match_score=skill_match_score,
                semantic_score=old_semantic["overall_score"],
                rag_score=job_rag_score,
            )
            old_decision = normalize_decision(old_report.get("decision", ""))

            old_results.append({
                "score": old_score, "decision": old_decision,
                "profile_latency": profile_latency,
                "reasoning_latency": old_reasoning_latency,
                "total_latency": profile_latency + old_reasoning_latency,
            })

            # =========================================
            # CONDITION: NEW_CANDIDATE_RAG
            # =========================================

            t0 = perf_counter()
            candidate_legal_evidence, rag_stats = get_candidate_legal_evidence(
                profile=profile, job_profile=job_profile, rule_result=rule_result
            )
            candidate_rag_latency = perf_counter() - t0

            for dim, res in candidate_legal_evidence.items():
                dimension_status_counts.setdefault(dim, {}).setdefault(
                    res["status"], 0
                )
                dimension_status_counts[dim][res["status"]] += 1

            t0 = perf_counter()
            new_assessment = generate_recruitment_assessment(
                profile=profile, job_profile=job_profile,
                rule_result=rule_result, gap_result=gap_result,
                rag_context=job_rag_context,
                candidate_legal_evidence=candidate_legal_evidence,
            )
            new_reasoning_latency = perf_counter() - t0

            new_semantic, new_report = split_assessment(new_assessment)

            new_score = compute_final_score(
                rule_eligible=rule_eligible,
                skill_match_score=skill_match_score,
                semantic_score=new_semantic["overall_score"],
                rag_score=job_rag_score,
            )
            new_decision = normalize_decision(new_report.get("decision", ""))

            new_results.append({
                "score": new_score, "decision": new_decision,
                "profile_latency": profile_latency,
                "candidate_rag_latency": candidate_rag_latency,
                "reasoning_latency": new_reasoning_latency,
                "total_latency": (
                    profile_latency + candidate_rag_latency + new_reasoning_latency
                ),
                "rag_stats": rag_stats,
            })

            if old_decision != new_decision:
                decision_changed += 1

            if expected_decision:
                has_ground_truth += 1
                if old_decision == expected_decision:
                    old_correct += 1
                if new_decision == expected_decision:
                    new_correct += 1

            self.stdout.write(
                f"  OLD: {old_decision} (score={old_score})  "
                f"NEW: {new_decision} (score={new_score})  "
                f"candidate_rag_latency={candidate_rag_latency:.2f}s"
            )

        # =========================================
        # SUMMARY
        # =========================================

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("CANDIDATE-LEVEL BENCHMARK -- OLD_RAG vs NEW_CANDIDATE_RAG")
        self.stdout.write("=" * 70)

        self.stdout.write(f"\nRecords processed: {len(records)}")
        self.stdout.write(f"Decision changed (NEW vs OLD): {decision_changed}/{len(records)}")

        if has_ground_truth:
            self.stdout.write(
                f"\nAccuracy (n={has_ground_truth} with expected_decision):"
            )
            self.stdout.write(f"  OLD_RAG:          {old_correct}/{has_ground_truth} "
                               f"({100*old_correct/has_ground_truth:.1f}%)")
            self.stdout.write(f"  NEW_CANDIDATE_RAG: {new_correct}/{has_ground_truth} "
                               f"({100*new_correct/has_ground_truth:.1f}%)")
        else:
            self.stdout.write(
                "\nNo 'expected_decision' in dataset -- accuracy not computed "
                "(this script does not invent ground truth)."
            )

        for label, results, key in [
            ("OLD_RAG total latency", old_results, "total_latency"),
            ("NEW_CANDIDATE_RAG total latency", new_results, "total_latency"),
            ("NEW_CANDIDATE_RAG candidate-RAG-only latency", new_results, "candidate_rag_latency"),
        ]:
            values = [r[key] for r in results]
            self.stdout.write(
                f"\n{label}: mean={statistics.mean(values):.2f}s  "
                f"P50={_percentile(values, 50):.2f}s  "
                f"P95={_percentile(values, 95):.2f}s"
            )

        total_retrieval = sum(r["rag_stats"]["retrieval_count"] for r in new_results)
        total_cache_hit = sum(r["rag_stats"]["cache_hit"] for r in new_results)
        total_cache_miss = sum(r["rag_stats"]["cache_miss"] for r in new_results)
        total_cache_lookups = total_cache_hit + total_cache_miss

        self.stdout.write(f"\nRetrieval calls: {total_retrieval} total "
                           f"({total_retrieval/len(records):.2f}/candidate)")
        if total_cache_lookups:
            self.stdout.write(
                f"Cache hit rate (this pass): "
                f"{100*total_cache_hit/total_cache_lookups:.1f}% "
                f"({total_cache_hit}/{total_cache_lookups})"
            )

        self.stdout.write("\nEvidence status distribution by dimension:")
        for dim, counts in dimension_status_counts.items():
            self.stdout.write(f"  {dim}: {counts}")

        if options.get("warm_cache_pass"):

            self.stdout.write("\n" + "=" * 70)
            self.stdout.write("WARM-CACHE PASS (re-running candidate RAG on same records)")
            self.stdout.write("=" * 70)

            warm_latencies = []
            warm_cache_hit = 0
            warm_cache_miss = 0

            for record in records:

                profile = analyze_cv(record["cv_text"])
                rule_result = evaluate_recruitment_rules(profile, record["job_profile"])

                t0 = perf_counter()
                _, rag_stats = get_candidate_legal_evidence(
                    profile=profile, job_profile=record["job_profile"],
                    rule_result=rule_result
                )
                warm_latencies.append(perf_counter() - t0)
                warm_cache_hit += rag_stats["cache_hit"]
                warm_cache_miss += rag_stats["cache_miss"]

            warm_lookups = warm_cache_hit + warm_cache_miss

            self.stdout.write(
                f"Warm-cache candidate-RAG latency: "
                f"mean={statistics.mean(warm_latencies):.2f}s  "
                f"P50={_percentile(warm_latencies, 50):.2f}s  "
                f"P95={_percentile(warm_latencies, 95):.2f}s"
            )

            if warm_lookups:
                self.stdout.write(
                    f"Warm-cache hit rate: "
                    f"{100*warm_cache_hit/warm_lookups:.1f}% "
                    f"({warm_cache_hit}/{warm_lookups})"
                )

        self.stdout.write("\nDone.")