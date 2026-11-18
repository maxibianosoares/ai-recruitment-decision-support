import glob
import unittest
from pathlib import Path

from rag import claim_guards as g

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "knowledge_base" / "documents_staging" / "hngv_2026"


class Temporal(unittest.TestCase):
    def test_substrings_are_not_current(self):
        for q in ["At which stage must the medical certificate be presented in CPI/2/2026?",
                  "Is the data known to the board?", "Snow day?", "Who is reserving seats?"]:
            self.assertFalse(g.is_current_claim(q), q)

    def test_real_current_questions(self):
        for q in ["Are applications still open today?", "Who is the current President?",
                  "What is the salary now?", "Who is presently serving?",
                  "Is the suspension still in force?"]:
            self.assertTrue(g.is_current_claim(q), q)

    def test_historical_evidence_blocks_only_current_claims(self):
        ev = "Published in the Jornal da República."
        self.assertTrue(g.temporal_guard("Who is the current minister?", ev)["blocked"])
        self.assertFalse(g.temporal_guard("Who signed the decree?", ev)["blocked"])


class Identifier(unittest.TestCase):
    def test_missing_vacancy_code_blocks(self):
        r = g.identifier_guard("How many positions does CPI/3/2026 offer?",
                               "Vacancy CPI/1/2026 offers 112 positions.")
        self.assertTrue(r["blocked"])
        self.assertIn("CPI/3/2026", r["reason"])

    def test_present_code_passes(self):
        self.assertFalse(g.identifier_guard("Salary of CPI/1/2026?", "cpi/1/2026 pays 610")["blocked"])

    def test_bare_law_number_not_required(self):
        self.assertFalse(g.identifier_guard("Under Decree-Law 34/2008, is 60 a fail?",
                                            "Candidates below 60 points are not approved.")["blocked"])


class Rank(unittest.TestCase):
    def test_senior_not_in_junior_evidence(self):
        self.assertTrue(g.rank_guard("Salary of a Senior General Doctor?",
                                     "Junior 1 category: USD 610")["blocked"])

    def test_same_rank_passes(self):
        self.assertFalse(g.rank_guard("Salary of a Junior doctor?", "Junior 1 category: USD 610")["blocked"])

    def test_no_rank_word_no_block(self):
        self.assertFalse(g.rank_guard("Salary of a doctor?", "Junior 1 category: USD 610")["blocked"])

    def test_accent_insensitive(self):
        self.assertFalse(g.rank_guard("Salary of a senior doctor?", "Médico Sénior: 900")["blocked"])


class RunGuards(unittest.TestCase):
    def test_first_blocking_guard_named(self):
        r = g.run_guards("How many positions does CPI/3/2026 offer?", "CPI/1/2026: 112")
        self.assertEqual(r["guard"], "identifier")
        self.assertEqual(g.run_guards("Any question", "any evidence")["guard"], "")


class Scoping(unittest.TestCase):
    R = [{"text": "Vacancy CPI/1/2026 medical x", "score": .8},
         {"text": "CPI/2/2026 medical certificate at interview", "score": .79},
         {"text": "Vacancy CPI/7/2026 y", "score": .78}]

    def test_keeps_only_named_vacancy(self):
        out = g.scope_results("medical certificate in CPI/2/2026?", self.R)
        self.assertEqual(len(out), 1)
        self.assertIn("CPI/2/2026", out[0]["text"])

    def test_no_code_unchanged(self):
        self.assertEqual(g.scope_results("medical certificate?", self.R), self.R)

    def test_unknown_code_unchanged_so_guard_decides(self):
        self.assertEqual(g.scope_results("positions in CPI/3/2026?", self.R), self.R)

    def test_retrieve_scoped_widens_search(self):
        calls = []
        def search(q, top_k):
            calls.append(top_k)
            return self.R
        out = g.retrieve_scoped("CPI/2/2026 medical?", search, top_k=3)
        self.assertEqual(calls, [10])
        self.assertEqual(len(out), 1)
        calls.clear()
        g.retrieve_scoped("no code here", search, top_k=3)
        self.assertEqual(calls, [3])


@unittest.skipUnless(STAGING.exists(), "staged HNGV corpus not present")
class OnRealCorpus(unittest.TestCase):
    def _text(self, pat):
        return Path(glob.glob(str(STAGING / pat))[0]).read_text(encoding="utf-8")

    def test_hd15_no_longer_blocked(self):
        q = "At which stage must the medical certificate be presented in vacancy CPI/2/2026?"
        self.assertFalse(g.run_guards(q, self._text("hngv_2026_cpi_2_*.md"))["blocked"])

    def test_hu05_senior_blocked_on_junior_only_corpus(self):
        q = "What is the monthly salary of a Senior General Doctor at HNGV?"
        self.assertTrue(g.run_guards(q, self._text("hngv_2026_cpi_1_*.md"))["blocked"])


if __name__ == "__main__":
    unittest.main()
