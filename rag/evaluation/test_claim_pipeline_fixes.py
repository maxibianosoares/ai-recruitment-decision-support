"""Offline tests for decomposition clean-up, partial aggregation, and evaluate() wiring.
No faiss / LLM needed: retriever and generate_json are replaced by fakes."""
import importlib
import os
import sys
import types
import unittest
from unittest import mock

from rag import claim_guards as g


def C(*texts):
    return [{"id": f"C{i}", "text": t} for i, t in enumerate(texts, 1)]


class CleanClaims(unittest.TestCase):
    def test_trailing_location_fragment_is_merged(self):
        out = g.clean_claims(C("What are the ages for CPI/1/2026 (General Doctor)?", "at HNGV"),
                             "What are the ages for CPI/1/2026 (General Doctor) at HNGV?")
        self.assertEqual(len(out), 1)
        self.assertIn("CPI/1/2026", out[0]["text"])
        self.assertIn("at HNGV", out[0]["text"])

    def test_leading_to_fragment_keeps_vacancy_code(self):
        out = g.clean_claims(C("On what date is age measured?",
                               "To check the 20 to 55 limit in vacancy CPI/1/2026?"), "q")
        self.assertEqual(len(out), 1)
        self.assertIn("CPI/1/2026", out[0]["text"])

    def test_two_real_claims_untouched(self):
        out = g.clean_claims(C("Can AI rank candidates?", "Can AI determine a candidate's salary?"), "q")
        self.assertEqual([c["id"] for c in out], ["C1", "C2"])
        self.assertEqual(len(out), 2)

    def test_lost_rank_qualifier_is_restored(self):
        out = g.clean_claims(C("What is the monthly salary of a General Doctor?"),
                             "What is the monthly salary of a Senior General Doctor at HNGV?")
        self.assertIn("senior", out[0]["text"].lower())
        # ... so the rank guard can now block it on junior-only evidence
        self.assertTrue(g.rank_guard(out[0]["text"], "Junior 1 category: USD 610")["blocked"])

    def test_present_qualifier_is_not_added_again(self):
        q = "What is the monthly salary of a Senior General Doctor at HNGV?"
        self.assertEqual(g.clean_claims(C(q), q)[0]["text"], q)

    def test_lost_vacancy_code_is_restored(self):
        out = g.clean_claims(C("How many positions are offered?"),
                             "How many positions does vacancy CPI/3/2026 offer?")
        self.assertIn("CPI/3/2026", out[0]["text"].upper())

    def test_empty_input_falls_back_to_question(self):
        self.assertEqual(g.clean_claims([], "Why?")[0]["text"], "Why?")

    def test_prepositional_question_is_not_a_fragment(self):
        out = g.clean_claims(C("Is a medical certificate required?",
                               "At which stage must the medical certificate be presented?",
                               "For how long is the certificate valid?"), "q")
        self.assertEqual(len(out), 3)

    def test_fragment_as_first_claim_is_kept(self):
        self.assertEqual(len(g.clean_claims(C("at HNGV"), "q")), 1)


class Aggregate(unittest.TestCase):
    def test_all_full(self):
        r = g.aggregate_status([{"supported": True}, {"supported": True}])
        self.assertEqual((r["status"], r["coverage"]), ("supported", 1.0))

    def test_none(self):
        self.assertEqual(g.aggregate_status([{"supported": False}])["status"], "unsupported")

    def test_mixed_full_and_none_is_partial_as_before(self):
        r = g.aggregate_status([{"supported": True}, {"supported": False}])
        self.assertEqual((r["status"], r["coverage"]), ("partially_supported", 0.5))

    def test_single_partial_claim_is_partial(self):
        r = g.aggregate_status([{"supported": False, "partial": True}])
        self.assertEqual((r["status"], r["coverage"]), ("partially_supported", 0.5))

    def test_partial_flag_ignored_when_supported(self):
        self.assertEqual(g.aggregate_status([{"supported": True, "partial": True}])["status"], "supported")


def load_coverage(llm_reply, chunks):
    fake_ret = types.ModuleType("rag.retriever")
    fake_ret.retriever = types.SimpleNamespace(search=lambda q, top_k=3: chunks[:top_k])
    fake_llm = types.ModuleType("ai_engine.services.local_llm")
    fake_llm.generate_json = lambda prompt, default=None: dict(llm_reply)
    with mock.patch.dict(sys.modules, {"rag.retriever": fake_ret,
                                       "ai_engine.services.local_llm": fake_llm}):
        sys.modules.pop("rag.evidence_coverage", None)
        mod = importlib.import_module("rag.evidence_coverage")
    return mod.EvidenceCoverage()


