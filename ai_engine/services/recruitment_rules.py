def evaluate_recruitment_rules(
    candidate_profile,
    job_requirement
):
    """
    Rule-Based Recruitment Engine

    Hard Rules berdasarkan:
    - Decreto-Lei 34/2008
    - Decreto-Lei 22/2011

    Input:
        candidate_profile (dict)
        job_requirement (dict)

    Output:
        dict
    """

    passed = True

    passed_rules = []

    failed_rules = []

    warnings = []

    # -----------------------------
    # Education
    # -----------------------------

    required_education = job_requirement.get(
        "required_education",
        ""
    )

    candidate_education = candidate_profile.get(
        "education",
        ""
    )

    if required_education:

        if required_education.lower() in candidate_education.lower():

            passed_rules.append(
                "Education requirement satisfied."
            )

        else:

            passed = False

            failed_rules.append(
                f"Required education: {required_education}"
            )

    # -----------------------------
    # Experience
    # -----------------------------

    required_exp = job_requirement.get(
        "minimum_experience",
        0
    )

    candidate_exp = candidate_profile.get(
        "years_experience",
        0
    )

    if candidate_exp >= required_exp:

        passed_rules.append(
            "Minimum experience satisfied."
        )

    else:

        passed = False

        failed_rules.append(
            f"Minimum {required_exp} years experience required."
        )

    # -----------------------------
    # Languages
    # -----------------------------

    required_languages = job_requirement.get(
        "required_languages",
        []
    )

    candidate_languages = [
        x.lower()
        for x in candidate_profile.get(
            "languages",
            []
        )
    ]

    for language in required_languages:

        if language.lower() not in candidate_languages:

            passed = False

            failed_rules.append(
                f"Missing language: {language}"
            )

    if required_languages:

        if all(
            language.lower() in candidate_languages
            for language in required_languages
        ):
            passed_rules.append(
                "Language requirement satisfied."
            )

    # -----------------------------
    # Certifications
    # -----------------------------

    required_certifications = job_requirement.get(
        "required_certifications",
        []
    )

    candidate_certifications = [
        x.lower()
        for x in candidate_profile.get(
            "certifications",
            []
        )
    ]

    for cert in required_certifications:

        if cert.lower() not in candidate_certifications:

            warnings.append(
                f"Preferred certification missing: {cert}"
            )

    # -----------------------------
    # Skills
    # -----------------------------

    required_skills = job_requirement.get(
        "required_skills",
        []
    )

    candidate_skills = [
        x.lower()
        for x in candidate_profile.get(
            "skills",
            []
        )
    ]

    missing_skills = []

    for skill in required_skills:

        if skill.lower() not in candidate_skills:

            missing_skills.append(skill)

    if missing_skills:

        warnings.append(
            f"Missing skills: {', '.join(missing_skills)}"
        )

    else:

        passed_rules.append(
            "Technical skills satisfied."
        )

    return {

        "eligible": passed,

        "passed_rules": passed_rules,

        "failed_rules": failed_rules,

        "warnings": warnings

    }