from concurrent.futures import ThreadPoolExecutor

from .recruitment_pipeline import recruitment_pipeline


def evaluate_candidate(candidate):

    result = recruitment_pipeline(
        candidate["cv"],
        candidate["job_description"]
    )

    return {

        "candidate_name": candidate["name"],

        "overall_score": result["semantic"]["overall_score"],

        "decision": result["report"]["decision"],

        "confidence": result["report"]["confidence"],

        "result": result

    }


def rank_candidates(candidates):

    ranked = []

    with ThreadPoolExecutor(max_workers=4) as executor:

        results = executor.map(
            evaluate_candidate,
            candidates
        )

        ranked = list(results)

    ranked.sort(

        key=lambda x: x["overall_score"],

        reverse=True

    )

    for index, item in enumerate(ranked):

        item["rank"] = index + 1

    return ranked