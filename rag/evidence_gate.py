class EvidenceGate:

    # Threshold awal.
    # Nanti kita kalibrasi berdasarkan hasil eksperimen.
    SUPPORTED_THRESHOLD = 0.68
    PARTIAL_THRESHOLD = 0.58

    @classmethod
    def evaluate(cls, documents):

        if not documents:
            return {
                "status": "unsupported",
                "score": 0.0,
                "reason": "No evidence retrieved."
            }

        scores = []

        for document in documents:

            score = document.get("score")

            if score is not None:
                scores.append(float(score))

        if not scores:
            return {
                "status": "unsupported",
                "score": 0.0,
                "reason": "Retrieved documents contain no evidence scores."
            }

        # Evidence terkuat
        best_score = max(scores)

        # Classification
        if best_score >= cls.SUPPORTED_THRESHOLD:

            status = "supported"

            reason = (
                "Strong evidence was retrieved from the knowledge base."
            )

        elif best_score >= cls.PARTIAL_THRESHOLD:

            status = "partially_supported"

            reason = (
                "Some relevant evidence was retrieved, "
                "but the evidence may not fully answer the question."
            )

        else:

            status = "unsupported"

            reason = (
                "Retrieved evidence is below the minimum "
                "relevance threshold."
            )

        return {
            "status": status,
            "score": round(best_score, 4),
            "reason": reason
        }