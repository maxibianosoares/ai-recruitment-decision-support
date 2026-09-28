import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.retriever import retriever
from ai_engine.services.local_llm import generate_json

DE10_QUESTION = "What principle governs the selection and recruitment of personnel according to the civil service law?"

# ---- Reproduce EXACT same retrieval used by EvidenceCoverage.evaluate() ----
# (single claim, top_k=3, since diagnostic showed DE10 decomposes to 1 claim)
results = retriever.search(DE10_QUESTION, top_k=3)
evidence_text = "\n\n".join(item.get("text", "") for item in results)
best = max(results, key=lambda x: x.get("score", 0)) if results else None

print("== RETRIEVAL (identical for both A and B) ==")
for rank, item in enumerate(results, start=1):
    print(f"  #{rank} score={item['score']:.4f} source={Path(item['source']).name}")
print(f"  best_score={best['score'] if best else 'N/A'}")
print()

# =========================================================
# PROMPT A: CURRENT PROMPT (rule 13/14 included) -- copied
# verbatim from rag/evidence_coverage.py verify_claim()
# =========================================================

def prompt_a(claim, evidence):
    return f"""
        You are an evidence verification component
        for a Retrieval-Augmented Generation system.

        Your task is to determine whether the provided evidence
        is sufficient to ANSWER the CLAIM / QUESTION.

        IMPORTANT:

        1. Use ONLY the provided evidence.
        2. Do NOT use external knowledge.
        3. Do NOT assume facts that are absent from the evidence.
        4. Semantic equivalence is allowed.
        5. The evidence does NOT need to agree with the wording
        of the question.
        6. The evidence only needs to provide sufficient information
        to determine the correct answer.

        VERY IMPORTANT:

        7. "supported": true means that the evidence is sufficient
        to answer the question.

        8. It does NOT mean that the answer to the question must be
        "yes".

        9. A question may be supported by evidence that gives a
        NEGATIVE answer.

        Example:

        QUESTION:
        Can AI replace human recruiters?

        EVIDENCE:
        "AI shall assist HR officers but shall never replace
        final human decisions."

        CORRECT:
        supported = true

        REASON:
        The evidence directly establishes that AI must not replace
        final human decisions. Therefore, the question can be
        answered using the evidence.

        Another example:

        QUESTION:
        Can AI determine a candidate's monthly salary?

        EVIDENCE:
        "Candidate Ranking, Skill Matching, Recruitment Analytics"

        CORRECT:
        supported = false

        REASON:
        The evidence does not establish that AI determines salary.

        Another example:

        QUESTION:
        Can AI rank candidates?

        EVIDENCE:
        "Candidate Ranking"

        CORRECT:
        supported = true

        Another example:

        QUESTION:
        Who is the current President of Timor-Leste?

        EVIDENCE:
        "O Presidente da República
        José Ramos-Horta
        Promulgado em 26 / 5 / 11"

        CORRECT:
        supported = false

        REASON:
        The evidence is historical and does not establish the
        current office holder.

        TEMPORAL RULE:

        10. If the question contains:
            - current
            - currently
            - today
            - now
            - latest
            - present
            - existing

        then the evidence must establish CURRENT validity.

        11. Historical documents, old appointments, old office holders,
        or dated statements must NOT support current-fact questions.

        12. Do not infer current status from historical evidence.

        SCOPE MATCHING RULE (VERY IMPORTANT):

        13. Evidence that is only topically or thematically related to
        the claim is NOT sufficient. Being about the same general
        subject area (e.g. "recruitment", "salary", "scoring",
        "leave") is not enough. The evidence must be about the SAME
        specific actor, scheme, population, or category that the
        claim names -- not a different one that merely resembles it.

        14. Before answering supported=true, check whether the
        evidence is actually about the SAME subject the claim names:
            - If the claim names a specific actor ("the AI system"),
              the evidence must say something about that actor
              specifically -- not about a general legal/human process
              that happens to cover similar ground.
            - If the claim asks about a general population ("a civil
              servant", "public servants" in general), evidence about
              a different, narrower scheme (e.g. a specific negotiated
              contract category, a specific job grade, a specific
              eligibility track) does NOT support the general claim
              unless the evidence explicitly says it applies to that
              general population.
            - If the evidence answers a related but different
              question than the one asked, answer supported=false.

        Example (reject -- wrong actor):

        QUESTION:
        What exact score threshold does the AI system use to reject
        a candidate?

        EVIDENCE:
        "In the final classification, a scale of 0 to 100 points is
        adopted. Candidates who obtain a score below 60 points are
        considered not approved."

        CORRECT:
        supported = false

        REASON:
        The evidence describes a general legal classification
        threshold used in the recruitment process, but it does not
        establish that this threshold is specifically used by "the
        AI system." The claim names the AI system specifically, and
        the evidence never mentions AI.

        Example (reject -- wrong population/scheme):

        QUESTION:
        What is the monthly salary of a civil servant in
        Timor-Leste?

        EVIDENCE:
        "All long-term contracts must be remunerated at a monthly
        rate. The initial salary offered during negotiation to
        Timorese citizens must be the minimum value stipulated in
        Tables 1 and 2, combined with task complexity and academic
        qualifications."

        CORRECT:
        supported = false

        REASON:
        The evidence describes a negotiated salary scheme for a
        specific category of long-term contracted hires, not the
        general salary of a regular civil servant. It does not
        establish the monthly salary of civil servants in general.

        Example (accept -- same subject, different wording is fine):

        QUESTION:
        Can AI replace human recruiters?

        EVIDENCE:
        "AI shall assist HR officers but shall never replace final
        human decisions."

        CORRECT:
        supported = true

        REASON:
        The evidence directly discusses AI's role relative to human
        recruiters, which is exactly the subject of the claim.

        Return ONLY valid JSON:

        {{
            "supported": true,
            "reason": ""
        }}


        CLAIM:
        {claim}

        EVIDENCE:
        {evidence}
        """


