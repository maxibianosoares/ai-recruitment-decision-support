"""
Online Gemma reliability fix (2026-10-02) -- regression tests for the
root causes diagnosed from the real Railway HTTP 500 incident:

  1. call_online_gemma() used to discard the response BODY on any
     HTTP failure, keeping only the status code -- every failure
     printed identically regardless of the real reason.
  2. analyze_cv()'s 3-attempt retry loop had zero delay between
     attempts and treated every failure (401 bad key, 500 server
     error, timeout, ...) the same way -- always retrying blindly.

All HTTP calls here are mocked (monkeypatched requests.post / the
online-Gemma call itself) -- no real network access, no API quota
spent, and no dependency on Ollama running. Run with:

    python manage.py test ai_engine.test_online_gemma_reliability -v 2
"""

import time
from unittest.mock import patch, MagicMock

from django.test import TestCase

from ai_engine.services.model_config import call_online_gemma, OnlineGemmaError
from ai_engine.services import llm_candidate_profile
from ai_engine.services.llm_candidate_profile import analyze_cv, DEFAULT_PROFILE


def _mock_response(status_code, body_json=None, body_text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = body_text or (str(body_json) if body_json is not None else "")
    if body_json is not None:
        resp.json.return_value = body_json
    if status_code >= 400:
        import requests
        http_error = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = http_error
    else:
        resp.raise_for_status.return_value = None
    return resp


def _gemma_ok_body(text='{"education": "Bachelor of IT"}'):
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}}
        ]
    }


