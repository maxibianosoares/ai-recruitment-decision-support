"""
Regression tests for the 2026-09-26 bug fix in
ai_engine/services/llm_candidate_profile.py: online_gemma
(model=gemma-4-26b-a4b-it) occasionally wraps the CV profile object in
a single-item JSON array ([{...}]) instead of returning the bare
object ({...}). json.loads() succeeds either way, so the old
`if result:` truthiness check accepted the list as a valid profile on
attempt 1 -- confirmed live in Railway production logs for candidate
"Maria da Costa" -- which then made recruitment_pipeline.py's
DEFAULT_PROFILE guard misclassify a fully-parsed profile as a
technical CV parsing failure.

Covers exactly the 6 unit cases + 1 integration case specified in the
bug-fix ticket. No prompt/model/provider/RAG/Rule Engine/scoring/DB
change is exercised or required by these tests.
"""
from unittest.mock import patch

from django.test import TestCase

from ai_engine.services.llm_candidate_profile import (
    analyze_cv,
    DEFAULT_PROFILE,
    _normalize_profile_result,
)


class NormalizeProfileResultTests(TestCase):
    """Unit tests for _normalize_profile_result() in isolation."""

    def test_1_normal_dict_returned_unchanged(self):
        original = {
            "education": "Bachelor",
            "skills": ["Python"],
            "years_experience": 3,
            "professional_summary": "Developer",
        }
        result = _normalize_profile_result(original, attempt=1)
        self.assertIs(result, original)  # not even a copy -- untouched
        self.assertIsInstance(result, dict)

    def test_2_single_item_array_unwrapped_to_dict(self):
        inner = {
            "education": "Bachelor",
            "skills": ["Python"],
            "years_experience": 3,
            "professional_summary": "Developer",
        }
        result = _normalize_profile_result([inner], attempt=1)
        self.assertIsInstance(result, dict)
        self.assertIs(result, inner)

    def test_3_empty_array_not_unwrapped(self):
        result = _normalize_profile_result([], attempt=1)
        self.assertEqual(result, [])
        self.assertNotIsInstance(result, dict)

    def test_4_multiple_objects_not_unwrapped_no_silent_pick(self):
        first = {"education": "Bachelor"}
        second = {"education": "Master"}
        result = _normalize_profile_result([first, second], attempt=1)
        self.assertEqual(result, [first, second])
        self.assertNotIsInstance(result, dict)

    def test_5_array_of_non_dict_not_unwrapped(self):
        result = _normalize_profile_result(["Bachelor"], attempt=1)
        self.assertEqual(result, ["Bachelor"])
        self.assertNotIsInstance(result, dict)

    def test_6_non_list_non_dict_passthrough(self):
        # Covers the "invalid JSON never reaches this function" case
        # indirectly: if generate_json() ever returned a bare string
        # or number (not raising, per its own default/{} contract),
        # normalization must not crash or fabricate a dict.
        result = _normalize_profile_result("some text", attempt=1)
        self.assertEqual(result, "some text")


class AnalyzeCvSuccessValidationTests(TestCase):
    """
    Integration-level tests for analyze_cv()'s retry/success logic
    after the fix -- mocks generate_json() to control exactly what
    each attempt returns, without any real Ollama/online_gemma call.
    """

    def test_normal_dict_response_accepted_on_first_attempt_unchanged(self):
        expected = {
            "education": "Bachelor's Degree",
            "skills": ["Python", "Django"],
            "languages": [],
            "certifications": [],
            "years_experience": 5,
            "professional_summary": "Backend developer",
        }
        with patch(
            "ai_engine.services.llm_candidate_profile.generate_json",
            return_value=dict(expected),
        ) as mock_gj:
            result = analyze_cv("some cv text")

        self.assertEqual(result, expected)
        mock_gj.assert_called_once()  # no retry needed

    def test_maria_da_costa_reproduction_single_item_array_unwrapped(self):
        """
        Reproduces the exact production shape from the Railway log:
        [{ "education": "...", "skills": [...], "years_experience": 2,
        "professional_summary": "..." }]
        Expected: attempt 1 succeeds, no unnecessary retry, result is
        a dict recruitment_pipeline.py's DEFAULT_PROFILE guard accepts.
        """
        maria_profile = {
            "education": "Bachelor of Information Systems, Universidade da Paz",
            "skills": [
                "Technical Troubleshooting",
                "Computer Networks",
                "Windows",
                "Basic Database Systems",
                "Help Desk Support",
            ],
            "languages": ["Tetum", "English"],
            "certifications": ["Microsoft Office Specialist"],
            "years_experience": 2,
            "professional_summary": (
                "ICT support specialist with approximately 2 years of "
                "experience working in private-sector technical support "
                "and basic system administration."
            ),
        }
        wrapped_response = [maria_profile]

        with patch(
            "ai_engine.services.llm_candidate_profile.generate_json",
            return_value=wrapped_response,
        ) as mock_gj:
            result = analyze_cv("Maria da Costa's CV text")

        # 1-4: json.loads/generate_json succeeded, list detected, unwrapped
        self.assertIsInstance(result, dict)
        # 5: attempt 1 succeeded
        mock_gj.assert_called_once()  # 6: no unnecessary retry
        self.assertEqual(result, maria_profile)

        # 7-8: what recruitment_pipeline.py's own guard would do with
        # this result -- mirrored here read-only, not re-imported, to
        # confirm the guard now passes instead of raising.
        guard_would_fail = (
            not any(key in result for key in DEFAULT_PROFILE)
            or "error" in result
        )
        self.assertFalse(guard_would_fail)  # 8: guard does NOT raise
        # 9/10: a real pipeline run would now set application.ai_profile
        # to this real, non-empty dict instead of leaving it at {}.

    def test_empty_array_response_exhausts_retries_and_returns_falsy(self):
        with patch(
            "ai_engine.services.llm_candidate_profile.generate_json",
            return_value=[],
        ) as mock_gj:
            result = analyze_cv("some cv text")

        self.assertEqual(mock_gj.call_count, 3)  # retried MAX_ATTEMPTS times
        self.assertEqual(result, [])  # not silently treated as success

    def test_multi_object_array_exhausts_retries_no_silent_pick(self):
        with patch(
            "ai_engine.services.llm_candidate_profile.generate_json",
            return_value=[{"education": "Bachelor"}, {"education": "Master"}],
        ) as mock_gj:
            result = analyze_cv("some cv text")

        self.assertEqual(mock_gj.call_count, 3)
        self.assertEqual(result, [{"education": "Bachelor"}, {"education": "Master"}])

    def test_invalid_json_still_uses_existing_retry_error_path(self):
        # generate_json() itself swallows JSON errors and returns
        # default/{} -- this test confirms that existing contract is
        # untouched by the normalization change.
        with patch(
            "ai_engine.services.llm_candidate_profile.generate_json",
            return_value={},
        ) as mock_gj:
            result = analyze_cv("some cv text")

        self.assertEqual(mock_gj.call_count, 3)
        self.assertEqual(result, {})