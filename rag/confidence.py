def distance_to_relevance(distance):
    """
    Convert FAISS L2 distance into
    a normalized relevance score.

    Smaller distance = higher relevance.
    """

    if distance is None:
        return 0.0

    distance = float(distance)

    return 1.0 / (1.0 + distance)


def calculate_retrieval_confidence(
    documents
):
    """
    Calculate confidence based on
    retrieved evidence.
    """

    if not documents:
        return 0.0


    relevance_scores = []


    for document in documents:

        distance = document.get(
            "score"
        )

        relevance = distance_to_relevance(
            distance
        )

        relevance_scores.append(
            relevance
        )


    if not relevance_scores:
        return 0.0


    # Use the strongest evidence
    max_relevance = max(
        relevance_scores
    )


    # Convert to percentage
    confidence = (
        max_relevance * 100
    )


    return round(
        confidence,
        2
    )


def calculate_evidence_coverage(
    documents,
    threshold=0.5
):
    """
    Calculate how many retrieved documents
    have meaningful relevance.
    """

    if not documents:
        return 0.0


    relevant = 0


    for document in documents:

        distance = document.get(
            "score"
        )

        relevance = distance_to_relevance(
            distance
        )

        if relevance >= threshold:

            relevant += 1


    coverage = (
        relevant /
        len(documents)
    )


    return round(
        coverage,
        4
    )


def calculate_final_confidence(
    documents
):

    retrieval_confidence = (
        calculate_retrieval_confidence(
            documents
        )
    )


    evidence_coverage = (
        calculate_evidence_coverage(
            documents
        )
    )


    final_confidence = (

        retrieval_confidence * 0.7

        +

        (evidence_coverage * 100) * 0.3

    )


    return round(
        final_confidence,
        2
    )