from .skill_gap_analysis import analyze_skill_gap


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
        "education",
        ""
    ) or ""

    candidate_education = candidate_profile.get(
        "education",
        ""
    ) or ""

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
        "years_experience",
        0
    ) or 0

    candidate_exp = candidate_profile.get(
        "years_experience",
        0
    ) or 0

    try:
        candidate_exp = float(candidate_exp)
    except (TypeError, ValueError):
        candidate_exp = 0

    try:
        required_exp = float(required_exp)
    except (TypeError, ValueError):
        required_exp = 0

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
        "languages",
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
        "certifications",
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
    # Single source of truth: delegate to the same analyze_skill_gap()
    # used by skill_gap_analysis.py, so the Rule Engine card and the
    # Skill Gap Analysis card on Candidate Detail can never disagree
    # about which skills matched (both use identical
    # .strip().lower() set comparison).
    # -----------------------------

    required_skills = job_requirement.get(
        "skills",
        []
    )

    candidate_skills_raw = candidate_profile.get(
        "skills",
        []
    )

    skill_gap = analyze_skill_gap(
        candidate_skills_raw,
        required_skills
    )

    missing_skills = skill_gap["missing_skills"]

    matched_skills = skill_gap["matched_skills"]

    if missing_skills:

        passed = False

        failed_rules.append(
            f"Missing required skills: {', '.join(missing_skills)}"
        )

    elif required_skills:

        passed_rules.append(
            "Technical skills satisfied."
        )

    return {

        "eligible": passed,

        "passed_rules": passed_rules,

        "failed_rules": failed_rules,

        "warnings": warnings,

        "matched_skills": matched_skills,

        "missing_skills": missing_skills

    }