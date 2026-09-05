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

    matrix = []

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

        education_met = required_education.lower() in candidate_education.lower()

        if education_met:

            passed_rules.append(
                "Education requirement satisfied."
            )

        else:

            passed = False

            failed_rules.append(
                f"Required education: {required_education}"
            )

        matrix.append({
            "requirement": f"Education: {required_education}",
            "evidence": candidate_education or "Not stated",
            "met": education_met
        })

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

    experience_met = candidate_exp >= required_exp

    if experience_met:

        passed_rules.append(
            "Minimum experience satisfied."
        )

    else:

        passed = False

        failed_rules.append(
            f"Minimum {required_exp} years experience required."
        )

    matrix.append({
        "requirement": f"Experience: {required_exp}+ years",
        "evidence": f"{candidate_exp} years",
        "met": experience_met
    })

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

        language_met = language.lower() in candidate_languages

        if not language_met:

            passed = False

            failed_rules.append(
                f"Missing language: {language}"
            )

        matrix.append({
            "requirement": f"Language: {language}",
            "evidence": (
                ", ".join(candidate_profile.get("languages", []))
                or "Not stated"
            ),
            "met": language_met
        })

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

        cert_met = cert.lower() in candidate_certifications

        if not cert_met:

            warnings.append(
                f"Preferred certification missing: {cert}"
            )

        matrix.append({
            "requirement": f"Certification (preferred): {cert}",
            "evidence": (
                ", ".join(candidate_profile.get("certifications", []))
                or "None listed"
            ),
            "met": cert_met
        })

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

    for skill in required_skills:

        skill_met = skill.strip().lower() in {
            s.lower() for s in matched_skills
        }

        matrix.append({
            "requirement": f"Skill: {skill}",
            "evidence": (
                ", ".join(candidate_skills_raw) or "None listed"
            ),
            "met": skill_met
        })

    return {

        "eligible": passed,

        "passed_rules": passed_rules,

        "failed_rules": failed_rules,

        "warnings": warnings,

        "matched_skills": matched_skills,

        "missing_skills": missing_skills,

        "matrix": matrix

    }