class CallOnlineGemmaErrorHandlingTests(TestCase):
    """STEP 2 -- real response body surfaced, never the API key."""

    def setUp(self):
        patcher = patch(
            "ai_engine.services.model_config.ONLINE_GEMMA_API_KEY",
            "fake-key-for-tests-only"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("ai_engine.services.model_config.requests.post")
    def test_valid_request_returns_text(self, mock_post):
        mock_post.return_value = _mock_response(
            200, _gemma_ok_body()
        )
        result = call_online_gemma("prompt", want_json=True)
        self.assertIn("Bachelor of IT", result)

    @patch("ai_engine.services.model_config.requests.post")
    def test_http_500_surfaces_response_body(self, mock_post):
        mock_post.return_value = _mock_response(
            500, body_text='{"error": {"message": "internal error XYZ"}}'
        )
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertIn("internal error XYZ", str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertTrue(ctx.exception.is_transient)

    @patch("ai_engine.services.model_config.requests.post")
    def test_http_429_is_transient(self, mock_post):
        mock_post.return_value = _mock_response(
            429, body_text='{"error": "rate limited"}'
        )
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertTrue(ctx.exception.is_transient)
        self.assertEqual(ctx.exception.status_code, 429)

    @patch("ai_engine.services.model_config.requests.post")
    def test_http_401_is_permanent(self, mock_post):
        mock_post.return_value = _mock_response(
            401, body_text='{"error": "invalid API key"}'
        )
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertFalse(ctx.exception.is_transient)
        self.assertEqual(ctx.exception.status_code, 401)

    @patch("ai_engine.services.model_config.requests.post")
    def test_http_404_unknown_model_is_permanent(self, mock_post):
        mock_post.return_value = _mock_response(
            404, body_text='{"error": "model not found"}'
        )
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertFalse(ctx.exception.is_transient)

    @patch("ai_engine.services.model_config.requests.post")
    def test_timeout_is_transient(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.Timeout("read timed out")
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertTrue(ctx.exception.is_transient)
        self.assertIsNone(ctx.exception.status_code)

    @patch("ai_engine.services.model_config.requests.post")
    def test_connection_error_is_transient(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertTrue(ctx.exception.is_transient)

    @patch("ai_engine.services.model_config.requests.post")
    def test_error_never_logs_full_api_key(self, mock_post):
        mock_post.return_value = _mock_response(500, body_text="server error")
        with self.assertRaises(OnlineGemmaError) as ctx:
            call_online_gemma("prompt")
        self.assertNotIn("fake-key-for-tests-only", str(ctx.exception))

    @patch("ai_engine.services.model_config.requests.post")
    def test_thought_parts_are_skipped(self, mock_post):
        body = {
            "candidates": [{
                "content": {"parts": [
                    {"text": "", "thought": True},
                    {"text": '{"education": "Bachelor"}'}
                ]}
            }]
        }
        mock_post.return_value = _mock_response(200, body)
        result = call_online_gemma("prompt", want_json=True)
        self.assertEqual(result, '{"education": "Bachelor"}')


class AnalyzeCvRetryTests(TestCase):
    """STEP 3 -- backoff between attempts, fail fast on permanent errors,
    never a fake/empty profile presented as success."""

    def setUp(self):
        # Keep tests fast -- patch the sleep so backoff logic still
        # RUNS (proving it's called the right number of times) but
        # doesn't actually slow the test suite down.
        patcher = patch("ai_engine.services.llm_candidate_profile.time.sleep")
        self.mock_sleep = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_success_on_first_attempt_no_retry(self, mock_gen):
        mock_gen.return_value = {
            "education": "Bachelor of IT", "skills": ["Python"],
            "languages": [], "certifications": [],
            "years_experience": 2, "professional_summary": ""
        }
        result = analyze_cv("some cv text")
        self.assertEqual(mock_gen.call_count, 1)
        self.assertEqual(result["education"], "Bachelor of IT")
        self.mock_sleep.assert_not_called()

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_transient_error_retries_with_backoff_then_succeeds(self, mock_gen):
        transient = OnlineGemmaError(
            "Online Gemma request failed (HTTP 500): server busy",
            status_code=500, is_transient=True
        )
        mock_gen.side_effect = [
            transient,
            {
                "education": "Bachelor of IT", "skills": [],
                "languages": [], "certifications": [],
                "years_experience": 1, "professional_summary": ""
            }
        ]
        result = analyze_cv("some cv text")
        self.assertEqual(mock_gen.call_count, 2)
        self.assertEqual(result["education"], "Bachelor of IT")
        # One backoff wait happened between attempt 1 and attempt 2.
        self.mock_sleep.assert_called()

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_permanent_error_fails_fast_no_wasted_attempts(self, mock_gen):
        permanent = OnlineGemmaError(
            "Online Gemma request failed (HTTP 401): invalid API key",
            status_code=401, is_transient=False
        )
        mock_gen.side_effect = permanent
        result = analyze_cv("some cv text")
        # Must stop after the FIRST attempt -- not burn all 3 on a
        # request that can never succeed.
        self.assertEqual(mock_gen.call_count, 1)
        self.assertEqual(result.get("error"), str(permanent))

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_transient_error_exhausts_all_attempts_then_fails_honestly(self, mock_gen):
        transient = OnlineGemmaError(
            "Online Gemma request failed (HTTP 503): overloaded",
            status_code=503, is_transient=True
        )
        mock_gen.side_effect = [transient, transient, transient]
        result = analyze_cv("some cv text")
        self.assertEqual(mock_gen.call_count, 3)
        # Must carry an "error" key -- this is what
        # recruitment_pipeline.py's guard checks to raise instead of
        # silently treating this as a real (empty) profile.
        self.assertIn("error", result)
        self.assertEqual(result["education"], "")
        self.assertEqual(result["years_experience"], 0)

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_empty_dict_result_without_exception_still_retries(self, mock_gen):
        # The known gemma early-stop bug: generate_json returns {}
        # with NO exception at all (raw_response was "").
        mock_gen.side_effect = [
            {},
            {
                "education": "Bachelor", "skills": [], "languages": [],
                "certifications": [], "years_experience": 0,
                "professional_summary": ""
            }
        ]
        result = analyze_cv("some cv text")
        self.assertEqual(mock_gen.call_count, 2)
        self.assertEqual(result["education"], "Bachelor")

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_malformed_json_error_is_treated_as_transient_and_retried(self, mock_gen):
        # json.loads() failures inside generate_json() have no
        # .is_transient attribute at all -- must default to True
        # (retry), not crash analyze_cv with an AttributeError.
        bad_json_error = ValueError("Expecting value: line 1 column 1")
        mock_gen.side_effect = [
            bad_json_error,
            {
                "education": "Bachelor", "skills": [], "languages": [],
                "certifications": [], "years_experience": 0,
                "professional_summary": ""
            }
        ]
        result = analyze_cv("some cv text")
        self.assertEqual(mock_gen.call_count, 2)
        self.assertEqual(result["education"], "Bachelor")

    @patch("ai_engine.services.llm_candidate_profile.generate_json")
    def test_never_returns_fake_success_shape_on_total_failure(self, mock_gen):
        """
        STEP 8 guard (not modified, but must still hold): a total
        failure must produce a dict carrying "error", never a dict
        that looks like a normal-but-sparse real profile -- that
        distinction is what recruitment_pipeline.py's existing check
        (`"error" in profile`) relies on to avoid saving a fake
        Candidate Profile.
        """
        permanent = OnlineGemmaError("boom", status_code=403, is_transient=False)
        mock_gen.side_effect = permanent
        result = analyze_cv("some cv text")
        self.assertIn("error", result)
        for key in DEFAULT_PROFILE:
            self.assertIn(key, result)