"""
Flexibility tests: the rule engine, corpus builder and question generator
must work for ANY rule pack, not only the HNGV one, and must be opt-in.

    python -m unittest rag.evaluation.test_vacancy_flexibility -v

Uses a small FICTIONAL pack (ministry clerk, different thresholds, several
rules omitted) written to a temp folder. No model, network or real data.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ai_engine.services import vacancy_rules_engine as eng
from rag import build_vacancy_corpus as bvc
from rag.evaluation import generate_vacancy_questions as gvq

ROOT = Path(__file__).resolve().parents[2]
HNGV_PACK = ROOT / "knowledge_base" / "vacancy_rules" / "hngv_2026_vacancy_rules.json"

CUSTOM = {
    "dataset": "fictional_clerk_pack", "version": "0.0.1",
    "status": "UNVERIFIED: fictional test pack", "contains_personal_data": False,
    "institution_label": "the Fictional Ministry of Testing",
    "rules": [{"id": "R02", "summary": "age", "type": "code", "gap": "none"}],
    "corpus_notes": ["Vacancy {code} is a clerical post in {field}."],
    "vacancies": [
        {"code": "FIC/1/2027", "job_title": "Clerk", "positions": 7, "salary_usd": 300,
         "source_file": "fictional.pdf", "verification": {"status": "human_verified"},
         "requirements": {
             "R02": {"min_age": 18, "max_age": 40, "default_reference_date": "2027-03-01"},
             "R04": {"min_months": 6, "field": "administration"},
             "R11": {"written_min_score": 50, "scale_max": 100},
         }},
        {"code": "FIC/2/2027", "job_title": "Archivist", "positions": 2,
         "source_file": "fictional2.pdf", "verification": {"status": "human_verified"},
         "requirements": {"R02": {"min_age": 21, "max_age": 60, "default_reference_date": "2027-03-01"}}},
    ],
}


def write_pack(folder, pack=CUSTOM, name="fictional.json"):
    p = Path(folder) / name
    p.write_text(json.dumps(pack), encoding="utf-8")
    return p


class EngineWithCustomPack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = write_pack(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ev(self, cand, code="FIC/1/2027", **kw):
        return eng.evaluate_vacancy_eligibility(cand, code, rules_path=self.pack, **kw)

    def test_thresholds_come_from_the_pack(self):
        # pure pack thresholds (law layer switched off): 18..40
        def r02(res): return next(r for r in res["rules"] if r["rule_id"] == "R02")["outcome"]
        young = self.ev({"date_of_birth": "2009-06-01"}, law={}, allow_no_law=True)      # 17 on 2027-03-01
        ok = self.ev({"date_of_birth": "2009-03-01"}, law={}, allow_no_law=True)          # exactly 18
        old = self.ev({"date_of_birth": "1986-02-28"}, law={}, allow_no_law=True)         # 41
        self.assertEqual((r02(young), r02(ok), r02(old)), (eng.FAIL, eng.PASS, eng.FAIL))

    def test_with_reference_law_the_pack_cannot_override_it_silently(self):
        # same candidates, default law layer: 17 and 41 are inside the law range 17-55
        # but outside this pack's 18-40 -> REVIEW, never an automatic FAIL
        def r02(res): return next(r for r in res["rules"] if r["rule_id"] == "R02")["outcome"]
        self.assertEqual(r02(self.ev({"date_of_birth": "2009-06-01"})), eng.REVIEW)
        self.assertEqual(r02(self.ev({"date_of_birth": "1986-02-28"})), eng.REVIEW)
        self.assertEqual(r02(self.ev({"date_of_birth": "2011-06-01"})), eng.FAIL)   # 15: fails both

    def test_undeclared_rules_are_not_applicable_and_do_not_affect_result(self):
        res = self.ev({"date_of_birth": "2000-01-01"})
        self.assertEqual(set(res["not_applicable_rule_ids"]),
                         {"R01", "R03", "R05", "R06", "R07", "R08", "R09", "R14"})
        self.assertEqual(res["failed_rule_ids"], ["R04"])   # no experience supplied, 6 months declared

    def test_experience_threshold_6_months_without_facility_filter(self):
        hist = [{"start": "2026-01-01", "end": "2026-06-30", "field": "administration", "facility_type": "anything"}]
        res = self.ev({"date_of_birth": "2000-01-01", "work_history": hist})
        self.assertEqual(next(r for r in res["rules"] if r["rule_id"] == "R04")["outcome"], eng.PASS)
        self.assertEqual(res["overall"], "AUTOMATED_CHECKS_PASSED")

    def test_second_vacancy_declares_only_age(self):
        res = self.ev({"date_of_birth": "1990-01-01"}, "FIC/2/2027")
        self.assertEqual(res["overall"], "AUTOMATED_CHECKS_PASSED")
        self.assertEqual(len(res["not_applicable_rule_ids"]), 9)

    def test_stage_rules_tolerate_missing_r12_and_r13(self):
        res = eng.evaluate_stage_progress("FIC/1/2027", document_stage_passed=True, written_score=49.9,
                                          rules_path=self.pack)
        self.assertEqual(res["rules"][-1]["outcome"], eng.FAIL)
        # pack pass mark 50 is below the law's (60 or less disqualified): 50 is a conflict -> REVIEW
        res = eng.evaluate_stage_progress("FIC/1/2027", document_stage_passed=True, written_score=50,
                                          rules_path=self.pack)
        self.assertEqual(res["rules"][-1]["outcome"], eng.REVIEW)
        # 61 passes both readings; the pack has no R12, so the final-score row is NOT_APPLICABLE
        res = eng.evaluate_stage_progress("FIC/1/2027", document_stage_passed=True, written_score=61,
                                          interview_score=10, rules_path=self.pack)
        self.assertEqual(res["rules"][-1]["outcome"], eng.NOT_APPLICABLE)
        with self.assertRaises(ValueError):
            eng.weighted_written_score(50, 50, "FIC/1/2027", self.pack)

    def test_adapter_tolerates_missing_rules(self):
        j = eng.vacancy_to_job_requirement("FIC/2/2027", self.pack)
        self.assertEqual((j["education"], j["years_experience"]), ("", 0))

    def test_unknown_code_and_list(self):
        with self.assertRaises(KeyError):
            eng.get_vacancy("NOPE/1/2027", self.pack)
        self.assertEqual(eng.list_vacancies(self.pack), ["FIC/1/2027", "FIC/2/2027"])

    def test_default_search_finds_all_packs_and_rejects_duplicates(self):
        old = eng.RULES_DIR
        try:
            eng.RULES_DIR = Path(self.tmp.name)
            write_pack(self.tmp.name, name="b.json")           # same codes in a second pack
            with self.assertRaises(ValueError):
                eng.find_vacancy("FIC/1/2027")
            (Path(self.tmp.name) / "b.json").unlink()
            self.assertEqual(eng.find_vacancy("FIC/2/2027")[0]["job_title"], "Archivist")
        finally:
            eng.RULES_DIR = old


class CorpusBuilderOptIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = write_pack(self.tmp.name)
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_selected_raises(self):
        with self.assertRaises(SystemExit):
            bvc.build(self.pack, self.out)

    def test_unknown_code_raises(self):
        with self.assertRaises(SystemExit):
            bvc.build(self.pack, self.out, ["NOPE"])

    def test_only_named_vacancy_written_and_sections_follow_rules(self):
        written = bvc.build(self.pack, self.out, ["FIC/2/2027"], prefix="fic")
        self.assertTrue(any("fic_fic_2_2027" in w for w in written))
        self.assertFalse(any("fic_1_2027" in w for w in written))
        text = next(self.out.glob("*fic_2_2027*.md")).read_text(encoding="utf-8")
        self.assertIn("minimum age is 21", text)
        self.assertNotIn("## Education", text)
        self.assertNotIn("## Experience", text)
        self.assertIn("Fictional Ministry of Testing", text)

    def test_every_content_line_carries_the_code(self):
        bvc.build(self.pack, self.out, all_vacancies=True, prefix="fic")
        for p in self.out.glob("*fic_1_2027*.md"):
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln and not ln.startswith("#"):
                    self.assertIn("FIC/1/2027", ln)


class QuestionGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = write_pack(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_opt_in(self):
        with self.assertRaises(SystemExit):
            gvq.generate(self.pack)
        with self.assertRaises(SystemExit):
            gvq.generate(self.pack, ["NOPE"])

    def test_only_declared_rules_get_questions(self):
        qs = gvq.generate(self.pack, ["FIC/2/2027"])["questions"]
        kinds = {q["id"].rsplit("-", 1)[1] for q in qs}
        # no salary, edu, exp...; no AGEREF because the pack does not say the reference date is unstated
        self.assertEqual(kinds, {"POS", "AGE", "NOCAND"})

    def test_labels_and_categories_valid(self):
        qs = gvq.generate(HNGV_PACK, all_vacancies=True)["questions"]
        ids = [q["id"] for q in qs]
        self.assertEqual(len(ids), len(set(ids)))
        valid = {"gen_direct": {"supported"}, "gen_partial": {"partially_supported"},
                 "gen_unsupported": {"unsupported"}}
        for q in qs:
            self.assertIn(q["expected"], valid[q["category"]], q["id"])
            self.assertIsNone(q["labeler_2"])

    def _check_needles(self, pack_path, codes=None, all_v=False):
        out = Path(self.tmp.name) / "corpus"
        bvc.build(pack_path, out, codes, "t", all_v)
        text = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.md")}
        for q in gvq.generate(pack_path, codes, all_v)["questions"]:
            if q["expected"] != "supported":
                continue
            doc = next(t for n, t in text.items() if q["vacancy"].replace("/", "_").lower() in n)
            for needle in q["needles"]:
                self.assertIn(needle, doc, f"{q['id']}: {needle!r}")

    def test_generated_direct_answers_exist_in_corpus_custom_pack(self):
        self._check_needles(self.pack, all_v=True)

    def test_generated_direct_answers_exist_in_corpus_hngv_pack(self):
        self._check_needles(HNGV_PACK, all_v=True)

    def test_cli_main_writes_json(self):
        out = Path(self.tmp.name) / "q.json"
        gvq.main(["--src", str(self.pack), "--vacancy", "FIC/1/2027", "--out", str(out)])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(doc["questions"] and "no results produced" in doc["status"])


class GeneratedSet(unittest.TestCase):
    def setUp(self):
        import os
        keys = ("BENCHMARK_SET", "BENCHMARK_IDS", "BENCHMARK_TAG", "BENCHMARK_QUESTIONS_FILE")
        self._saved = {k: os.environ.pop(k) for k in keys if k in os.environ}

    def tearDown(self):
        import os
        for k in ("BENCHMARK_SET", "BENCHMARK_IDS", "BENCHMARK_TAG", "BENCHMARK_QUESTIONS_FILE"):
            os.environ.pop(k, None)
        os.environ.update(self._saved)

    def test_generated_set_is_opt_in_and_needs_a_file(self):
        import os
        from rag.evaluation import benchmark_sets as bs
        self.assertIn("generated", bs.RESULT_FILES)
        self.assertNotEqual(bs.RESULT_FILES["generated"], bs.RESULT_FILES["baseline"])
        old = os.environ.pop("BENCHMARK_QUESTIONS_FILE", None)
        try:
            with self.assertRaises(SystemExit):
                bs.load_set("generated")
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "q.json"
                f.write_text(json.dumps({"questions": [{"id": "X"}]}), encoding="utf-8")
                os.environ["BENCHMARK_QUESTIONS_FILE"] = str(f)
                self.assertEqual(bs.load_set("generated"), [{"id": "X"}])
        finally:
            os.environ.pop("BENCHMARK_QUESTIONS_FILE", None)
            if old:
                os.environ["BENCHMARK_QUESTIONS_FILE"] = old


if __name__ == "__main__":
    unittest.main()
