# -*- coding: utf-8 -*-
"""
Dynamic benchmark generator: questions for EVERY vacancy in the rules JSON.

    python -m rag.evaluation.dynamic_questions            # summary
    python -m rag.evaluation.dynamic_questions --export   # writes benchmark_dynamic_questions.json

Add a vacancy to knowledge_base/vacancy_rules/hngv_2026_vacancy_rules.json,
re-run `python -m rag.build_hngv_corpus`, and the benchmark grows by itself:
questions, expected labels and the strings each answer must contain are all
derived from the same JSON that generates the corpus text.

Question types (labels are fixed by the template, not by a model):
  hngv_direct        answer stated in the vacancy notice        -> supported
  hngv_partial       part stated, part not in the notice         -> partially_supported
  hngv_unsupported   not in corpus (no applicants/test data;
                     notices not yet processed)                  -> unsupported
  hngv_cross_source  one per statute conflict in the JSON        -> supported
  hngv_temporal      depends on "today"                          -> unsupported

`per_vacancy` limits direct questions per vacancy (default 4; partial and
unsupported default 2 each via `other_per_vacancy`) so that 10 near-
identical vacancies do not swamp the baseline; topics rotate by a stable hash,
so every topic is still covered across vacancies. per_vacancy=None / other_per_vacancy=None -> all topics.

Labels come from templates and have had NO human second labeller. Generated
questions are a scalable regression set, not a gold standard; keep the 40
hand-written questions in questions_hngv.py as the gold set.
No third-party dependencies; does not touch the index.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "knowledge_base" / "vacancy_rules" / "hngv_2026_vacancy_rules.json"
EXPORT_PATH = Path(__file__).resolve().parent / "benchmark_dynamic_questions.json"
DEFAULT_PER_VACANCY = 4      # direct topics per vacancy
DEFAULT_OTHER_PER_VACANCY = 2  # partial and unsupported topics per vacancy each


def _short(v):
    return v["job_title"].split(" (")[0]


def _direct_topics(v):
    r = v["requirements"]
    c, t = v["code"], _short(v)
    return [
        ("positions", f"How many positions does vacancy {c} ({t}) offer?",
         [f"offers {v['positions']} positions"], f"{v['positions']} positions."),
        ("salary", f"What is the monthly salary for vacancy {c} ({t})?",
         [f"is {v['salary_usd']} US dollars"], f"USD {v['salary_usd']}."),
        ("age", f"What are the minimum and maximum ages for applicants to vacancy {c}?",
         [f"minimum age is {r['R02']['min_age']}", f"maximum age is {r['R02']['max_age']}"],
         f"Age {r['R02']['min_age']} to {r['R02']['max_age']}."),
        ("education", f"Which qualification is required for vacancy {c} ({t})?",
         [r["R03"]["education_text"]], r["R03"]["education_text"]),
        ("experience", f"How much work experience does vacancy {c} require?",
         [f"at least {int(r['R04']['min_months'])} months of work experience in {r['R04']['field']}"],
         f"At least {int(r['R04']['min_months'])} months in {r['R04']['field']} in a health facility."),
        ("language", f"Which language skills does vacancy {c} require?",
         [r["R05"]["languages"]], r["R05"]["languages"]),
        ("period", f"During which dates could applicants submit documents for vacancy {c}?",
         [r["R09"]["window_start"], r["R09"]["window_end"]],
         f"{r['R09']['window_start']} to {r['R09']['window_end']}."),
        ("hours", f"What are the daily document-submission hours for vacancy {c}?",
         ["08:00-12:00 and 13:30-17:30"], "08:00-12:00 and 13:30-17:30 on working days."),
        ("weights", f"How is the written test content weighted for vacancy {c}?",
         [f"{int(r['R13']['general_weight']*100)}% general subjects and {int(r['R13']['specific_weight']*100)}% specific subjects"],
         f"General {int(r['R13']['general_weight']*100)}%, specific {int(r['R13']['specific_weight']*100)}%."),
        ("passmark", f"What written-test score lets a candidate in vacancy {c} continue to the interview?",
         [f"score of {r['R11']['written_min_score']}"], f"Score of {r['R11']['written_min_score']}."),
        ("medical", f"At which stage must the medical certificate be presented in vacancy {c}?",
         ["medical certificate presented at the interview stage"], "At the interview stage."),
        ("probation", f"What probation period applies to vacancy {c}?",
         [f"probation period of {v['probation_years']} year"], f"{v['probation_years']} year."),
    ]


def _partial_topics(v):
    c = v["code"]
    out = [
        ("stage1", f"How are applications scored in the document assessment stage of vacancy {c}, and what score is needed to pass it?",
         ["Document assessment is stage I; candidates who pass continue to the written test."],
         ["Scoring criteria and pass score of stage I are not stated (accountability gap R14)."], "borderline"),
        ("conduct", f"When must a candidate for vacancy {c} submit the 'Bom Comportamento' good-conduct certificate?",
         ["A valid Bom Comportamento certificate from the Ministry of Justice is a mandatory requirement."],
         ["It is not in the numbered list of documents to submit; submission time is not stated."], "high"),
        ("english", f"How is language proficiency tested for applicants to vacancy {c}?",
         ["The required language skills are listed."],
         ["No test method, level or minimum score is described."], "high"),
        ("expletter", f"Does the notice for vacancy {c} require an employer letter as proof of the required experience?",
         ["The minimum experience is stated; CV and training certificates are listed."],
         ["An experience letter is not among the listed documents; how experience is proven is not stated."], "high"),
        ("agedate", f"On what date is an applicant's age measured to check the age limits in vacancy {c}?",
         ["The age limits are stated and proven by identity documents."],
         ["The reference date (closing date, test date, appointment date) is not stated."], "high"),
    ]
    if v["verification"].get("flags"):
        out.append(("inconsistent", f"Which exact qualification does vacancy {c} require?",
                    ["The notice lists several qualifications."],
                    ["The notice text is inconsistent; check the PDF."], "borderline"))
    return out


def _unsupported_topics(v):
    c = v["code"]
    return [
        ("applicants", f"How many candidates applied for vacancy {c}?", "No candidate or application-count data in the corpus."),
        ("testcontent", f"Which questions were asked in the written test of vacancy {c}?", "Only the programme of subjects is in the notice."),
        ("testdate", f"On what date and at what venue was the written test for vacancy {c} held?", "Test date and venue are not in the vacancy notices."),
        ("topscore", f"What interview score did the highest-ranked candidate obtain in vacancy {c}?", "No candidate results in the corpus."),
    ]


def _slug(code):
    return code.replace("/", "-").replace("-2026", "").lower().replace("cpi-", "cpi")


def _pick(code, topics, n):
    """Deterministic rotation: keep the n topics with the smallest stable hash."""
    if n is None or n >= len(topics):
        return topics
    ranked = sorted(topics, key=lambda t: hashlib.md5(f"{code}|{t[0]}".encode()).hexdigest())
    keep = {t[0] for t in ranked[:n]}
    return [t for t in topics if t[0] in keep]


def build_dynamic_questions(rules_path=None, per_vacancy=DEFAULT_PER_VACANCY,
                            other_per_vacancy=DEFAULT_OTHER_PER_VACANCY):
    data = json.loads(Path(rules_path or RULES_PATH).read_text(encoding="utf-8"))
    qs = []
    have = {v["code"] for v in data["vacancies"]}
    for v in data["vacancies"]:
        c, s = v["code"], _slug(v["code"])
        for key, q, needles, ref in _pick(c, _direct_topics(v), per_vacancy):
            qs.append({"id": f"DY-{s}-{key}", "category": "hngv_direct", "expected": "supported",
                       "question": q, "reference_note": f"{c}: {ref}", "vacancy": c, "template": key,
                       "corpus_needles": needles, "label_confidence": "high", "generated": True, "labeler_2": None})
        for key, q, sup, uns, conf in _pick(c, _partial_topics(v), other_per_vacancy):
            qs.append({"id": f"DY-{s}-{key}", "category": "hngv_partial", "expected": "partially_supported",
                       "question": q, "supported_parts": sup, "unsupported_parts": uns, "vacancy": c,
                       "template": key, "label_confidence": conf, "generated": True, "labeler_2": None})
        for key, q, ref in _pick(c, _unsupported_topics(v), other_per_vacancy):
            qs.append({"id": f"DY-{s}-{key}", "category": "hngv_unsupported", "expected": "unsupported",
                       "question": q, "reference_note": f"{c}: {ref}", "vacancy": c, "template": key,
                       "label_confidence": "high", "generated": True, "labeler_2": None})
    for code in data.get("known_unprocessed", []):
        if code in have:
            continue   # now processed: no longer an "unsupported" probe
        qs.append({"id": f"DY-{_slug(code)}-positions", "category": "hngv_unsupported", "expected": "unsupported",
                   "question": f"How many positions does vacancy {code} offer?",
                   "reference_note": f"{code} is not in the corpus (notice not yet processed).",
                   "vacancy": code, "template": "unprocessed", "label_confidence": "high",
                   "generated": True, "labeler_2": None})
    for cf in data.get("statute_conflicts", []):
        qs.append({"id": f"DY-conflict-{cf['id'].lower()}", "category": "hngv_cross_source", "expected": "supported",
                   "question": f"On {cf['topic']}, what do the HNGV notices say and what does the statute say?",
                   "reference_note": f"Notices: {cf['notice']}. Statute: {cf['statute']}.",
                   "conflict": cf["id"], "template": "conflict", "label_confidence": "high",
                   "generated": True, "labeler_2": None})
    for key, q in (("open-now", "Are applications for the HNGV special-regime vacancies still open today?"),
                   ("final-list", "Has the final result list of the HNGV 2026 competition been published, and who ranked first?"),
                   ("new-vacancies", "Which new HNGV vacancies were announced after September 2026?")):
        qs.append({"id": f"DY-temporal-{key}", "category": "hngv_temporal", "expected": "unsupported",
                   "question": q, "reference_note": "Depends on today's date or later events; corpus is a September 2026 snapshot.",
                   "template": "temporal", "label_confidence": "high", "generated": True, "labeler_2": None})
    return qs


def summary(qs):
    from collections import Counter
    return Counter((q["category"], q["expected"]) for q in qs)


if __name__ == "__main__":
    qs = build_dynamic_questions()
    print(f"{len(qs)} dynamic questions")
    for k, v in sorted(summary(qs).items()):
        print(" ", k, v)
    if "--export" in sys.argv:
        EXPORT_PATH.write_text(json.dumps(
            {"set": "hngv_dynamic", "status": "template labels; no second labeller; no results produced",
             "questions": qs}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", EXPORT_PATH)
