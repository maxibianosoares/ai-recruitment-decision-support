from rag.retriever import retriever


class EvidenceCoverage:

    def __init__(self, threshold=0.55):

        self.threshold = threshold

    def evaluate(self, claims):

        evaluated_claims = []

        for claim in claims:

            results = retriever.search(
                claim["text"],
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

            supported = (
                best_score >= self.threshold
            )

            evaluated_claims.append({

                "id":
                    claim["id"],

                "claim":
                    claim["text"],

                "supported":
                    supported,

                "score":
                    best_score,

                "document":
                    best_document,

                "evidence":
                    best_text

            })

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
                round(
                    coverage,
                    4
                ),

            "supported_claims":
                supported_count,

            "total_claims":
                total,

            "claims":
                evaluated_claims

        }


evidence_coverage = EvidenceCoverage()