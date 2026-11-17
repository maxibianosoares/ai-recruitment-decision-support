"""
Checks for the dynamic benchmark generator. No embeddings or LLM needed:

    python -m unittest rag.evaluation.test_dynamic_questions -v

They prove the generated questions agree with the generated corpus TEXT and
that the set grows when a vacancy is added to the JSON. They do not measure
retrieval accuracy.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from rag import build_hngv_corpus as bc
from rag.evaluation import benchmark_sets as bs
from rag.evaluation import dynamic_questions as dq

DATA = json.loads(dq.RULES_PATH.read_text(encoding="utf-8"))
VALID = {
    "hngv_direct": {"supported"}, "hngv_partial": {"partially_supported"},
    "hngv_unsupported": {"unsupported"}, "hngv_cross_source": {"supported"},
    "hngv_temporal": {"unsupported"},
}


def with_extra_vacancy():
    d = copy.deepcopy(DATA)
    v = copy.deepcopy(d["vacancies"][0])
    v.update(code="CPI/99/2026", job_title="Test Technician (Synthetic)", positions=7, salary_usd=333)
    d["vacancies"].append(v)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(d, f)
    f.close()
    return Path(f.name)


class Generator(unittest.TestCase):
    def test_ids_unique_and_labels_valid(self):
        qs = dq.build_dynamic_questions()
        ids = [q["id"] for q in qs]
        self.assertEqual(len(ids), len(set(ids)))
        for q in qs:
            self.assertIn(q["expected"], VALID[q["category"]], q["id"])
            if q["expected"] == "partially_supported":
                self.assertTrue(q["supported_parts"] and q["unsupported_parts"], q["id"])

    def test_deterministic(self):
        self.assertEqual(dq.build_dynamic_questions(), dq.build_dynamic_questions())

    def test_every_vacancy_is_covered(self):
        qs = dq.build_dynamic_questions()
        covered = {q.get("vacancy") for q in qs}
        for v in DATA["vacancies"]:
            self.assertIn(v["code"], covered)

    def test_all_topics_mode_is_larger(self):
        self.assertGreater(len(dq.build_dynamic_questions(per_vacancy=None, other_per_vacancy=None)),
                           len(dq.build_dynamic_questions()))

    def test_one_cross_source_question_per_conflict(self):
        qs = [q for q in dq.build_dynamic_questions() if q["category"] == "hngv_cross_source"]
        self.assertEqual(len(qs), len(DATA["statute_conflicts"]))


class AgreesWithCorpus(unittest.TestCase):
    def test_every_direct_needle_is_in_that_vacancys_corpus_text(self):
        by_code = {v["code"]: v for v in DATA["vacancies"]}
        qs = dq.build_dynamic_questions(per_vacancy=None, other_per_vacancy=None)
        checked = 0
        for q in qs:
            if q["category"] != "hngv_direct":
                continue
            text = bc.vacancy_doc(by_code[q["vacancy"]], DATA["general_regime_reference"])
            for n in q["corpus_needles"]:
                self.assertIn(n, text, f"{q['id']}: {n!r}")
                checked += 1
        self.assertGreater(checked, 100)

    def test_unprocessed_codes_absent_from_corpus_text(self):
        corpus = "".join(bc.vacancy_doc(v, DATA["general_regime_reference"]) for v in DATA["vacancies"])
        for code in DATA["known_unprocessed"]:
            self.assertNotIn(code, corpus)
            self.assertNotIn(code, {v["code"] for v in DATA["vacancies"]})

    def test_unprocessed_probe_questions_exist(self):
        qs = [q for q in dq.build_dynamic_questions() if q.get("template") == "unprocessed"]
        self.assertEqual(len(qs), len(DATA["known_unprocessed"]))


class Dynamic(unittest.TestCase):
    def test_adding_a_vacancy_adds_questions_that_match_its_corpus_text(self):
        path = with_extra_vacancy()
        try:
            before = dq.build_dynamic_questions()
            after = dq.build_dynamic_questions(rules_path=path)
            new = [q for q in after if q.get("vacancy") == "CPI/99/2026"]
            self.assertGreater(len(after), len(before))
            self.assertGreaterEqual(len(new), 8)   # 4 direct + 2 partial + 2 unsupported
            d = json.loads(path.read_text(encoding="utf-8"))
            v = [x for x in d["vacancies"] if x["code"] == "CPI/99/2026"][0]
            text = bc.vacancy_doc(v, d["general_regime_reference"])
            full = dq.build_dynamic_questions(rules_path=path, per_vacancy=None)
            for q in full:
                if q.get("vacancy") == "CPI/99/2026" and q["category"] == "hngv_direct":
                    for n in q["corpus_needles"]:
                        self.assertIn(n, text)
            self.assertIn("offers 7 positions", text)
            self.assertIn("is 333 US dollars", text)
        finally:
            os.unlink(path)

    def test_processed_code_stops_being_an_unprocessed_probe(self):
        d = copy.deepcopy(DATA)
        v = copy.deepcopy(d["vacancies"][0])
        v["code"] = d["known_unprocessed"][0]
        d["vacancies"].append(v)
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(d, f)
        f.close()
        try:
            qs = dq.build_dynamic_questions(rules_path=Path(f.name))
            probes = [q for q in qs if q.get("template") == "unprocessed"]
            self.assertEqual(len(probes), len(DATA["known_unprocessed"]) - 1)
        finally:
            os.unlink(f.name)


class Sets(unittest.TestCase):
    def test_set_sizes(self):
        n = {k: len(bs.load_set(k)) for k in bs.RESULT_FILES if k != "generated"}   # "generated" is opt-in and needs a file
        self.assertEqual(n["baseline"], 40)
        self.assertEqual(n["hngv"], 40)
        self.assertEqual(n["combined"], 80)
        self.assertEqual(n["all"], 80 + n["dynamic"])

    def test_ids_unique_across_all(self):
        ids = [q["id"] for q in bs.load_set("all")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_result_files_distinct_and_baseline_unchanged(self):
        self.assertEqual(len(set(bs.RESULT_FILES.values())), len(bs.RESULT_FILES))
        self.assertEqual(bs.RESULT_FILES["baseline"], "benchmark_40_results.json")

    def test_unknown_set_rejected(self):
        old = os.environ.get("BENCHMARK_SET")
        os.environ["BENCHMARK_SET"] = "nonsense"
        try:
            with self.assertRaises(SystemExit):
                bs.current_set()
        finally:
            if old is None:
                os.environ.pop("BENCHMARK_SET")
            else:
                os.environ["BENCHMARK_SET"] = old

    def test_exported_json_is_current(self):
        j = json.loads(dq.EXPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual([q["id"] for q in j["questions"]], [q["id"] for q in dq.build_dynamic_questions()])


if __name__ == "__main__":
    unittest.main()
