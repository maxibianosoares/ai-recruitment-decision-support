import numpy as np

from .skill_gap_analysis import (
    analyze_skill_gap,
    _normalize,
    _classify,
    STRONG_MATCH,
    MATCH,
    RELATED,
    PARTIAL,
    MISSING,
)
from ai_engine.services.embedding_engine import embedding_engine


# =====================================================================
# TASK C -- GRADED RULE ENGINE (2026-09-30)
#
# Upgraded from PASS/FAIL binary checks to graded evidence levels, so
# a near-miss (e.g. 1 year 10 months against a 2-year requirement) is
# no longer treated identically to a candidate with zero experience.
#
# Two NEW levels specific to this file (not used by Skill Matching):
#   NEAR_REQUIREMENT -- close enough to count as met (experience only)
#   UNKNOWN           -- could not be evaluated (missing/ambiguous
#                         data, or an embedding-model failure) --
#                         treated as a WARNING, never a hard fail,
#                         since penalizing a candidate for a data gap
#                         that isn't their fault would be unfair.
#
# Everything else reuses the SAME 5 levels + SAME calibrated
# thresholds already validated in skill_gap_analysis.py (TASK B) --
# no second threshold set to guess or maintain.
#
# Backward compatibility: the return shape (eligible, passed_rules,
# failed_rules, warnings, matched_skills, missing_skills, matrix) is
# UNCHANGED -- recruitment_pipeline.py, candidate_legal_rag.py, the
# candidate_detail.html template, and every management command that
# reads rule_result still work with no changes. Each matrix row keeps
# its "requirement" / "evidence" / "met" keys exactly as before (and
# candidate_legal_rag.py's dimension-prefix matching, e.g.
# "Education:", "Experience:", still works) -- "level" and
# "similarity" are ADDITIVE, new keys nothing existing reads yet.
#
# IMPORTANT CALIBRATION NOTE: the STRONG_MATCH/MATCH/RELATED/PARTIAL
# thresholds reused below for Education were calibrated in TASK B on
# short skill PHRASES ("Python" vs "Cisco Networking"), not full
# degree-title sentences. They may not be perfectly tuned for
# Education text specifically. Run
#
#     python manage.py test_rule_engine
#
# on your own machine (this sandbox cannot reach the embedding model)
# to see real similarity numbers for Education before fully trusting
# them -- adjust EDUCATION-specific thresholds below only if that
# test shows a real problem.
# =====================================================================

NEAR_REQUIREMENT = "NEAR_REQUIREMENT"
UNKNOWN = "UNKNOWN"

# A requirement at one of these levels counts as satisfied (does not
# block eligibility). PARTIAL, MISSING and UNKNOWN do not -- UNKNOWN
# still shows as a gap in the matrix/candidate_legal_rag (so it can
# get RAG grounding), but only goes to `warnings`, never
# `failed_rules`, so it alone never flips `eligible` to False.
HARD_PASS_LEVELS = {STRONG_MATCH, MATCH, RELATED, NEAR_REQUIREMENT}

# Experience ratio (candidate_years / required_years) cut points.
EXPERIENCE_STRONG_MATCH_RATIO = 1.5
EXPERIENCE_MATCH_RATIO = 1.0
EXPERIENCE_NEAR_REQUIREMENT_RATIO = 0.85
EXPERIENCE_PARTIAL_RATIO = 0.25


def _graded_text_match(required_text, candidate_text):
    """
    Graded requirement-vs-evidence comparison for free-text fields
    (currently used for Education only). Exact-substring still
    short-circuits to STRONG_MATCH (identical behaviour to the old
    code for the common case); otherwise falls back to the same
    embedding + classify() used by Skill Matching.
    """

    req_norm = _normalize(required_text)
    cand_norm = _normalize(candidate_text)

    if not req_norm:
        return STRONG_MATCH, 1.0

    if req_norm in cand_norm:
        return STRONG_MATCH, 1.0

    if not cand_norm:
        return MISSING, 0.0

    try:
        vectors = embedding_engine.encode([req_norm, cand_norm])
        similarity = float(np.dot(vectors[0], vectors[1]))
    except Exception:
        return UNKNOWN, None

    return _classify(similarity), round(similarity, 3)


