"""Diagnose one question: python -m rag.manual_diagnose_claim "question text"
Shows the retrieved chunks, which guard (if any) blocks, and the LLM verdict + reason."""
import sys

from rag import claim_guards
from rag.evidence_coverage import EvidenceCoverage
from rag.retriever import retriever


def main(question):
    results = claim_guards.retrieve_scoped(question, retriever.search, top_k=3)
    print("=== RETRIEVED (scoped top 3) ===")
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r.get('score', 0):.4f} source={r.get('source')}")
        print((r.get("text") or "")[:600].replace("\n", " "))
        print()
    evidence = "\n\n".join(r.get("text", "") for r in results)
    print("=== GUARDS ===")
    print(claim_guards.run_guards(question, evidence))
    print("=== LLM VERDICT ===")
    print(EvidenceCoverage().verify_claim(question, evidence))


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))
