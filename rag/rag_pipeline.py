from rag.retriever import retriever
from rag.context_builder import build_context
from rag.evidence_gate import EvidenceGate

from ai_engine.services.local_llm import generate_json
from rag.groundedness import groundedness_analyzer

from rag.question_decomposer import question_decomposer
from rag.evidence_coverage import evidence_coverage


DEFAULT_RESULT = {
    "answer": "",
    "sources": [],
    "evidence": [],
    "confidence": 0,
    "evidence_status": "unsupported",
    "retrieval_status": "unsupported",
    "coverage_status": "unsupported",
    "coverage": 0,
    "grounded": False,
    "unsupported_claims": []
}


class RAGPipeline:

    def ask(self, query, top_k=5):

        # ==========================================
        # 1. QUESTION DECOMPOSITION
        # ==========================================

        claims = question_decomposer.decompose(
            query
        )

        print("\n===== QUESTION DECOMPOSITION =====")

        for claim in claims:
            print(
                f'{claim["id"]} : {claim["text"]}'
            )

        # ==========================================
        # 2. RETRIEVE
        # ==========================================

        documents = retriever.search(
            query,
            top_k
        )

        # ==========================================
        # 3. EVIDENCE COVERAGE
        # ==========================================

        coverage_result = evidence_coverage.evaluate(
            claims
        )

        coverage_status = coverage_result["status"]
        coverage = coverage_result["coverage"]

        print("\n===== EVIDENCE COVERAGE =====")

        print(
            "Status:",
            coverage_status
        )

        print(
            "Coverage:",
            coverage
        )

        print(
            "Supported claims:",
            coverage_result["supported_claims"]
        )

        print(
            "Total claims:",
            coverage_result["total_claims"]
        )

        for claim in coverage_result["claims"]:

            print(
                f'\nClaim: {claim["claim"]}'
            )

            print(
                f'Supported: {claim["supported"]}'
            )

            print(
                f'Score: {claim["score"]}'
            )

        # ==========================================
        # 4. BUILD RETRIEVAL EVIDENCE
        # ==========================================

        evidence = []

        for document in documents:

            evidence.append({

                "document":
                    document.get("source"),

                "chunk_id":
                    document.get("id"),

                "score":
                    document.get("score", 0),

                "evidence":
                    document.get("text")

            })

        # ==========================================
        # 5. EVIDENCE GATE
        # ==========================================

        evidence_result = EvidenceGate.evaluate(
            documents
        )

        retrieval_status = evidence_result["status"]

        best_score = evidence_result["score"]

        print("\n===== EVIDENCE GATE =====")

        print(
            "Status:",
            retrieval_status
        )

        print(
            "Best Evidence Score:",
            best_score
        )

        print(
            "Reason:",
            evidence_result["reason"]
        )

        # ==========================================
        # 6. FINAL EVIDENCE STATUS
        #
        # CLAIM COVERAGE HAS PRIORITY OVER
        # GLOBAL RETRIEVAL STATUS
        # ==========================================

        if coverage_status == "unsupported":

            final_status = "unsupported"

        elif coverage_status == "partially_supported":

            final_status = "partially_supported"

        else:

            final_status = "supported"

        # ==========================================
        # 7. UNSUPPORTED → ABSTAIN
        # ==========================================

        if final_status == "unsupported":

            return {

                "answer":
                    "I don't have enough evidence.",

                "sources": [],

                "evidence": [],

                "confidence":
                    round(
                        best_score * 100,
                        2
                    ),

                "evidence_status":
                    "unsupported",

                "retrieval_status":
                    retrieval_status,

                "coverage_status":
                    coverage_status,

                "coverage":
                    coverage,

                "grounded":
                    True,

                "unsupported_claims": []

            }

        # ==========================================
        # 8. BUILD CONTEXT
        # ==========================================

        context = build_context(
            documents
        )

        # ==========================================
        # 9. GENERATE INSTRUCTION
        # ==========================================

        if final_status == "supported":

            instruction = """
The evidence fully supports the question.

Answer the question using ONLY information
supported by the retrieved evidence.

Do not introduce external knowledge.

Every factual statement must be grounded
in the retrieved evidence.
"""

        else:

            instruction = """
The question contains multiple claims.

Only some claims are supported by the evidence.

Answer ONLY the supported claims.

For every unsupported part, explicitly say:

"I don't have enough evidence for that part."

Do not guess.
Do not use external knowledge.
Do not infer unsupported facts.

The absence of evidence is not evidence of a fact.
"""

        # ==========================================
        # 10. CLAIM-LEVEL EVIDENCE
        # ==========================================

        claim_information = ""

        for claim in coverage_result["claims"]:

            claim_information += f"""

Claim ID:
{claim["id"]}

Claim:
{claim["claim"]}

Supported:
{claim["supported"]}

Evidence Score:
{claim["score"]}

Evidence:
{claim["evidence"]}

----------------------------------------
"""

        # ==========================================
        # 11. PROMPT
        # ==========================================

        prompt = f"""

You are an expert Recruitment AI Assistant.

{instruction}

========================================
QUESTION
========================================

{query}

========================================
CLAIM-LEVEL EVIDENCE
========================================

{claim_information}

========================================
RETRIEVED KNOWLEDGE BASE
========================================

{context}

========================================
OUTPUT
========================================

Return ONLY valid JSON.

{{
    "answer": "",
    "sources": [],
    "confidence": 0
}}

"""

        # ==========================================
        # 12. LLM
        # ==========================================

        result = generate_json(

            prompt,

            default={

                "answer":
                    "I don't have enough evidence.",

                "sources": [],

                "confidence": 0

            }

        )

        # ==========================================
        # 13. GROUNDEDNESS
        # ==========================================

        groundedness = groundedness_analyzer.analyze(

            query,

            result.get(
                "answer",
                ""
            ),

            evidence

        )

        grounded = groundedness.get(
            "grounded",
            False
        )

        unsupported_claims = groundedness.get(
            "unsupported_claims",
            []
        )

        print("\n===== GROUNDEDNESS =====")

        print(
            "Grounded:",
            grounded
        )

        print(
            "Unsupported Claims:",
            unsupported_claims
        )

        # ==========================================
        # 14. FINAL RESULT
        # ==========================================

        return {

            "answer":
                result.get(
                    "answer",
                    "I don't have enough evidence."
                ),

            "sources":
                result.get(
                    "sources",
                    []
                ),

            "evidence":
                evidence,

            "confidence":
                round(
                    best_score * 100,
                    2
                ),

            "evidence_status":
                final_status,

            "retrieval_status":
                retrieval_status,

            "coverage_status":
                coverage_status,

            "coverage":
                coverage,

            "grounded":
                grounded,

            "unsupported_claims":
                unsupported_claims

        }


rag_pipeline = RAGPipeline()