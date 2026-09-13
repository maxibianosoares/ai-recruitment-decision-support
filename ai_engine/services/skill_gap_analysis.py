def analyze_skill_gap(
    candidate_skills,
    job_skills
):

    candidate_set = {
        skill.strip().lower()
        for skill in candidate_skills
    }

    job_set = {
        skill.strip().lower()
        for skill in job_skills
    }

    matched = list(
        candidate_set.intersection(job_set)
    )

    missing = list(
        job_set - candidate_set
    )

    score = 0

    if len(job_set) > 0:

        score = (
            len(matched)
            / len(job_set)
        ) * 100

    return {
        "matched_skills": matched,
        "missing_skills": missing,
        "match_score": round(
            score,
            2
        )
    }


def skill_gap_analysis(
    candidate_skills,
    job_skills
):
    return analyze_skill_gap(
        candidate_skills,
        job_skills
    )