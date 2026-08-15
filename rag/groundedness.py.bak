from ai_engine.services.local_llm import generate_json


class GroundednessAnalyzer:

    ABSTENTION_MARKERS = [
        "I don't have enough evidence.",
        "I don't have enough evidence for that part.",
        "I do not have enough evidence.",
        "I do not have enough evidence for that part.",
        "There is not enough evidence.",
        "There is insufficient evidence.",
        "Insufficient evidence.",
        "Not enough evidence.",
        "Cannot be determined from the evidence.",
        "Cannot be determined from the available evidence."
    ]

    def __init__(self):

        pass

    # ======================================================
    # CHECK ABSTENTION
    # ======================================================

    def is_abstention(self, text):

        if not text:
            return False

        normalized = text.strip().lower()

        for marker in self.ABSTENTION_MARKERS:

            if marker.lower() in normalized:

                return True

        return False

    # ======================================================
    # ANALYZE
    # ======================================================

    def analyze(
        self,
        query,
        answer,
        evidence
    ):

        # --------------------------------------------------
        # Empty answer
        # --------------------------------------------------

        if not answer:

            return {

                "grounded": False,

                "status": "unsupported",

                "unsupported_claims": [],

                "supported_claims": [],

                "abstention": True

            }

        # --------------------------------------------------
        # No evidence
        # --------------------------------------------------

        if not evidence:

            return {

                "grounded": False,

                "status": "unsupported",

                "unsupported_claims": [],

                "supported_claims": [],

                "abstention": True

            }

        # --------------------------------------------------
        # Ask LLM to identify factual claims
        # --------------------------------------------------

        prompt = f"""

You are a groundedness evaluator for a
Retrieval-Augmented Generation system.

Your task is to determine whether the factual claims
in the ANSWER are supported by the EVIDENCE.

IMPORTANT:

Statements such as:

"I don't have enough evidence."

"I don't have enough evidence for that part."

"I do not have enough evidence."

"I do not have enough evidence for that part."

are NOT factual claims.

They are abstention statements.

Do NOT classify abstention statements as unsupported claims.

Only evaluate factual claims.

========================================
QUESTION
========================================

{query}

========================================
ANSWER
========================================

{answer}

========================================
EVIDENCE
========================================

{evidence}

========================================
OUTPUT
========================================

Return ONLY valid JSON.

{{
    "claims": [
        {{
            "claim": "",
            "supported": true
        }}
    ]
}}

"""

        result = generate_json(

            prompt,

            default={
                "claims": []
            }

        )

        claims = result.get(
            "claims",
            []
        )

        supported_claims = []

        unsupported_claims = []

        # ==================================================
        # CLASSIFY CLAIMS
        # ==================================================

        for item in claims:

            claim = item.get(
                "claim",
                ""
            ).strip()

            if not claim:

                continue

            # ----------------------------------------------
            # Ignore abstention statements
            # ----------------------------------------------

            if self.is_abstention(claim):

                continue

            supported = item.get(
                "supported",
                False
            )

            if supported:

                supported_claims.append(
                    claim
                )

            else:

                unsupported_claims.append(
                    claim
                )

        # ==================================================
        # DETERMINE GROUNDEDNESS
        # ==================================================

        factual_claim_count = (
            len(supported_claims)
            +
            len(unsupported_claims)
        )

        # --------------------------------------------------
        # Answer contains only abstention
        # --------------------------------------------------

        if factual_claim_count == 0:

            return {

                "grounded": True,

                "status": "abstained",

                "unsupported_claims": [],

                "supported_claims": [],

                "abstention": True

            }

        # --------------------------------------------------
        # All factual claims supported
        # --------------------------------------------------

        if not unsupported_claims:

            return {

                "grounded": True,

                "status": "grounded",

                "unsupported_claims": [],

                "supported_claims":
                    supported_claims,

                "abstention":
                    self.is_abstention(answer)

            }

        # --------------------------------------------------
        # Some factual claims unsupported
        # --------------------------------------------------

        if supported_claims:

            return {

                "grounded": False,

                "status":
                    "partially_grounded",

                "unsupported_claims":
                    unsupported_claims,

                "supported_claims":
                    supported_claims,

                "abstention":
                    self.is_abstention(answer)

            }

        # --------------------------------------------------
        # No factual claims are supported
        # --------------------------------------------------

        return {

            "grounded": False,

            "status":
                "ungrounded",

            "unsupported_claims":
                unsupported_claims,

            "supported_claims": [],

            "abstention":
                self.is_abstention(answer)

        }


groundedness_analyzer = GroundednessAnalyzer()