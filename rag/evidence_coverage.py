from rag.retriever import retriever
import os

from rag import claim_guards
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
        return claim_guards.is_current_claim(claim)

    def has_historical_evidence(self, evidence):
        return claim_guards.has_historical_evidence(evidence)

    def temporal_guard(self, claim, evidence):
        return claim_guards.temporal_guard(claim, evidence)

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

        guard = claim_guards.run_guards(claim, evidence)

        if guard["blocked"]:

            return {
                "supported": False,
                "reason": guard["reason"],
                "guard": guard["guard"]
            }

        # =====================================================
        # LLM VERIFICATION
        # =====================================================

        allow_partial = os.environ.get("RAG_PARTIAL_CLAIMS", "0") == "1"

        if allow_partial:
            partial_rule = (
                "PARTIAL RULE: If the claim has several parts (or asks for "
                "several facts) and the evidence answers SOME but not ALL of "
                "them, set supported=false and partial=true, and say which "
                "part is missing. If the evidence answers none of it, set "
                "supported=false and partial=false. Set partial=true only when "
                "part of the answer is really present in the evidence."
            )
            json_format = (
                '{"supported": true, "partial": false, "reason": ""}'
            )
        else:
            partial_rule = ""
            json_format = '{"supported": true, "reason": ""}'

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

        {partial_rule}

        Return ONLY valid JSON:

        {json_format}


        CLAIM:
        {claim}

        EVIDENCE:
        {evidence}
        """

        result = generate_json(
            prompt,
            default={
                "supported": False,
                "reason": "Evidence verification failed.",
                "verification_error": True
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
            ),
            "verification_error": bool(
                result.get("verification_error", False)
            ),
            "partial": (
                allow_partial
                and not supported
                and str(result.get("partial", False)).lower() == "true"
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

            results = claim_guards.retrieve_scoped(
                claim_text,
                retriever.search,
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

                verification_error = False

                partial = False

                guard_name = ""

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

                verification_error = verification.get(
                    "verification_error",
                    False
                )

                partial = verification.get(
                    "partial",
                    False
                )

                guard_name = verification.get(
                    "guard",
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
                    verification_reason,

                "verification_error":
                    verification_error,

                "partial":
                    partial,

                "guard":
                    guard_name

            })

        agg = claim_guards.aggregate_status(
            evaluated_claims
        )

        total = agg["total_claims"]
        supported_count = agg["supported_claims"]
        coverage = agg["coverage"]
        status = agg["status"]

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