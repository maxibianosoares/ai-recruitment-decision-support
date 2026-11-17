"""
Compare two benchmark result files (e.g. before / after adding the HNGV corpus).

    python -m rag.evaluation.compare_runs rag/evaluation/<before>.json rag/evaluation/<after>.json

Prints, per question id: expected, actual-before, actual-after, and whether it changed,
then accuracy per file and the ids that flipped. Reads only the two JSON files.
"""
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r for r in json.load(f)["results"]}


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    a, b = load(argv[0]), load(argv[1])
    ids = [i for i in a if i in b]
    print(f"{'id':6} {'expected':20} {'before':20} {'after':20} change")
    flips = []
    for i in ids:
        x, y = a[i], b[i]
        ch = ""
        if x["actual"] != y["actual"]:
            ch = "FIXED" if (y["correct"] and not x["correct"]) else ("BROKE" if (x["correct"] and not y["correct"]) else "changed")
            flips.append((i, ch))
        print(f"{i:6} {x['expected']:20} {x['actual']:20} {y['actual']:20} {ch}")
    for name, d in (("before", a), ("after", b)):
        ok = sum(d[i]["correct"] for i in ids)
        print(f"{name}: {ok}/{len(ids)} correct")
    print("flips:", flips or "none")


if __name__ == "__main__":
    main(sys.argv[1:])
