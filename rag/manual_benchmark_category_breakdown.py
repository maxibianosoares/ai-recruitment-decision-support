import json
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.evaluation.questions import BENCHMARK_QUESTIONS

RESULTS_FILE = PROJECT_ROOT / "rag" / "evaluation" / "benchmark_40_results.json"

with open(RESULTS_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

results_by_id = {r["id"]: r for r in data["results"]}
category_of = {q["id"]: q["category"] for q in BENCHMARK_QUESTIONS}

by_category = defaultdict(lambda: {"total": 0, "correct": 0, "fails": []})

for qid, category in category_of.items():
    r = results_by_id.get(qid)
    if not r:
        continue
    by_category[category]["total"] += 1
    if r["correct"]:
        by_category[category]["correct"] += 1
    else:
        by_category[category]["fails"].append({
            "id": qid,
            "question": r["question"],
            "expected": r["expected"],
            "actual": r["actual"],
        })

print()
print("=" * 70)
print("CATEGORY BREAKDOWN")
print("=" * 70)

for category, stats in by_category.items():
    total = stats["total"]
    correct = stats["correct"]
    acc = correct / total if total else 0
    print()
    print(f"[{category}] {correct}/{total} correct ({acc:.2%})")
    for fail in stats["fails"]:
        print(f"  FAIL {fail['id']}: expected={fail['expected']} actual={fail['actual']}")
        print(f"    Q: {fail['question']}")

print()
print("=" * 70)
print("OVERALL METRICS")
print("=" * 70)
print(json.dumps(data["metrics"], indent=2))