def _graded_experience_match(required_years, candidate_years):
    """
    Graded years-of-experience comparison. No requirement stated
    (required_years <= 0) is trivially satisfied.
    """

    if required_years <= 0:
        return MATCH, None

    ratio = candidate_years / required_years

    if ratio >= EXPERIENCE_STRONG_MATCH_RATIO:
        return STRONG_MATCH, round(ratio, 2)

    if ratio >= EXPERIENCE_MATCH_RATIO:
        return MATCH, round(ratio, 2)

    if ratio >= EXPERIENCE_NEAR_REQUIREMENT_RATIO:
        return NEAR_REQUIREMENT, round(ratio, 2)

    if ratio >= EXPERIENCE_PARTIAL_RATIO:
        return PARTIAL, round(ratio, 2)

    return MISSING, round(ratio, 2)


def evaluate_recruitment_rules(
    candidate_profile,
    job_requirement
):
    """
    Rule-Based Recruitment Engine (graded -- see module docstring)

    Hard Rules berdasarkan:
    - Decreto-Lei 34/2008
    - Decreto-Lei 22/2011

    Input:
        candidate_profile (dict)
        job_requirement (dict)

    Output:
        dict (same shape as before TASK C -- see module docstring)
    """

    passed = True

    passed_rules = []

    failed_rules = []

    warnings = []

    matrix = []

    # -----------------------------
    # Education (graded)
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

        education_level, education_similarity = _graded_text_match(
            required_education, candidate_education
        )

        education_met = education_level in HARD_PASS_LEVELS

        if education_level == UNKNOWN:

            warnings.append(
                f"Could not verify education requirement (internal error): {required_education}"
            )

        elif education_met:

            passed_rules.append(
                f"Education requirement satisfied ({education_level})."
            )

        else:

            passed = False

            failed_rules.append(
                f"Required education: {required_education} (evidence level: {education_level})"
            )

        matrix.append({
            "requirement": f"Education: {required_education}",
            "evidence": candidate_education or "Not stated",
            "met": education_met,
            "level": education_level,
            "similarity": education_similarity
        })

    # -----------------------------
    # Experience (graded)
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

    experience_level, experience_ratio = _graded_experience_match(
        required_exp, candidate_exp
    )

    experience_met = experience_level in HARD_PASS_LEVELS

    if experience_met:

        passed_rules.append(
            f"Experience requirement satisfied ({experience_level})."
        )

    else:

        passed = False

        failed_rules.append(
            f"Minimum {required_exp} years experience required "
            f"(candidate has {candidate_exp}, evidence level: {experience_level})."
        )

    matrix.append({
        "requirement": f"Experience: {required_exp}+ years",
        "evidence": f"{candidate_exp} years",
        "met": experience_met,
        "level": experience_level,
        "similarity": experience_ratio
    })

    # -----------------------------
    # Languages (exact requirement -- UNKNOWN when CV lists none at
    # all, so a missing extraction isn't punished as a hard fail)
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

        if not candidate_languages:
            language_level = UNKNOWN
        elif language.lower() in candidate_languages:
            language_level = MATCH
        else:
            language_level = MISSING

        language_met = language_level in HARD_PASS_LEVELS

        if language_level == MISSING:

            passed = False

            failed_rules.append(
                f"Missing language: {language}"
            )

        elif language_level == UNKNOWN:

            warnings.append(
                f"Could not confirm language (no languages listed on CV): {language}"
            )

        matrix.append({
            "requirement": f"Language: {language}",
            "evidence": (
                ", ".join(candidate_profile.get("languages", []))
                or "Not stated"
            ),
            "met": language_met,
            "level": language_level
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
    # Certifications (unchanged -- already soft/preferred, not a
    # hard-eligibility gate, so out of TASK C's graded-eligibility
    # scope)
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
    # Skills (graded -- reuses skill_gap_analysis.py's per-skill
    # "level" directly, computed once. No second skill-matching
    # logic implemented here.)
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

    skill_details_by_job_skill = {
        detail["job_skill"]: detail
        for detail in skill_gap.get("skill_details", [])
    }

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

        detail = skill_details_by_job_skill.get(_normalize(skill), {})

        skill_level = detail.get("level", MISSING)

        skill_met = skill_level in HARD_PASS_LEVELS

        matrix.append({
            "requirement": f"Skill: {skill}",
            "evidence": (
                ", ".join(candidate_skills_raw) or "None listed"
            ),
            "met": skill_met,
            "level": skill_level,
            "similarity": detail.get("similarity"),
            "matched_candidate_skill": detail.get("matched_candidate_skill")
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