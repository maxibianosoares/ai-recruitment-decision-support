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


# =========================================================
# LOAD BENCHMARK
# =========================================================

BENCHMARK_FILE = PROJECT_ROOT / "benchmark_40.json"


def load_benchmark():

    with open(
        BENCHMARK_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# =========================================================
# RUN BENCHMARK
# =========================================================

def run_benchmark():

    questions = load_benchmark()

    results = []

    total = len(questions)

    print()
    print("=" * 70)
    print("RAG BENCHMARK")
    print("=" * 70)
    print(f"Total questions: {total}")
    print()

    for index, item in enumerate(
        questions,
        start=1
    ):

        question_id = item["id"]
        question = item["question"]
        expected = item["expected_status"]

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

            actual = result.get(
                "coverage_status",
                "unknown"
            )

            evidence_score = result.get(
                "confidence",
                0
            )

            grounded = result.get(
                "grounded",
                False
            )

            coverage = result.get(
                "coverage",
                0
            )

            correct = (
                actual == expected
            )

            print(
                f"ACTUAL: {actual}"
            )

            print(
                f"COVERAGE: {coverage}"
            )

            print(
                f"EVIDENCE SCORE: {evidence_score}"
            )

            print(
                f"GROUNDED: {grounded}"
            )

            print(
                f"RESULT: "
                f"{'PASS' if correct else 'FAIL'}"
            )

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
# METRICS
# =========================================================

def calculate_metrics(results):

    total = len(results)

    correct = sum(
        1
        for r in results
        if r["correct"]
    )

    grounded = sum(
        1
        for r in results
        if r["grounded"]
    )

    coverage_sum = sum(
        r["coverage"]
        for r in results
    )

    average_coverage = (
        coverage_sum / total
        if total
        else 0
    )

    average_evidence_score = (
        sum(
            r["evidence_score"]
            for r in results
        ) / total
        if total
        else 0
    )

    accuracy = (
        correct / total
        if total
        else 0
    )

    grounded_rate = (
        grounded / total
        if total
        else 0
    )

    return {

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
            grounded_rate

    }


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    results = run_benchmark()

    metrics = calculate_metrics(
        results
    )

    print()
    print("=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    print(
        f"Questions           : "
        f"{metrics['total_questions']}"
    )

    print(
        f"Correct             : "
        f"{metrics['correct']}"
    )

    print(
        f"Accuracy            : "
        f"{metrics['accuracy']:.4f}"
    )

    print(
        f"Average Coverage    : "
        f"{metrics['average_coverage']:.4f}"
    )

    print(
        f"Average Evidence    : "
        f"{metrics['average_evidence_score']:.4f}"
    )

    print(
        f"Grounded Rate       : "
        f"{metrics['grounded_rate']:.4f}"
    )

    print("=" * 70)

    output_file = (
        PROJECT_ROOT
        / "rag"
        / "evaluation"
        / "benchmark_40_results.json"
    )

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "metrics": metrics,
                "results": results
            },
            f,
            indent=4,
            ensure_ascii=False
        )

    print()
    print(
        f"Results saved to: "
        f"{output_file}"
    )