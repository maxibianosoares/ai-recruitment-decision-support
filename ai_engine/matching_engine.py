def calculate_match_score(
    candidate_skills,
    job_skills
):

    if not job_skills:
        return 0

    matched = 0

    for skill in candidate_skills:

        if skill in job_skills:

            matched += 1

    score = (
        matched / len(job_skills)
    ) * 100

    return round(score, 2)