CH = [{"text": "Vacancy CPI/1/2026 pays Junior 1 USD 610.", "score": 0.8, "source": "a.md"}]


class EvaluateWiring(unittest.TestCase):
    def setUp(self):
        os.environ.pop("RAG_PARTIAL_CLAIMS", None)

    def test_rank_guard_blocks_before_llm(self):
        ec = load_coverage({"supported": True, "reason": "x"}, CH)
        r = ec.evaluate(C("Salary of a Senior General Doctor?"))
        self.assertEqual(r["status"], "unsupported")
        self.assertEqual(r["claims"][0]["guard"], "rank")

    def test_supported_when_llm_says_yes(self):
        ec = load_coverage({"supported": True, "reason": "x"}, CH)
        self.assertEqual(ec.evaluate(C("Salary for CPI/1/2026?"))["status"], "supported")

    def test_partial_verdict_ignored_when_flag_off(self):
        ec = load_coverage({"supported": False, "partial": True, "reason": "x"}, CH)
        self.assertEqual(ec.evaluate(C("Salary for CPI/1/2026?"))["status"], "unsupported")

    def test_partial_verdict_used_when_flag_on(self):
        ec = load_coverage({"supported": False, "partial": True, "reason": "x"}, CH)
        with mock.patch.dict(os.environ, {"RAG_PARTIAL_CLAIMS": "1"}):
            r = ec.evaluate(C("Salary for CPI/1/2026?"))
        self.assertEqual((r["status"], r["coverage"]), ("partially_supported", 0.5))

    def test_verification_error_flag_propagates(self):
        ec = load_coverage({"supported": False, "reason": "failed", "verification_error": True}, CH)
        self.assertTrue(ec.evaluate(C("Salary for CPI/1/2026?"))["claims"][0]["verification_error"])

    def test_prompt_has_no_doubled_braces(self):
        seen = {}
        fake_ret = types.ModuleType("rag.retriever")
        fake_ret.retriever = types.SimpleNamespace(search=lambda q, top_k=3: CH)
        fake_llm = types.ModuleType("ai_engine.services.local_llm")
        def gj(prompt, default=None):
            seen["p"] = prompt
            return {"supported": True}
        fake_llm.generate_json = gj
        with mock.patch.dict(sys.modules, {"rag.retriever": fake_ret,
                                           "ai_engine.services.local_llm": fake_llm}):
            sys.modules.pop("rag.evidence_coverage", None)
            ec = importlib.import_module("rag.evidence_coverage").EvidenceCoverage()
            with mock.patch.dict(os.environ, {"RAG_PARTIAL_CLAIMS": "1"}):
                ec.verify_claim("Salary for CPI/1/2026?", CH[0]["text"])
        self.assertIn('{"supported": true, "partial": false, "reason": ""}', seen["p"])
        self.assertNotIn("{{", seen["p"])


class OllamaEnv(unittest.TestCase):
    def test_seed_and_temperature_go_into_payload(self):
        fake_cfg = types.ModuleType("ai_engine.services.model_config")
        fake_cfg.MODEL_NAME = "m"; fake_cfg.OLLAMA_BASE_URL = "http://x"
        fake_cfg.OLLAMA_TIMEOUT_SECONDS = 5; fake_cfg.LLM_PROVIDER = "ollama"
        fake_cfg.call_online_gemma = None
        sent = {}
        class R:
            def raise_for_status(self): pass
            def json(self): return {"response": "{}"}
        with mock.patch.dict(sys.modules, {"ai_engine.services.model_config": fake_cfg}):
            sys.modules.pop("ai_engine.services.ollama_llm", None)
            mod = importlib.import_module("ai_engine.services.ollama_llm")
            mod._session = types.SimpleNamespace(
                post=lambda url, json=None, timeout=None: (sent.update(json), R())[1])
            with mock.patch.dict(os.environ, {"LLM_SEED": "42", "LLM_TEMPERATURE": "0"}):
                mod.generate("hi")
            self.assertEqual(sent["options"], {"temperature": 0.0, "seed": 42})
            sent.clear()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LLM_SEED", None); os.environ.pop("LLM_TEMPERATURE", None)
                mod.generate("hi")
            self.assertEqual(sent["options"], {"temperature": 0.1})
        sys.modules.pop("ai_engine.services.ollama_llm", None)


if __name__ == "__main__":
    unittest.main()
