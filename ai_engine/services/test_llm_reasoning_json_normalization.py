"""
Regression tests for the 2026-09-26 bug fix in
ai_engine/services/llm_reasoning.py: online_gemma occasionally wraps
the fused-reasoning assessment object in a single-item JSON array
([{...}]) instead of returning the bare object ({...}) -- the THIRD
confirmed occurrence of the same shape bug already fixed in
analyze_cv() and analyze_job_description(). This one was SILENT: with
no unwrap step, _normalize_assessment()'s `isinstance(raw_result,
dict)` check treated the array as "not a dict" and discarded the
entire real assessment (confirmed live for candidate "Joao Martins" /
job "Junior Web Developer": a fully-reasoned "Not Recommended",
confidence=100 response was replaced with silent all-zero/empty
defaults and decision "Consider", with ai_status left at "SUCCESS").

Mirrors the structure of the other two normalization test files. No
prompt/model/provider/RAG/Rule Engine/scoring/DB change is exercised
or required by these tests.
"""
from unittest.mock import patch

from django.test import TestCase

from ai_engine.services.llm_reasoning import (
    generate_recruitment_assessment,
    DEFAULT_ASSESSMENT,
)


MINIMAL_PROFILE = {
    "education": "Bachelor",
    "skills": ["Python"],
    "languages": [],
    "certifications": [],
    "years_experience": 3,
    "professional_summary": "Developer",
}

MINIMAL_JOB_PROFILE = {
    "job_title": "Developer",
    "education": "Bachelor",
    "skills": ["Python"],
    "languages": [],
    "certifications": [],
    "years_experience": 2,
    "professional_summary": "Dev role",
}

MINIMAL_RULE_RESULT = {"eligible": True, "matrix": {}}
MINIMAL_GAP_RESULT = {"match_score": 100, "matched_skills": ["Python"], "missing_skills": []}


def _call_with_mocked_llm(return_value):
    with patch(
        "ai_engine.services.llm_reasoning.generate_json",
        return_value=return_value,
    ) as mock_gj:
        result = generate_recruitment_assessment(
            profile=MINIMAL_PROFILE,
            job_profile=MINIMAL_JOB_PROFILE,
            rule_result=MINIMAL_RULE_RESULT,
            gap_result=MINIMAL_GAP_RESULT,
        )
    return result, mock_gj


class GenerateRecruitmentAssessmentArrayUnwrapTests(TestCase):

    def test_normal_dict_response_accepted_unchanged(self):
        expected = {
            "dimension_scores": {
                "education": 80, "experience": 70, "technical_skills": 90,
                "soft_skills": 60, "certifications": 50, "languages": 40,
            },
            "overall_score": 70,
            "strengths": ["Good fit"],
            "weaknesses": [],
            "decision": "Recommended",
            "confidence": 85,
            "reasoning": ["Solid match."],
            "risks": [],
            "recommendation": "Proceed to interview.",
        }
        result, mock_gj = _call_with_mocked_llm(dict(expected))

        mock_gj.assert_called_once()
        self.assertEqual(result["decision"], "Recommended")
        self.assertEqual(result["overall_score"], 70)
        self.assertEqual(result["confidence"], 85)
        self.assertEqual(result["reasoning"], ["Solid match."])
        self.assertEqual(result["recommendation"], "Proceed to interview.")

    def test_maria_da_costa_style_single_item_array_unwrapped(self):
        """
        Reproduces the exact production shape that silently destroyed a
        fully-reasoned assessment: a single-item JSON array. Expected,
        after the fix: the real decision/confidence/reasoning survive
        intact instead of being replaced by all-zero/empty defaults.
        """
        real_assessment = {
            "dimension_scores": {
                "education": 100, "experience": 100, "technical_skills": 0,
                "soft_skills": 0, "certifications": 100, "languages": 0,
            },
            "overall_score": 33,
            "strengths": ["Strong academic background."],
            "weaknesses": ["No web development evidence."],
            "decision": "Not Recommended",
            "confidence": 100,
            "reasoning": ["Fundamental mismatch with job requirements."],
            "risks": ["Significant skill gap."],
            "recommendation": "Do not proceed for this role.",
        }
        wrapped_response = [real_assessment]

        result, mock_gj = _call_with_mocked_llm(wrapped_response)

        mock_gj.assert_called_once()  # no unnecessary retry

        # Before the fix, all of these would have silently come back as
        # the DEFAULT_ASSESSMENT shape (0 / "" / [] / decision
        # "Consider") even though ai_status stayed "SUCCESS".
        self.assertEqual(result["decision"], "Not Recommended")
        self.assertEqual(result["overall_score"], 33)
        self.assertEqual(result["confidence"], 100)
        self.assertEqual(
            result["reasoning"],
            ["Fundamental mismatch with job requirements."],
        )
        self.assertEqual(
            result["recommendation"], "Do not proceed for this role."
        )
        self.assertEqual(result["dimension_scores"]["education"], 100)
        self.assertEqual(result["dimension_scores"]["technical_skills"], 0)

    def test_empty_array_response_falls_back_to_safe_defaults(self):
        result, mock_gj = _call_with_mocked_llm([])

        mock_gj.assert_called_once()
        # [] is falsy -> hits the existing "Empty response" error path
        # (DEFAULT_ASSESSMENT copy, unnormalized decision=""), same as
        # an empty dict {} always has -- not silently treated as a
        # fully-reasoned assessment.
        self.assertEqual(result["decision"], "")
        self.assertEqual(result["overall_score"], 0)
        self.assertEqual(result["reasoning"], [])
        self.assertIn("Reasoning unavailable", result["recommendation"])

    def test_multi_object_array_no_silent_pick_falls_back_to_safe_defaults(self):
        result, mock_gj = _call_with_mocked_llm(
            [{"decision": "Recommended"}, {"decision": "Not Recommended"}]
        )

        mock_gj.assert_called_once()
        # Ambiguous shape -- must not guess which object is the "real"
        # one. Falls back to the same safe defaults as an empty/invalid
        # response, exactly like before this fix.
        self.assertEqual(result["decision"], "Consider")
        self.assertEqual(result["overall_score"], 0)
        self.assertEqual(result["reasoning"], [])

    def test_empty_dict_response_still_uses_existing_retry_error_path(self):
        result, mock_gj = _call_with_mocked_llm({})

        mock_gj.assert_called_once()
        self.assertEqual(result["decision"], "")
        self.assertIn("Reasoning unavailable", result["recommendation"])

    def test_default_assessment_shape_unaffected(self):
        # Sanity check the fixture itself matches the real schema keys.
        self.assertEqual(
            set(DEFAULT_ASSESSMENT.keys()),
            {
                "dimension_scores", "overall_score", "strengths",
                "weaknesses", "decision", "confidence", "reasoning",
                "risks", "recommendation",
            },
        )    