# =========================================================
# PROMPT B: DIAGNOSTIC PROMPT -- IDENTICAL to A except
# rule 13/14 (the SCOPE MATCHING RULE block, including its
# two worked examples) is removed. Nothing else changed:
# same rules 1-12, same earlier examples, same temporal
# rule, same output format instruction, same claim/evidence
# injection.
# =========================================================

def prompt_b(claim, evidence):
    return f"""
        You are an evidence verification component
        for a Retrieval-Augmented Generation system.

        Your task is to determine whether the provided evidence
        is sufficient to ANSWER the CLAIM / QUESTION.

        IMPORTANT:

        1. Use ONLY the provided evidence.
        2. Do NOT use external knowledge.
        3. Do NOT assume facts that are absent from the evidence.
        4. Semantic equivalence is allowed.
        5. The evidence does NOT need to agree with the wording
        of the question.
        6. The evidence only needs to provide sufficient information
        to determine the correct answer.

        VERY IMPORTANT:

        7. "supported": true means that the evidence is sufficient
        to answer the question.

        8. It does NOT mean that the answer to the question must be
        "yes".

        9. A question may be supported by evidence that gives a
        NEGATIVE answer.

        Example:

        QUESTION:
        Can AI replace human recruiters?

        EVIDENCE:
        "AI shall assist HR officers but shall never replace
        final human decisions."

        CORRECT:
        supported = true

        REASON:
        The evidence directly establishes that AI must not replace
        final human decisions. Therefore, the question can be
        answered using the evidence.

        Another example:

        QUESTION:
        Can AI determine a candidate's monthly salary?

        EVIDENCE:
        "Candidate Ranking, Skill Matching, Recruitment Analytics"

        CORRECT:
        supported = false

        REASON:
        The evidence does not establish that AI determines salary.

        Another example:

        QUESTION:
        Can AI rank candidates?

        EVIDENCE:
        "Candidate Ranking"

        CORRECT:
        supported = true

        Another example:

        QUESTION:
        Who is the current President of Timor-Leste?

        EVIDENCE:
        "O Presidente da República
        José Ramos-Horta
        Promulgado em 26 / 5 / 11"

        CORRECT:
        supported = false

        REASON:
        The evidence is historical and does not establish the
        current office holder.

        TEMPORAL RULE:

        10. If the question contains:
            - current
            - currently
            - today
            - now
            - latest
            - present
            - existing

        then the evidence must establish CURRENT validity.

        11. Historical documents, old appointments, old office holders,
        or dated statements must NOT support current-fact questions.

        12. Do not infer current status from historical evidence.

        Return ONLY valid JSON:

        {{
            "supported": true,
            "reason": ""
        }}


        CLAIM:
        {claim}

        EVIDENCE:
        {evidence}
        """


def run_verify(label, prompt_fn, claim, evidence, n_runs=3):
    print(f"== {label} ==")
    outcomes = []
    for i in range(1, n_runs + 1):
        prompt = prompt_fn(claim, evidence)
        result = generate_json(
            prompt,
            default={"supported": False, "reason": "Evidence verification failed."}
        )
        supported = result.get("supported", False)
        if not isinstance(supported, bool):
            supported = str(supported).lower() == "true"
        reason = result.get("reason", "")
        outcomes.append(supported)
        print(f"  run {i}: supported={supported}")
        print(f"    reason: {reason}")
    print(f"  -> {label} outcomes: {outcomes}")
    print()
    return outcomes


if best and best["score"] >= 0.55:
    a_outcomes = run_verify("A (current prompt, rule 13/14 INCLUDED)", prompt_a, DE10_QUESTION, evidence_text, n_runs=3)
    b_outcomes = run_verify("B (diagnostic prompt, rule 13/14 REMOVED)", prompt_b, DE10_QUESTION, evidence_text, n_runs=3)

    print("== SUMMARY ==")
    print(f"  A (with rule 13/14):    {a_outcomes}")
    print(f"  B (without rule 13/14): {b_outcomes}")
else:
    print("Below threshold -- cannot run verify_claim comparison.")
