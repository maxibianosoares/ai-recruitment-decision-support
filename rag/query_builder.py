def candidate_query(

    candidate,

    job

):

    skills = ", ".join(

        candidate.get(

            "skills",

            []

        )

    )

    job_skills = ", ".join(

        job.get(

            "skills",

            []

        )

    )

    return f"""

Candidate Skills

{skills}

Job Skills

{job_skills}

Provide recruitment recommendation.

"""