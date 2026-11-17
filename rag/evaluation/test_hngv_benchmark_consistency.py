"""
Consistency checks between the HNGV benchmark extension, the vacancy-rules
JSON and the staged corpus text. No embeddings, FAISS or LLM needed:

    python -m unittest rag.evaluation.test_hngv_benchmark_consistency -v

These checks prove that the benchmark labels agree with the corpus TEXT.
They do NOT measure retrieval or evidence-gate accuracy; that needs
BENCHMARK_SET=hngv python -m rag.evaluation.run_benchmark after the index
is rebuilt.
"""
import json
import re
import unittest
from pathlib import Path

from rag.evaluation.questions_hngv import HNGV_QUESTIONS

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "knowledge_base" / "documents_staging" / "hngv_2026"
RULES = ROOT / "knowledge_base" / "vacancy_rules" / "hngv_2026_vacancy_rules.json"

VALID = {
    "hngv_direct": {"supported"},
    "hngv_partial": {"partially_supported"},
    "hngv_unsupported": {"unsupported"},
    "hngv_cross_source": {"supported", "partially_supported"},
    "hngv_temporal": {"unsupported", "partially_supported"},
}


def doc_for(code):
    slug = "cpi_" + code.split("/")[1] + "_2026"
    hits = [p for p in STAGING.glob("*.md") if f"_{slug}_" in p.name]
    assert len(hits) == 1, (code, hits)
    return hits[0].read_text(encoding="utf-8")


def all_text():
    return "\n".join(p.read_text(encoding="utf-8") for p in STAGING.glob("*.md"))


class Structure(unittest.TestCase):
    def test_count_and_unique_ids(self):
        ids = [q["id"] for q in HNGV_QUESTIONS]
        self.assertEqual(len(ids), 40)
        self.assertEqual(len(ids), len(set(ids)))

    def test_category_expected_pairs_valid(self):
        for q in HNGV_QUESTIONS:
            self.assertIn(q["expected"], VALID[q["category"]], q["id"])

    def test_partial_items_name_both_parts(self):
        for q in HNGV_QUESTIONS:
            if q["expected"] == "partially_supported":
                self.assertTrue(q.get("supported_parts") and q.get("unsupported_parts"), q["id"])

    def test_json_export_matches_python(self):
        j = json.loads((ROOT / "rag" / "evaluation" / "benchmark_hngv_questions.json").read_text(encoding="utf-8"))
        self.assertEqual([q["id"] for q in j["questions"]], [q["id"] for q in HNGV_QUESTIONS])
        self.assertTrue(all(q["labeler_2"] is None for q in j["questions"]))


class DirectAnswersAreInCorpus(unittest.TestCase):
    # question id -> (vacancy code, strings that must appear in that vacancy's document)
    CASES = {
        "HD01": ("CPI/1/2026", ["minimum age is 20", "maximum age is 55"]),
        "HD02": ("CPI/2/2026", ["offers 236 positions"]),
        "HD03": ("CPI/4/2026", ["salary for vacancy CPI/4/2026 is 250"]),
        "HD04": ("CPI/18/2026", ["salary for vacancy CPI/18/2026 is 405"]),
        "HD05": ("CPI/5/2026", ["Licenciatura in Midwifery"]),
        "HD06": ("CPI/7/2026", ["at least 3 months", "radiology"]),
        "HD07": ("CPI/1/2026", ["2026-09-07", "2026-09-18"]),
        "HD08": ("CPI/1/2026", ["08:00-12:00 and 13:30-17:30"]),
        "HD09": ("CPI/14/2026", ["25% general subjects and 75% specific subjects"]),
        "HD10": ("CPI/13/2026", ["document assessment", "written test", "interview"]),
        "HD11": ("CPI/8/2026", ["score of 60"]),
        "HD12": ("CPI/1/2026", ["hngv.ms.gov.tl/rekrutamentu", "Facebook"]),
        "HD13": ("CPI/1/2026", ["offers 112 positions", "is 610 US dollars"]),
        "HD14": ("CPI/1/2026", ["permanent appointment", "probation period of 1 year"]),
        "HD15": ("CPI/2/2026", ["medical certificate presented at the interview stage"]),
    }

    def test_each_direct_question_has_its_answer_text(self):
        ids = {q["id"] for q in HNGV_QUESTIONS if q["category"] == "hngv_direct"}
        self.assertEqual(ids, set(self.CASES))
        for qid, (code, needles) in self.CASES.items():
            text = doc_for(code)
            for n in needles:
                self.assertIn(n, text, f"{qid}: {n!r} not in {code} document")


class UnsupportedAreNotInCorpus(unittest.TestCase):
    def test_unprocessed_vacancy_absent(self):
        self.assertNotIn("CPI/3/2026", all_text())

    def test_no_candidate_data_terms(self):
        text = all_text().lower()
        for term in ("applicants admitted", "candidates excluded", "interview score of", "senior general doctor", "outpatient"):
            self.assertNotIn(term, text)

    def test_no_personal_names_of_jury(self):
        text = all_text()
        for name in ("Vidal", "Eligio", "Juvenal", "Floriati", "Rosvita"):
            self.assertNotIn(name, text)


class ReferenceLawStaysAuthoritative(unittest.TestCase):
    def test_every_vacancy_doc_says_the_statute_is_the_reference(self):
        for p in STAGING.glob("*cpi_*.md"):
            t = p.read_text(encoding="utf-8")
            self.assertIn("secondary source", t, p.name)
            self.assertIn("the statute is the reference", t, p.name)
            self.assertIn("apply to this vacancy only", t, p.name)
            self.assertIn("applies to every civil service vacancy", t, p.name)

    def test_catalogue_lists_notice_vs_statute_differences(self):
        t = (STAGING / "hngv_2026_rule_catalogue.md").read_text(encoding="utf-8")
        for topic in ("minimum age", "pass mark boundary", "official language"):
            self.assertIn(f"Difference on {topic}", t)
        self.assertIn("The statute is the reference law", t)


class CorpusAgreesWithJson(unittest.TestCase):
    def test_every_vacancy_doc_carries_json_values(self):
        data = json.loads(RULES.read_text(encoding="utf-8"))
        for v in data["vacancies"]:
            t = doc_for(v["code"])
            self.assertIn(f"offers {v['positions']} positions", t, v["code"])
            self.assertIn(f"is {v['salary_usd']} US dollars", t, v["code"])
            self.assertIn(f"minimum age is {v['requirements']['R02']['min_age']}", t, v["code"])

    def test_total_positions_in_overview(self):
        t = (STAGING / "hngv_2026_overview.md").read_text(encoding="utf-8")
        self.assertIn("430 positions", t)

    def test_cross_source_facts_exist_in_existing_pdfs_text_if_available(self):
        # Only runs when pdftotext output of the existing corpus was dumped; otherwise skipped.
        dump = ROOT / "knowledge_base" / "_text_dump"
        if not dump.exists():
            self.skipTest("no text dump of existing PDFs")
        joined = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in dump.glob("*.txt"))
        self.assertTrue(re.search(r"60 points or less", joined))
        self.assertTrue(re.search(r"twelve months", joined))
        self.assertTrue(re.search(r"at least one official language", joined))
        self.assertTrue(re.search(r"5 working days", joined))


if __name__ == "__main__":
    unittest.main()
