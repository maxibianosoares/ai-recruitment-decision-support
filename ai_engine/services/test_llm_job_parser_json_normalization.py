"""
Regression tests for the 2026-09-26 bug fix in
ai_engine/services/llm_job_parser.py: online_gemma occasionally wraps
the job profile object in a single-item JSON array ([{...}]) instead
of returning the bare object ({...}) -- the same shape bug already
fixed in llm_candidate_profile.py, confirmed live in production for
this file too (job.ai_job_profile stored as a list, which then made
recruitment_pipeline.py's `job_profile.get("skills", [])` raise
"'list' object has no attribute 'get'" for every application to that
job).

Mirrors the structure of
test_llm_candidate_profile_json_normalization.py. No prompt/model/
provider/RAG/Rule Engine/scoring/DB change is exercised or required
by these tests.
"""
from unittest.mock import patch

from django.test import TestCase

from ai_engine.services.llm_job_parser import (
    analyze_job_description,
    DEFAULT_JOB_PROFILE,
    _normalize_job_profile_result,
)


class NormalizeJobProfileResultTests(TestCase):
    """Unit tests for _normalize_job_profile_result() in isolation."""

    def test_1_normal_dict_returned_unchanged(self):
        original = {
            "job_title": "ICT Officer",
            "skills": ["Networking"],
            "years_experience": 2,
        }
        result = _normalize_job_profile_result(original, attempt=1)
        self.assertIs(result, original)
        self.assertIsInstance(result, dict)

    def test_2_single_item_array_unwrapped_to_dict(self):
        inner = {
            "job_title": "ICT Officer",
            "skills": ["Networking"],
            "years_experience": 2,
        }
        result = _normalize_job_profile_result([inner], attempt=1)
        self.assertIsInstance(result, dict)
        self.assertIs(result, inner)

    def test_3_empty_array_not_unwrapped(self):
        result = _normalize_job_profile_result([], attempt=1)
        self.assertEqual(result, [])
        self.assertNotIsInstance(result, dict)

    def test_4_multiple_objects_not_unwrapped_no_silent_pick(self):
        first = {"job_title": "ICT Officer"}
        second = {"job_title": "ICT Manager"}
        result = _normalize_job_profile_result([first, second], attempt=1)
        self.assertEqual(result, [first, second])
        self.assertNotIsInstance(result, dict)

    def test_5_array_of_non_dict_not_unwrapped(self):
        result = _normalize_job_profile_result(["ICT Officer"], attempt=1)
        self.assertEqual(result, ["ICT Officer"])
        self.assertNotIsInstance(result, dict)

    def test_6_non_list_non_dict_passthrough(self):
        result = _normalize_job_profile_result("some text", attempt=1)
        self.assertEqual(result, "some text")


class AnalyzeJobDescriptionSuccessValidationTests(TestCase):
    """
    Integration-level tests for analyze_job_description()'s
    retry/success logic after the fix -- mocks generate_json() to
    control exactly what each attempt returns, without any real
    Ollama/online_gemma call.
    """

    def test_normal_dict_response_accepted_on_first_attempt_unchanged(self):
        expected = {
            "job_title": "ICT Support Officer",
            "education": "Bachelor's Degree",
            "skills": ["Networking", "SQL"],
            "languages": [],
            "certifications": [],
            "years_experience": 3,
            "professional_summary": "Support role",
        }
        with patch(
            "ai_engine.services.llm_job_parser.generate_json",
            return_value=dict(expected),
        ) as mock_gj:
            result = analyze_job_description("some job description")

        self.assertEqual(result, expected)
        mock_gj.assert_called_once()

    def test_single_item_array_response_unwrapped_no_unnecessary_retry(self):
        """
        Reproduces the exact production shape that corrupted
        job.ai_job_profile: a single-item JSON array. Expected:
        attempt 1 succeeds, no retry, result is a dict
        process_job()/recruitment_pipeline.py's guards accept.
        """
        job_profile = {
            "job_title": "ICT Officer",
            "education": "Bachelor",
            "skills": ["Computer Networks", "Database Systems"],
            "languages": ["Tetum", "English"],
            "certifications": [],
            "years_experience": 2,
            "professional_summary": "Government ICT support role.",
        }
        wrapped_response = [job_profile]

        with patch(
            "ai_engine.services.llm_job_parser.generate_json",
            return_value=wrapped_response,
        ) as mock_gj:
            result = analyze_job_description("some job description")

        self.assertIsInstance(result, dict)
        mock_gj.assert_called_once()
        self.assertEqual(result, job_profile)

        # Mirrors job_pipeline.py's own tightened guard, read-only, to
        # confirm it now passes instead of silently accepting a list.
        guard_would_fail = (
            not isinstance(result, dict)
            or not any(key in result for key in DEFAULT_JOB_PROFILE)
            or "error" in result
        )
        self.assertFalse(guard_would_fail)

    def test_empty_array_response_exhausts_retries_and_returns_falsy(self):
        with patch(
            "ai_engine.services.llm_job_parser.generate_json",
            return_value=[],
        ) as mock_gj:
            result = analyze_job_description("some job description")

        self.assertEqual(mock_gj.call_count, 3)
        self.assertEqual(result, [])

    def test_multi_object_array_exhausts_retries_no_silent_pick(self):
        with patch(
            "ai_engine.services.llm_job_parser.generate_json",
            return_value=[{"job_title": "A"}, {"job_title": "B"}],
        ) as mock_gj:
            result = analyze_job_description("some job description")

        self.assertEqual(mock_gj.call_count, 3)
        self.assertEqual(result, [{"job_title": "A"}, {"job_title": "B"}])

    def test_invalid_json_still_uses_existing_retry_error_path(self):
        with patch(
            "ai_engine.services.llm_job_parser.generate_json",
            return_value={},
        ) as mock_gj:
            result = analyze_job_description("some job description")

        self.assertEqual(mock_gj.call_count, 3)
        self.assertEqual(result, {})