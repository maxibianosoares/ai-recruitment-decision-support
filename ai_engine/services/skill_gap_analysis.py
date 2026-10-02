"""
Skill Matching -- Task B (2026-09-30)

Upgraded from pure exact-string matching to:

    Normalize -> Exact match -> Embedding semantic similarity -> Classify

Still 100% Python, deterministic, NO new LLM call. Reuses the
embedding model already loaded for RAG retrieval
(ai_engine/services/embedding_engine.py) -- no second model, no
duplicate loading, no new dependency (sentence-transformers is
already a required package).

Why: exact-string matching alone marked a candidate's "Cisco
Networking" as zero evidence for a job requiring "Network
Administration", even though they are clearly related. That false
"missing skill" also fed the Rule Engine's hard eligibility gate
(recruitment_rules.py calls this same function), so a close synonym
could cap a candidate's final ai_score at 49 for no real reason.

Backward compatibility (do not break the Rule Engine or scoring):
recruitment_rules.py and recruitment_pipeline.py both call this
module and read exactly 3 keys: matched_skills, missing_skills,
match_score. Those 3 keys keep their same shape (lists of the JOB's
required-skill strings, and a 0-100 float) -- only the CRITERIA for
what counts as "matched" is smarter now. Neither of those two files
needed to change.

New, additive info: "skill_details", a per-required-skill breakdown
(which candidate skill it matched, the match level, the similarity
score) for transparency / a future UI. Nothing existing reads this
key, so nothing breaks if it's ignored.

THRESHOLDS BELOW ARE A STARTING POINT, NOT FINAL: this sandbox has
no network access to download the embedding model
(BAAI/bge-base-en-v1.5), so these 4 cut points could not be
calibrated against real similarity numbers here. Run

    python manage.py test_skill_matching

on your own machine (where RAG already proves the model downloads
and runs) BEFORE trusting these numbers -- that command prints the
actual similarity score for every example in this file's own docs
so you can see whether STRONG_MATCH_THRESHOLD etc. need adjusting.
"""

import numpy as np

from ai_engine.services.embedding_engine import embedding_engine


STRONG_MATCH = "STRONG_MATCH"
MATCH = "MATCH"
RELATED = "RELATED"
PARTIAL = "PARTIAL"
MISSING = "MISSING"

# Used to turn the 5 levels into a single 0-100 match_score (keeps
# the same 0-100 scale recruitment_pipeline.py's compute_final_score
# already expects -- no change needed there).
_LEVEL_WEIGHTS = {
    STRONG_MATCH: 1.0,
    MATCH: 0.85,
    RELATED: 0.65,
    PARTIAL: 0.35,
    MISSING: 0.0,
}

# Cosine-similarity cut points. embedding_engine.encode() normalizes
# vectors, so cosine similarity == plain dot product (see
# _similarity below) -- no extra normalization needed here.
STRONG_MATCH_THRESHOLD = 0.85
MATCH_THRESHOLD = 0.70
RELATED_THRESHOLD = 0.65
PARTIAL_THRESHOLD = 0.62


def _normalize(skill):
    return skill.strip().lower()


def _classify(similarity):

    if similarity >= STRONG_MATCH_THRESHOLD:
        return STRONG_MATCH

    if similarity >= MATCH_THRESHOLD:
        return MATCH

    if similarity >= RELATED_THRESHOLD:
        return RELATED

    if similarity >= PARTIAL_THRESHOLD:
        return PARTIAL

    return MISSING


def _encode_all(skills):
    """
    One batched embedding call for every unique skill string in play
    (candidate skills + job skills combined), instead of one call
    per skill -- batching is the fast path for sentence-transformers
    and keeps this to a single model call per application regardless
    of how many skills are involved.

    Returns {} (not an exception) if the embedding model can't be
    loaded/reached -- callers degrade to exact-match-only behaviour
    in that case rather than crashing apply_job.
    """

    skills = sorted(skills)

    if not skills:
        return {}

    try:
        vectors = embedding_engine.encode(skills)
        return dict(zip(skills, vectors))
    except Exception:
        return {}


def _best_match_for_job_skill(job_skill_norm, candidate_skills_norm, embeddings):
    """
    Finds the candidate skill that best explains one required job
    skill. Exact match short-circuits (no embedding lookup needed --
    the common case, an identical skill string, is exactly as fast
    as the old code). Falls back to embedding similarity against
    every candidate skill, keeping only the single best one.
    """

    if job_skill_norm in candidate_skills_norm:
        return job_skill_norm, STRONG_MATCH, 1.0

    if not candidate_skills_norm or job_skill_norm not in embeddings:
        # No candidate skills to compare against, or the embedding
        # batch failed/was skipped -- same outcome as the old
        # exact-match-only code for this skill.
        return None, MISSING, 0.0

    job_vector = embeddings[job_skill_norm]

    best_candidate = None
    best_similarity = -1.0

    for candidate_skill_norm in candidate_skills_norm:

        candidate_vector = embeddings.get(candidate_skill_norm)

        if candidate_vector is None:
            continue

        similarity = float(np.dot(job_vector, candidate_vector))

        if similarity > best_similarity:
            best_similarity = similarity
            best_candidate = candidate_skill_norm

    if best_candidate is None:
        return None, MISSING, 0.0

    return best_candidate, _classify(best_similarity), round(best_similarity, 3)


def analyze_skill_gap(
    candidate_skills,
    job_skills
):

    candidate_set = {
        _normalize(skill)
        for skill in candidate_skills
    }

    job_set = {
        _normalize(skill)
        for skill in job_skills
    }

    embeddings = _encode_all(candidate_set | job_set)

    matched = []
    missing = []
    skill_details = []
    total_weight = 0.0

    for job_skill in job_set:

        best_candidate, level, similarity = _best_match_for_job_skill(
            job_skill, candidate_set, embeddings
        )

        skill_details.append({
            "job_skill": job_skill,
            "matched_candidate_skill": best_candidate,
            "level": level,
            "similarity": similarity
        })

        total_weight += _LEVEL_WEIGHTS[level]

        # STRONG_MATCH / MATCH / RELATED all count as the requirement
        # being satisfied (this is the change that fixes the
        # false-"missing skill" problem described at the top of this
        # file). PARTIAL and MISSING do not -- a loosely-related
        # skill still shouldn't satisfy a hard requirement.
        if level in (STRONG_MATCH, MATCH, RELATED):
            matched.append(job_skill)
        else:
            missing.append(job_skill)

    score = 0

    if len(job_set) > 0:
        score = (total_weight / len(job_set)) * 100

    return {
        "matched_skills": matched,
        "missing_skills": missing,
        "match_score": round(score, 2),
        "skill_details": skill_details
    }


def skill_gap_analysis(
    candidate_skills,
    job_skills
):
    return analyze_skill_gap(
        candidate_skills,
        job_skills
    )