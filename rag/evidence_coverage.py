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
    # TEMPORAL CLAIM DETECTION
    # =========================================================

    CURRENT_TERMS = [
        "current",
        "currently",
        "today",
        "now",
        "latest",
        "present",
        "currently holds",
        "current president",
        "current prime minister",
        "current minister",
        "current director",
        "current office holder",
        "serving"
    ]

    HISTORICAL_MARKERS = [
        "promulgated",
        "promulgada",
        "promulgado",
        "published",
        "publique-se",
        "jornal da república",
        "decreto-lei",
        "lei no.",
        "lei n.º",
        "law no.",
        "in 2008",
        "in 2009",
        "in 2010",
        "in 2011",
        "in 2012",
        "in 2013",
        "in 2014",
        "in 2015",
        "in 2016",
        "in 2017",
        "in 2018",
        "in 2019",
        "in 2020",
        "in 2021",
        "in 2022",
        "in 2023",
        "in 2024",
        "in 2025"
    ]

    def is_current_claim(self, claim):

        text = claim.lower()

        return any(
            term in text
            for term in self.CURRENT_TERMS
        )

    def has_historical_evidence(self, evidence):

        text = evidence.lower()

        return any(
            marker in text
            for marker in self.HISTORICAL_MARKERS
        )

    def temporal_guard(self, claim, evidence):

        current_claim = self.is_current_claim(
            claim
        )

        historical_evidence = self.has_historical_evidence(
            evidence
        )

        # -----------------------------------------------------
        # Current claim + clearly historical evidence
        # -----------------------------------------------------

        if current_claim and historical_evidence:

            return {
                "blocked": True,
                "reason": (
                    "The claim asks for a current or present fact, "
                    "but the retrieved evidence contains historical "
                    "or dated information and does not establish "
                    "current validity."
                )
            }

        return {
            "blocked": False,
            "reason": ""
        }

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

        # =====================================================
        # TEMPORAL GUARD
        # =====================================================

        temporal_check = self.temporal_guard(
            claim,
            evidence
        )

        if temporal_check["blocked"]:

            return {
                "supported": False,
                "reason": temporal_check["reason"]
            }

        # =====================================================
        # LLM VERIFICATION
        # =====================================================

        prompt = f"""
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

        if not isinstance(
            supported,
            bool
        ):

            supported = (
                str(supported).lower()
                == "true"
            )

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
            # RETRIEVE
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
            # COMBINE EVIDENCE
            # -------------------------------------------------

            evidence_text = "\n\n".join(
                item.get(
                    "text",
                    ""
                )
                for item in results
            )

            # -------------------------------------------------
            # RETRIEVAL THRESHOLD
            # -------------------------------------------------

            if best_score < self.threshold:

                supported = False

                verification_reason = (
                    "Retrieved evidence is below "
                    "the minimum relevance threshold."
                )

            else:

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
            # STORE RESULT
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
        # COVERAGE
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
        # STATUS
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