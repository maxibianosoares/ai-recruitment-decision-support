def generate_explanation(
    candidate_name,
    match_result
):

    matched = match_result[
        "matched_skills"
    ]

    missing = match_result[
        "missing_skills"
    ]

    score = match_result[
        "match_score"
    ]

    explanation = f"""
Candidate: {candidate_name}

Match Score: {score}%

Matched Skills:
{', '.join(matched)}

Missing Skills:
{', '.join(missing)}

Recommendation:
"""

    if score >= 80:

        explanation += (
            "Candidate is highly suitable "
            "for this position."
        )

    elif score >= 60:

        explanation += (
            "Candidate is suitable "
            "for further evaluation."
        )

    else:

        explanation += (
            "Candidate currently lacks "
            "several required skills."
        )

    return explanation