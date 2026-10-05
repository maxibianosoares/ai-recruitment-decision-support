"""
FINAL FINISHING SESSION (2026-10-04) -- regression tests for:

  1. The fused-reasoning reliability fix (Section H/G): a malformed/
     empty LLM response must raise -> ai_status="FAILED", never a
     fake score=0/"Consider" success.
  2. The Tetum translation SHA-256 cache (Section J): same input text
     -> cache hit, no second LLM call; failed translation -> never
     cached; changed text -> cache miss.

All LLM calls are mocked (no real Ollama/online_gemma network access
needed) -- run with:

    python manage.py test ai_engine.test_apply_job_optimization -v 2
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from talent.models import Job, Candidate, Application
from ai_engine.services.recruitment_pipeline import recruitment_pipeline
from ai_engine.services import recruitment_pipeline as pipeline_module


_counter = {"n": 0}


def _make_application(cv_text="Experienced ICT officer. Skills: Networking."):

    _counter["n"] += 1

    job = Job.objects.create(
        title="ICT Officer", department="ICT",
        description="x", requirements="x",
        ai_job_profile={
            "job_title": "ICT Officer", "education": "Bachelor",
            "years_experience": 0, "languages": [],
            "certifications": [], "skills": []
        },
        ai_rag_context={
            "evidence": [], "best_evidence_score": 0,
            "grounded": False, "error": None
        }
    )

    candidate = Candidate.objects.create(
        full_name="Test Candidate",
        email=f"testcand{_counter['n']}@x.com",
        extracted_text=cv_text,
    )

    return Application.objects.create(candidate=candidate, job=job)


class FusedReasoningReliabilityTests(TestCase):
    """Section H/G: malformed/empty fused reasoning -> FAILED, not a
    fake deterministic success."""

    def setUp(self):
        cache.clear()

    @patch("ai_engine.services.recruitment_pipeline.detect_language")
    @patch("ai_engine.services.recruitment_pipeline.evaluate_recruitment_rules")
    @patch("ai_engine.services.recruitment_pipeline.skill_gap_analysis")
    @patch("ai_engine.services.recruitment_pipeline.analyze_cv")
    @patch("ai_engine.services.recruitment_pipeline.generate_recruitment_assessment")
    def test_malformed_fused_reasoning_marks_application_failed(
        self, mock_assessment, mock_analyze_cv, mock_skill_gap,
        mock_rules, mock_lang
    ):
        mock_lang.return_value = {"tetum_significant": False}

        mock_analyze_cv.return_value = {
            "education": "Bachelor", "skills": ["Networking"],
            "languages": [], "certifications": [], "years_experience": 3,
            "professional_summary": "x"
        }

        mock_rules.return_value = {"eligible": True, "matrix": []}
        mock_skill_gap.return_value = {"match_score": 50}

        # Same shape generate_recruitment_assessment() itself returns
        # from its except-block on malformed/empty LLM JSON (see
        # llm_reasoning.py) -- decision="" and the exact
        # "Reasoning unavailable:" prefix this fix detects.
        mock_assessment.return_value = {
            "dimension_scores": {
                "education": 0, "experience": 0, "technical_skills": 0,
                "soft_skills": 0, "certifications": 0, "languages": 0
            },
            "overall_score": 0,
            "strengths": [], "weaknesses": [],
            "decision": "", "confidence": 0,
            "reasoning": [], "risks": [],
            "recommendation": "Reasoning unavailable: Empty response from Ollama.",
        }

        application = _make_application()

        with self.assertRaises(ValueError):
            recruitment_pipeline(application)

        application.refresh_from_db()

        self.assertEqual(application.ai_status, "FAILED")
        # Never a fake deterministic decision.
        self.assertEqual(application.ai_score, 0)
        self.assertNotEqual(application.ai_decision, "Not Recommended")
        self.assertIn("Reasoning unavailable", application.ai_feedback)

    @patch("ai_engine.services.recruitment_pipeline.detect_language")
    @patch("ai_engine.services.recruitment_pipeline.evaluate_recruitment_rules")
    @patch("ai_engine.services.recruitment_pipeline.skill_gap_analysis")
    @patch("ai_engine.services.recruitment_pipeline.analyze_cv")
    @patch("ai_engine.services.recruitment_pipeline.generate_recruitment_assessment")
    def test_valid_fused_reasoning_still_succeeds(
        self, mock_assessment, mock_analyze_cv, mock_skill_gap,
        mock_rules, mock_lang
    ):
        """Regression guard: the fix must not reject a NORMAL valid
        result (empty decision only matters together with the
        specific 'Reasoning unavailable:' prefix)."""

        mock_lang.return_value = {"tetum_significant": False}

        mock_analyze_cv.return_value = {
            "education": "Bachelor", "skills": ["Networking"],
            "languages": [], "certifications": [], "years_experience": 3,
            "professional_summary": "x"
        }

        mock_rules.return_value = {"eligible": True, "matrix": []}
        mock_skill_gap.return_value = {"match_score": 50}

        mock_assessment.return_value = {
            "dimension_scores": {
                "education": 80, "experience": 70, "technical_skills": 60,
                "soft_skills": 50, "certifications": 0, "languages": 0
            },
            "overall_score": 65,
            "strengths": ["Good networking skills"], "weaknesses": [],
            "decision": "Recommended", "confidence": 80,
            "reasoning": ["Matches core requirements"], "risks": [],
            "recommendation": "Proceed to interview.",
        }

        application = _make_application()

        result = recruitment_pipeline(application)

        self.assertEqual(result.ai_status, "SUCCESS")
        self.assertEqual(result.ai_decision, "Recommended")


class TetumTranslationCacheTests(TestCase):
    """Section J: SHA-256 cache for successful Tetum translations."""

    def setUp(self):
        cache.clear()

    def test_cache_key_is_empty_before_any_translation(self):

        cv_text = "Tetum CV text, unique for this test, long enough."

        key = pipeline_module._tetum_translation_cache_key(cv_text)
        self.assertIsNone(cache.get(key))

    @patch("ai_engine.services.recruitment_pipeline.detect_language")
    @patch("ai_engine.services.recruitment_pipeline.evaluate_recruitment_rules")
    @patch("ai_engine.services.recruitment_pipeline.skill_gap_analysis")
    @patch("ai_engine.services.recruitment_pipeline.analyze_cv")
    @patch("ai_engine.services.recruitment_pipeline.generate_recruitment_assessment")
    @patch("ai_engine.services.recruitment_pipeline.translate_tetum_to_english")
    def test_identical_text_is_cache_hit_second_time(
        self, mock_translate, mock_assessment, mock_analyze_cv,
        mock_skill_gap, mock_rules, mock_lang
    ):
        mock_lang.return_value = {"tetum_significant": True}
        mock_translate.return_value = {
            "success": True,
            "translated_text": "Translated CV text, long enough to pass.",
            "error": None,
        }
        mock_analyze_cv.return_value = {
            "education": "Bachelor", "skills": ["Networking"],
            "languages": [], "certifications": [], "years_experience": 3,
            "professional_summary": "x"
        }
        mock_rules.return_value = {"eligible": True, "matrix": []}
        mock_skill_gap.return_value = {"match_score": 50}
        mock_assessment.return_value = {
            "dimension_scores": {
                "education": 80, "experience": 70, "technical_skills": 60,
                "soft_skills": 50, "certifications": 0, "languages": 0
            },
            "overall_score": 65, "strengths": [], "weaknesses": [],
            "decision": "Recommended", "confidence": 80,
            "reasoning": [], "risks": [], "recommendation": "ok",
        }

        shared_cv_text = "Tetum CV text shared between two applications."

        app1 = _make_application(cv_text=shared_cv_text)
        app2 = _make_application(cv_text=shared_cv_text)

        recruitment_pipeline(app1)
        self.assertEqual(mock_translate.call_count, 1)

        recruitment_pipeline(app2)
        # Second application, SAME cv_text -> cache hit, no second
        # translate_tetum_to_english() call.
        self.assertEqual(mock_translate.call_count, 1)

    @patch("ai_engine.services.recruitment_pipeline.detect_language")
    @patch("ai_engine.services.recruitment_pipeline.evaluate_recruitment_rules")
    @patch("ai_engine.services.recruitment_pipeline.skill_gap_analysis")
    @patch("ai_engine.services.recruitment_pipeline.analyze_cv")
    @patch("ai_engine.services.recruitment_pipeline.generate_recruitment_assessment")
    @patch("ai_engine.services.recruitment_pipeline.translate_tetum_to_english")
    def test_failed_translation_is_not_cached(
        self, mock_translate, mock_assessment, mock_analyze_cv,
        mock_skill_gap, mock_rules, mock_lang
    ):
        mock_lang.return_value = {"tetum_significant": True}

        # translate_tetum_to_english() never raises -- a failure is a
        # dict with success=False and the ORIGINAL text (see
        # translation.py).
        failing_cv_text = "Tetum CV text that fails translation, long."
        mock_translate.return_value = {
            "success": False,
            "translated_text": failing_cv_text,
            "error": "Translation returned empty or invalid result.",
        }
        mock_analyze_cv.return_value = {
            "education": "Bachelor", "skills": ["Networking"],
            "languages": [], "certifications": [], "years_experience": 3,
            "professional_summary": "x"
        }
        mock_rules.return_value = {"eligible": True, "matrix": []}
        mock_skill_gap.return_value = {"match_score": 50}
        mock_assessment.return_value = {
            "dimension_scores": {
                "education": 80, "experience": 70, "technical_skills": 60,
                "soft_skills": 50, "certifications": 0, "languages": 0
            },
            "overall_score": 65, "strengths": [], "weaknesses": [],
            "decision": "Recommended", "confidence": 80,
            "reasoning": [], "risks": [], "recommendation": "ok",
        }

        app1 = _make_application(cv_text=failing_cv_text)
        app2 = _make_application(cv_text=failing_cv_text)

        recruitment_pipeline(app1)
        recruitment_pipeline(app2)

        # A FAILED translation must be retried for real every time,
        # never cached/"stuck".
        self.assertEqual(mock_translate.call_count, 2)

    @patch("ai_engine.services.recruitment_pipeline.detect_language")
    @patch("ai_engine.services.recruitment_pipeline.evaluate_recruitment_rules")
    @patch("ai_engine.services.recruitment_pipeline.skill_gap_analysis")
    @patch("ai_engine.services.recruitment_pipeline.analyze_cv")
    @patch("ai_engine.services.recruitment_pipeline.generate_recruitment_assessment")
    @patch("ai_engine.services.recruitment_pipeline.translate_tetum_to_english")
    def test_changed_text_is_cache_miss(
        self, mock_translate, mock_assessment, mock_analyze_cv,
        mock_skill_gap, mock_rules, mock_lang
    ):
        mock_lang.return_value = {"tetum_significant": True}
        mock_translate.return_value = {
            "success": True,
            "translated_text": "Translated text, long enough to pass.",
            "error": None,
        }
        mock_analyze_cv.return_value = {
            "education": "Bachelor", "skills": ["Networking"],
            "languages": [], "certifications": [], "years_experience": 3,
            "professional_summary": "x"
        }
        mock_rules.return_value = {"eligible": True, "matrix": []}
        mock_skill_gap.return_value = {"match_score": 50}
        mock_assessment.return_value = {
            "dimension_scores": {
                "education": 80, "experience": 70, "technical_skills": 60,
                "soft_skills": 50, "certifications": 0, "languages": 0
            },
            "overall_score": 65, "strengths": [], "weaknesses": [],
            "decision": "Recommended", "confidence": 80,
            "reasoning": [], "risks": [], "recommendation": "ok",
        }

        app1 = _make_application(cv_text="Tetum CV text, version A, long enough.")
        app2 = _make_application(cv_text="Tetum CV text, version B, different.")

        recruitment_pipeline(app1)
        recruitment_pipeline(app2)

        # Different input text -> cache miss -> called twice.
        self.assertEqual(mock_translate.call_count, 2)