import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.retriever import retriever
from rag.evidence_coverage import evidence_coverage
from rag.evidence_gate import EvidenceGate
from rag.question_decomposer import question_decomposer
from rag.rag_pipeline import rag_pipeline


def is_decree_3_2026(source_name):
    return "3_2026" in source_name or "3 2026" in source_name


# Exact question text as it appears in rag/evaluation/questions.py,
# taken from the actual 40-question benchmark output already run.
RS02_QUESTION = "What happens if a jury member fails to meet the deadlines required for their jury duties?"
DE10_QUESTION = "What principle governs the selection and recruitment of personnel according to the civil service law?"


def trace_question(qid, query):
    print()
    print("#" * 70)
    print(f"# {qid}")
    print(f"# ORIGINAL QUESTION: {query}")
    print("#" * 70)

    print()
    print("== DETECTED QUESTION TYPE ==")
    print("  N/A -- no question-type classifier exists in this architecture.")
    print("  Decomposition is a single LLM call (rag/question_decomposer.py)")
    print("  with no rule-based type tagging.")

    # ---- 1. Decomposition ----
    claims = question_decomposer.decompose(query)
    print()
    print("== GENERATED CLAIMS ==")
    for c in claims:
        print(f"  {c['id']}: {c['text']}")
    if len(claims) == 1:
        print("  >> NOTE: only 1 claim generated for a question that reads")
        print("     as [supported fact] - but [specific trap detail].")

    # ---- 2. Per-claim retrieval + verification ----
    for c in claims:
        print()
        print(f"---- CLAIM [{c['id']}]: \"{c['text']}\" ----")

        print(f"  Retrieved evidence (top_k=5, for visibility):")
        results5 = retriever.search(c["text"], top_k=5)
        for rank, item in enumerate(results5, start=1):
            source = Path(item["source"]).name
            score = item["score"]
            text = item["text"]
            print(f"    #{rank} score={score:.4f} source={source}")
            print(f"        page: N/A (not tracked in metadata)")
            print(f"        text: {text[:350].strip()}")
            if is_decree_3_2026(source):
                print(f"        >> DECREE-LAW 3/2026 HIT at rank {rank}")

        # Reproduce EvidenceCoverage's actual top_k=3 slice
        top3 = retriever.search(c["text"], top_k=3)
        evidence_text = "\n\n".join(item.get("text", "") for item in top3)
        best = max(top3, key=lambda x: x.get("score", 0)) if top3 else None

        print()
        print(f"  [EvidenceCoverage internals] top_k=3 best score: "
              f"{best['score'] if best else 'N/A'} "
              f"(auto-unsupported threshold: {evidence_coverage.threshold})")

        if best and best["score"] >= evidence_coverage.threshold:
            verification = evidence_coverage.verify_claim(c["text"], evidence_text)
            print(f"  [LLM verify_claim()] supported={verification['supported']}")
            print(f"  [LLM verify_claim()] reason: {verification['reason']}")
        else:
            print(f"  Below threshold -- LLM verify_claim() NOT called, auto-unsupported.")

    # ---- 3. Official EvidenceCoverage.evaluate() ----
    coverage_result = evidence_coverage.evaluate(claims)
    print()
    print("== EvidenceCoverage.evaluate() (OFFICIAL, this determines the gate) ==")
    print(f"  status: {coverage_result['status']}  coverage: {coverage_result['coverage']}")
    for claim in coverage_result["claims"]:
        doc = Path(claim['document']).name if claim['document'] else None
        print(f"  - {claim['claim']!r}")
        print(f"      supported={claim['supported']} score={claim['score']:.4f} doc={doc}")
        print(f"      reason: {claim['verification_reason']}")

    # ---- 4. EvidenceGate (reporting-only, full-query retrieval) ----
    full_query_docs = retriever.search(query, top_k=5)
    gate_result = EvidenceGate.evaluate(full_query_docs)
    print()
    print("== EvidenceGate.evaluate() (reporting-only, NOT the actual gate) ==")
    print(f"  status: {gate_result['status']}  score: {gate_result['score']}  reason: {gate_result['reason']}")

    # ---- 5. Full pipeline run (answer + Groundedness) ----
    print()
    print("== FULL rag_pipeline.ask() RUN (answer generation + Groundedness) ==")
    result = rag_pipeline.ask(query)

    print()
    print("== FINAL CLASSIFICATION ==")
    print(f"  coverage_status   : {result.get('coverage_status')}")
    print(f"  evidence_status   : {result.get('evidence_status')}")
    print(f"  retrieval_status  : {result.get('retrieval_status')}")
    print(f"  confidence        : {result.get('confidence')}")

    print()
    print("== GROUNDEDNESS ==")
    print(f"  grounded          : {result.get('grounded')}")
    print(f"  unsupported_claims: {result.get('unsupported_claims')}")
    print(f"  answer            : {result.get('answer')}")


# ---- RS02: run 3x in a row, identical conditions, to check for
#      non-determinism in verify_claim() ----
for run_number in range(1, 4):
    trace_question(f"RS02 (run {run_number}/3)", RS02_QUESTION)

# ---- DE10: single diagnostic-only run ----
trace_question("DE10", DE10_QUESTION)

print()
print("#" * 70)
print("DONE")
print("#" * 70)