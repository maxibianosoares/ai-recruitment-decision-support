from .embedding_engine import embedding_engine

from .vector_utils import similarity_score

from .profile_to_text import profile_to_text


def semantic_match(
    candidate_profile,
    job_profile
):

    candidate_text = profile_to_text(
        candidate_profile
    )

    job_text = profile_to_text(
        job_profile
    )

    candidate_vector = embedding_engine.encode(
        candidate_text
    )

    job_vector = embedding_engine.encode(
        job_text
    )

    score = similarity_score(
        candidate_vector,
        job_vector
    )

    return {

        "overall_score": round(
            score * 100,
            2
        ),

        "semantic_similarity": round(
            score,
            4
        )

    }