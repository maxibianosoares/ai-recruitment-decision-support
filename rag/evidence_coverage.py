from rag.retriever import retriever
from ai_engine.services.local_llm import generate_json


class EvidenceCoverage:

    def __init__(
        self,
        threshold=0.55,
        verification_threshold=0.50
    ):

        self.threshold = threshold
        self.verification_threshold = verification_threshold

    # =========================================================
    # VERIFY WHETHER EVIDENCE ACTUALLY SUPPORTS CLAIM
    # =========================================================

    def verify_claim(
        self,
        claim,
        evidence
    ):

        if not evidence:

            return {
                "supported": False,
                "reason": "No evidence was retrieved."
            }

        prompt = f"""
        You are an evidence verification component
        for a Retrieval-Augmented Generation system.

        Determine whether the evidence is sufficient to answer
        the claim/question.

        IMPORTANT:

        1. Use ONLY the provided evidence.
        2. Do NOT use external knowledge.
        3. Do NOT assume facts that are absent from the evidence.
        4. Semantic equivalence is allowed.
        5. A concise policy term may support a corresponding
        question.

        For example:

        Claim:
        "Can AI rank candidates?"

        Evidence:
        "Candidate Ranking"

        This SHOULD be considered supported because
        "Candidate Ranking" directly identifies candidate
        ranking as an AI-assisted recruitment activity.

        Another example:

        Claim:
        "Can AI replace human recruiters?"

        Evidence:
        "AI shall assist HR officers but shall never replace
        final human decisions."

        This SHOULD be considered supported because the
        evidence directly answers the question negatively.

        However:

        Claim:
        "Can AI determine a candidate's monthly salary?"

        Evidence:
        "Candidate Ranking, Skill Matching, Recruitment Analytics"

        This should NOT be considered supported because
        the evidence does not establish that AI determines
        salary.

        Judge whether the evidence provides enough information
        to answer the claim.

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

        result = generate_json(
            prompt,
            default={
                "supported": False,
                "reason": "Evidence verification failed."
            }
        )

        supported = result.get(
            "supported",
            False
        )

        # Make sure the result is actually boolean
        if not isinstance(supported, bool):

            supported = str(
                supported
            ).lower() == "true"

        return {
            "supported": supported,
            "reason": result.get(
                "reason",
                ""
            )
        }

    # =========================================================
    # EVALUATE CLAIM-LEVEL EVIDENCE COVERAGE
    # =========================================================

    def evaluate(self, claims):

        evaluated_claims = []

        for claim in claims:

            claim_text = claim.get(
                "text",
                ""
            )

            # -------------------------------------------------
            # 1. RETRIEVE EVIDENCE FOR THIS CLAIM
            # -------------------------------------------------

            results = retriever.search(
                claim_text,
                top_k=3
            )

            best_score = 0
            best_document = None
            best_text = None

            if results:

                best = max(
                    results,
                    key=lambda x: x.get(
                        "score",
                        0
                    )
                )

                best_score = best.get(
                    "score",
                    0
                )

                best_document = best.get(
                    "source"
                )

                best_text = best.get(
                    "text"
                )

            # -------------------------------------------------
            # Combine retrieved chunks
            # -------------------------------------------------

            evidence_text = "\n\n".join(
                item.get("text", "")
                for item in results
            )

            # -------------------------------------------------
            # 2. RETRIEVAL THRESHOLD
            # -------------------------------------------------

            if best_score < self.threshold:

                supported = False

                verification_reason = (
                    "Retrieved evidence is below "
                    "the minimum relevance threshold."
                )

            else:

                # ---------------------------------------------
                # 3. CLAIM-LEVEL VERIFICATION
                # ---------------------------------------------

                verification = self.verify_claim(
                    claim_text,
                    evidence_text
                )

                supported = verification.get(
                    "supported",
                    False
                )

                verification_reason = verification.get(
                    "reason",
                    ""
                )

            # -------------------------------------------------
            # 4. STORE CLAIM RESULT
            # -------------------------------------------------

            evaluated_claims.append({

                "id":
                    claim.get("id"),

                "claim":
                    claim_text,

                "supported":
                    supported,

                "score":
                    best_score,

                "document":
                    best_document,

                "evidence":
                    best_text,

                "verification_reason":
                    verification_reason

            })

        # =====================================================
        # 5. CALCULATE COVERAGE
        # =====================================================

        total = len(
            evaluated_claims
        )

        supported_count = sum(
            1
            for item in evaluated_claims
            if item["supported"]
        )

        coverage = (
            supported_count / total
            if total
            else 0
        )

        # =====================================================
        # 6. DETERMINE STATUS
        # =====================================================

        if supported_count == 0:

            status = "unsupported"

        elif supported_count == total:

            status = "supported"

        else:

            status = "partially_supported"

        return {

            "status":
                status,

            "coverage":
                coverage,

            "supported_claims":
                supported_count,

            "total_claims":
                total,

            "claims":
                evaluated_claims

        }


evidence_coverage = EvidenceCoverage()