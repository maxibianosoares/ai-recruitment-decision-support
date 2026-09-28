import json
import sys
from pathlib import Path


# =========================================================
# MAKE PROJECT ROOT IMPORTABLE
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =========================================================
# IMPORT RAG
# =========================================================

from rag.rag_pipeline import rag_pipeline

# =====================================================================
# SOURCE OF TRUTH FIX (2026-09-23) -- this used to load from
# benchmark_40.json, a 7-entry file left over from an earlier phase
# (its questions are identical to the 7-case test_rag_regression.py
# set). The real 40-question matrix
# (direct_evidence/partial_evidence/unsupported/temporal/
# recruitment_specific) lives in rag/evaluation/questions.py
# (BENCHMARK_QUESTIONS) and was never actually wired into this
# script. Fixed to import that directly instead of reading the stale
# JSON file -- questions.py is not modified by this change.
# =====================================================================

from rag.evaluation.questions import BENCHMARK_QUESTIONS


# =========================================================
# OUTPUT FILE
# =========================================================

OUTPUT_FILE = (
    PROJECT_ROOT
    / "rag"
    / "evaluation"
    / "benchmark_40_results.json"
)


# =========================================================
# LOAD BENCHMARK
# =========================================================

def load_benchmark():

    return BENCHMARK_QUESTIONS

# =========================================================
# RUN BENCHMARK
# =========================================================

def run_benchmark():

    questions = load_benchmark()

    results = []

    total = len(questions)

    print()
    print("=" * 70)
    print("RAG BENCHMARK — PHASE 5")
    print("=" * 70)
    print(
        f"Total questions: {total}"
    )
    print()

    for index, item in enumerate(
        questions,
        start=1
    ):

        question_id = item["id"]

        question = item["question"]

        expected = item["expected"]

        print()
        print("-" * 70)

        print(
            f"[{index}/{total}] {question_id}"
        )

        print(
            f"QUESTION: {question}"
        )

        print(
            f"EXPECTED: {expected}"
        )

        print("-" * 70)

        try:

            result = rag_pipeline.ask(
                question
            )

            # -------------------------------------------------
            # ACTUAL STATUS
            # -------------------------------------------------

            actual = result.get(
                "coverage_status",
                "unknown"
            )

            # -------------------------------------------------
            # METRICS
            # -------------------------------------------------

            coverage = result.get(
                "coverage",
                0
            )

            evidence_score = result.get(
                "confidence",
                0
            )

            grounded = result.get(
                "grounded",
                False
            )

            # -------------------------------------------------
            # CORRECT CLASSIFICATION
            # -------------------------------------------------

            correct = (
                actual == expected
            )

            # -------------------------------------------------
            # PRINT RESULT
            # -------------------------------------------------

            print(
                f"ACTUAL: {actual}"
            )

            print(
                f"COVERAGE: {coverage}"
            )

            print(
                f"EVIDENCE SCORE: "
                f"{evidence_score}"
            )

            print(
                f"GROUNDED: {grounded}"
            )

            print(
                f"RESULT: "
                f"{'PASS' if correct else 'FAIL'}"
            )

            # -------------------------------------------------
            # STORE RESULT
            # -------------------------------------------------

            results.append({

                "id":
                    question_id,

                "question":
                    question,

                "expected":
                    expected,

                "actual":
                    actual,

                "coverage":
                    coverage,

                "evidence_score":
                    evidence_score,

                "grounded":
                    grounded,

                "correct":
                    correct

            })

        except Exception as e:

            print(
                f"ERROR: {e}"
            )

            results.append({

                "id":
                    question_id,

                "question":
                    question,

                "expected":
                    expected,

                "actual":
                    "error",

                "coverage":
                    0,

                "evidence_score":
                    0,

                "grounded":
                    False,

                "correct":
                    False,

                "error":
                    str(e)

            })

    return results


# =========================================================
# CALCULATE METRICS
# =========================================================

def calculate_metrics(results):

    total = len(results)

    # =====================================================
    # ACCURACY
    # =====================================================

    correct = sum(
        1
        for r in results
        if r["correct"]
    )

    accuracy = (
        correct / total
        if total
        else 0
    )

    # =====================================================
    # EVIDENCE COVERAGE
    # =====================================================

    coverage_sum = sum(
        r["coverage"]
        for r in results
    )

    average_coverage = (
        coverage_sum / total
        if total
        else 0
    )

    # =====================================================
    # EVIDENCE SCORE
    # =====================================================

    average_evidence_score = (

        sum(
            r["evidence_score"]
            for r in results
        )

        / total

        if total
        else 0
    )

    # =====================================================
    # GROUNDEDNESS
    # =====================================================

    grounded = sum(
        1
        for r in results
        if r["grounded"]
    )

    grounded_rate = (
        grounded / total
        if total
        else 0
    )

    # =====================================================
    # FALSE ACCEPTANCE
    #
    # Expected:
    #     unsupported
    #
    # Actual:
    #     supported / partially_supported
    #
    # Meaning:
    # RAG accepted evidence for a question that should
    # have been rejected.
    # =====================================================

    false_acceptance = sum(

        1

        for r in results

        if (
            r["expected"] == "unsupported"
            and r["actual"] != "unsupported"
        )

    )

    # =====================================================
    # FALSE REJECTION
    #
    # Expected:
    #     supported
    #
    # Actual:
    #     unsupported
    #
    # Meaning:
    # RAG rejected evidence that should have been accepted.
    # =====================================================

    false_rejection = sum(

        1

        for r in results

        if (
            r["expected"] == "supported"
            and r["actual"] == "unsupported"
        )

    )

    # =====================================================
    # METRICS OBJECT
    # =====================================================

    metrics = {

        "total_questions":
            total,

        "correct":
            correct,

        "accuracy":
            accuracy,

        "average_coverage":
            average_coverage,

        "average_evidence_score":
            average_evidence_score,

        "grounded_rate":
            grounded_rate,

        "false_acceptance":
            false_acceptance,

        "false_rejection":
            false_rejection

    }

    return metrics


# =========================================================
# PRINT SUMMARY
# =========================================================

def print_summary(metrics):

    print()
    print("=" * 70)
    print("PHASE 5 — RAG BENCHMARK SUMMARY")
    print("=" * 70)

    print(
        f"Questions            : "
        f"{metrics['total_questions']}"
    )

    print(
        f"Correct              : "
        f"{metrics['correct']}"
    )

    print(
        f"Accuracy             : "
        f"{metrics['accuracy']:.4f}"
    )

    print(
        f"Evidence Coverage    : "
        f"{metrics['average_coverage']:.4f}"
    )

    print(
        f"Evidence Score       : "
        f"{metrics['average_evidence_score']:.2f}"
    )

    print(
        f"Groundedness         : "
        f"{metrics['grounded_rate']:.4f}"
    )

    print(
        f"False Acceptance     : "
        f"{metrics['false_acceptance']}"
    )

    print(
        f"False Rejection      : "
        f"{metrics['false_rejection']}"
    )

    print("=" * 70)


# =========================================================
# SAVE RESULTS
# =========================================================

def save_results(
    metrics,
    results
):

    output = {

        "metrics":
            metrics,

        "results":
            results

    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=4,
            ensure_ascii=False
        )

    print()
    print(
        f"Results saved to:"
    )

    print(
        OUTPUT_FILE
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    results = run_benchmark()

    metrics = calculate_metrics(
        results
    )

    print_summary(
        metrics
    )

    save_results(
        metrics,
        results
    )