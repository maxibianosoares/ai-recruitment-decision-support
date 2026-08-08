from sklearn.metrics.pairwise import cosine_similarity


def similarity_score(
    vector_a,
    vector_b
):

    score = cosine_similarity(
        [vector_a],
        [vector_b]
    )[0][0]

    return float(score)