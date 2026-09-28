import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.rag_pipeline import rag_pipeline

PROBES = [
    ("STRONG EVIDENCE", "What is the role of the Civil Service Commission?"),
    ("WEAK/PARTIAL EVIDENCE", "What academic qualifications are required for civil service positions?"),
    ("NO EVIDENCE (flagged in retrieval benchmark)", "What is the minimum wage for private sector workers in Timor-Leste?"),
]

for label, question in PROBES:
    print()
    print("=" * 70)
    print(f"[{label}]")
    print(f"QUESTION: {question}")
    print("-" * 70)

    result = rag_pipeline.ask(question)

    print(f"coverage_status : {result.get('coverage_status')}")
    print(f"evidence_status : {result.get('evidence_status')}")
    print(f"confidence      : {result.get('confidence')}")
    print(f"grounded        : {result.get('grounded')}")
    print("claims:")
    for c in result.get("claims", []):
        print(f"  - supported={c.get('supported')} score={c.get('score')} doc={c.get('document')}")
        print(f"    reason: {c.get('reason')}")

print()
print("=" * 70)
print("DONE")
print("=" * 70)