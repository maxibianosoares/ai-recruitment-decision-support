"""
Lightweight unit tests for candidate_legal_rag.py's DETERMINISTIC
logic only (dimension filtering, query construction, cache key,
status mapping). Mocks rag.evidence_coverage.evidence_coverage so
these run without Ollama or a real embedding model -- this sandbox
has no access to either (see session notes: localhost:11434
unreachable, huggingface.co blocked by network policy).

This does NOT replace Step 10/11/12 (real unit tests, RAG regression,
40-question + candidate benchmark) which require the user's local
machine with Ollama running. Run with:
    DJANGO_SETTINGS_MODULE=core.settings python3 -m ai_engine.services.test_candidate_legal_rag_unit
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django
django.setup()

from django.core.cache import cache

from ai_engine.services import candidate_legal_rag as m


PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# =====================================================
# 1. Dimension filtering (Step 4) -- the Bachelor/Diploma example
#    from the design report Section 7
# =====================================================

print("\n== Dimension filtering ==")

rule_result_gap = {
    "matrix": [
        {"requirement": "Education: Bachelor Degree in IT/CS/IS", "evidence": "Diploma in IT", "met": False},
        {"requirement": "Experience: 2.0+ years", "evidence": "3.0 years", "met": True},
        {"requirement": "Language: English", "evidence": "Tetum", "met": False},
        {"requirement": "Certification (preferred): PMP", "evidence": "None listed", "met": False},
        {"requirement": "Skill: Python", "evidence": "Python, SQL", "met": True},
    ]
}

needs, has_req = m._dimensions_needing_legal_grounding(rule_result_gap)

check("education flagged (gap: Bachelor required, Diploma held)", needs["education"] is True)
check("experience NOT flagged (met=True, no gap)", needs["experience"] is False)
check("experience has_requirement True (job specified experience)", has_req["experience"] is True)
check("language flagged (missing required language)", needs["language"] is True)
check("certification flagged (preferred cert missing)", needs["certification"] is True)
check("skill dimension excluded entirely (not in _DIMENSION_PREFIXES)", "skill" not in needs)

rule_result_no_gaps = {
    "matrix": [
        {"requirement": "Education: Bachelor Degree", "evidence": "Bachelor Degree in IT", "met": True},
    ]
}

needs2, has_req2 = m._dimensions_needing_legal_grounding(rule_result_no_gaps)
check("education NOT flagged when already met", needs2["education"] is False)
check("experience has_requirement False (job never mentioned it)", has_req2["experience"] is False)

rule_result_empty = {"matrix": []}
needs3, has_req3 = m._dimensions_needing_legal_grounding(rule_result_empty)
check("empty matrix -> nothing flagged", all(v is False for v in needs3.values()))

# Defensive: missing/None rule_result must not raise
needs4, has_req4 = m._dimensions_needing_legal_grounding({})
check("missing matrix key -> nothing flagged, no crash", all(v is False for v in needs4.values()))


# =====================================================
# 2. Targeted query construction (Step 5) -- must include
#    requirement + candidate condition + recruitment context,
#    never a bare keyword.
# =====================================================

print("\n== Targeted query construction ==")

profile = {
    "education": "Diploma in Information Technology",
    "years_experience": 3,
    "languages": ["Tetum", "Indonesian"],
    "certifications": [],
}
job_profile = {
    "education": "Bachelor Degree in IT/CS/IS or related field",
    "years_experience": 2,
    "languages": ["English"],
    "certifications": ["PMP"],
}

edu_q = m._build_targeted_query("education", profile, job_profile)
check("education query contains job requirement", "Bachelor Degree in IT/CS/IS" in edu_q)
check("education query contains candidate condition", "Diploma in Information Technology" in edu_q)
check("education query is not a bare keyword", edu_q.strip() != "education")

exp_q = m._build_targeted_query("experience", profile, job_profile)
check("experience query contains required years", "2" in exp_q)
check("experience query contains candidate years", "3" in exp_q)

lang_q = m._build_targeted_query("language", profile, job_profile)
check("language query contains required language", "English" in lang_q)
check("language query contains candidate languages", "Tetum" in lang_q)

cert_q = m._build_targeted_query("certification", profile, job_profile)
check("certification query contains required cert", "PMP" in cert_q)
check("certification query handles empty candidate certs gracefully", "no listed certification" in cert_q)

try:
    m._build_targeted_query("medical", profile, job_profile)
    check("unknown dimension raises ValueError", False, "did not raise")
except ValueError:
    check("unknown dimension raises ValueError", True)


# =====================================================
# 3. Cache key (Step 7) -- must depend on profile+job+dimension+
#    version, NOT candidate_id; must change when profile changes.
# =====================================================

print("\n== Cache key ==")

key_a = m._cache_key("education", profile, job_profile)
key_b = m._cache_key("education", profile, job_profile)
check("same inputs -> same cache key (deterministic)", key_a == key_b)

profile_changed = dict(profile)
profile_changed["education"] = "Bachelor Degree in Computer Science"
key_c = m._cache_key("education", profile_changed, job_profile)
check("changed candidate profile -> different cache key", key_a != key_c)

key_d = m._cache_key("experience", profile, job_profile)
check("different dimension -> different cache key", key_a != key_d)

check("cache key format", key_a.startswith("candidate_legal_rag:"))


# =====================================================
# 4. Status mapping (Step 6, mocked evidence_coverage -- no real
#    retrieval/LLM call, this sandbox cannot reach Ollama or
#    huggingface.co)
# =====================================================

print("\n== Status mapping (evidence_coverage mocked) ==")

def _mock_evaluate_supported(claims):
    return {
        "claims": [{
            "id": claims[0]["id"], "claim": claims[0]["text"],
            "supported": True, "score": 0.81, "document": "policy.pdf",
            "evidence": "Article 8 ... non-discriminatory basis.",
            "verification_reason": "Matches same population.",
        }]
    }

def _mock_evaluate_below_threshold(claims):
    return {
        "claims": [{
            "id": claims[0]["id"], "claim": claims[0]["text"],
            "supported": False, "score": 0.30, "document": None,
            "evidence": None, "verification_reason": "Below threshold.",
        }]
    }

def _mock_evaluate_rejected_by_verifier(claims):
    return {
        "claims": [{
            "id": claims[0]["id"], "claim": claims[0]["text"],
            "supported": False, "score": 0.70, "document": "Decree_Law_22_2011.pdf",
            "evidence": "unrelated scheme text",
            "verification_reason": "Wrong population/scheme.",
        }]
    }

with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_supported), \
     patch.object(m.evidence_coverage, "threshold", 0.55):
    status, evidence = m._retrieve_dimension_evidence("education", "query text")
    check("supported=True -> evidence_found", status == "evidence_found")
    check("evidence_found carries verbatim_text", evidence and evidence[0]["verbatim_text"])

with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_below_threshold), \
     patch.object(m.evidence_coverage, "threshold", 0.55):
    status, evidence = m._retrieve_dimension_evidence("education", "query text")
    check("below threshold -> evidence_not_found", status == "evidence_not_found")
    check("evidence_not_found carries no evidence entries", evidence == [])

with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_rejected_by_verifier), \
     patch.object(m.evidence_coverage, "threshold", 0.55):
    status, evidence = m._retrieve_dimension_evidence("education", "query text")
    check("above threshold but verifier rejects -> evidence_insufficient", status == "evidence_insufficient")


# =====================================================
# 5. Full get_candidate_legal_evidence() -- integration of the
#    above, cache hit/miss counting, "not needed" dimensions never
#    trigger retrieval at all (Section 6/11 -- filter BEFORE
#    retrieval).
# =====================================================

print("\n== get_candidate_legal_evidence() integration (mocked) ==")

cache.clear()

call_count = {"n": 0}

def _mock_evaluate_counting(claims):
    call_count["n"] += 1
    return _mock_evaluate_supported(claims)

with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_counting), \
     patch.object(m.evidence_coverage, "threshold", 0.55):

    result, stats = m.get_candidate_legal_evidence(profile, job_profile, rule_result_gap)

    check("all 4 dimensions present in output", set(result.keys()) == {"education", "experience", "language", "certification"})
    check("education retrieved (gap)", result["education"]["status"] == "evidence_found")
    check("experience NOT retrieved (met=True) -> not_applicable", result["experience"]["status"] == "not_applicable")
    check("retrieval only called for flagged dimensions (education, language, certification = 3)", call_count["n"] == 3, f"got {call_count['n']}")
    check("stats.dimensions_checked == 4", stats["dimensions_checked"] == 4)
    check("stats.dimensions_retrieved == 3", stats["dimensions_retrieved"] == 3)
    check("stats.cache_miss == 3 on first run", stats["cache_miss"] == 3)
    check("stats.cache_hit == 0 on first run", stats["cache_hit"] == 0)

    call_count["n"] = 0
    result2, stats2 = m.get_candidate_legal_evidence(profile, job_profile, rule_result_gap)
    check("second identical run: no new retrieval calls (cache hit)", call_count["n"] == 0, f"got {call_count['n']}")
    check("second run: cache_hit == 3", stats2["cache_hit"] == 3)
    check("second run: cache_miss == 0", stats2["cache_miss"] == 0)
    check("cached result identical to first result", result2 == result)


# =====================================================
# 6. Error handling -- module must never raise, even if
#    evidence_coverage.evaluate() itself raises.
# =====================================================

print("\n== Error handling (never raises) ==")

cache.clear()

def _mock_evaluate_raises(claims):
    raise RuntimeError("Ollama unreachable")

with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_raises), \
     patch.object(m.evidence_coverage, "threshold", 0.55):
    try:
        result, stats = m.get_candidate_legal_evidence(profile, job_profile, rule_result_gap)
        check("exception in evaluate() does not propagate", True)
        check("failed dimension marked evidence_not_found", result["education"]["status"] == "evidence_not_found")
    except Exception as e:
        check("exception in evaluate() does not propagate", False, str(e))

check("None inputs do not raise", True if m.get_candidate_legal_evidence(None, None, None) else True)


# =====================================================
# 7. Status vocabulary -- no invented statuses anywhere.
# =====================================================

print("\n== Status vocabulary ==")

cache.clear()
with patch.object(m.evidence_coverage, "evaluate", side_effect=_mock_evaluate_supported), \
     patch.object(m.evidence_coverage, "threshold", 0.55):
    result, _ = m.get_candidate_legal_evidence(profile, job_profile, rule_result_gap)
    all_statuses = {v["status"] for v in result.values()}
    check("only allowed statuses used", all_statuses.issubset(m.ALLOWED_STATUSES), all_statuses)


print(f"\n{'='*50}\nTOTAL: {PASS} passed, {FAIL} failed\n{'='*50}")

sys.exit(1 if FAIL else 0)