"""
One place that decides which question set a benchmark run uses.

BENCHMARK_SET (env var):
  baseline  original 40 questions (default; unchanged behaviour)
  hngv      40 hand-written HNGV gold questions
  dynamic   questions generated from the vacancy-rules JSON for ALL vacancies
  combined  baseline + hngv (80)
  all       baseline + hngv + dynamic
  generated questions from a file made by generate_vacancy_questions.py for ANY pack;
            path in env BENCHMARK_QUESTIONS_FILE (opt-in, never part of the others)
Each set writes its own results file; the baseline results are never overwritten.
"""
import os

RESULT_FILES = {
    "baseline": "benchmark_40_results.json",
    "hngv": "benchmark_hngv_40_results.json",
    "dynamic": "benchmark_dynamic_results.json",
    "combined": "benchmark_80_results.json",
    "all": "benchmark_all_results.json",
    "generated": "benchmark_generated_results.json",
}


def current_set():
    name = os.environ.get("BENCHMARK_SET", "baseline").lower()
    if name not in RESULT_FILES:
        raise SystemExit(f"Unknown BENCHMARK_SET={name!r}; use one of {sorted(RESULT_FILES)}")
    return name


def _load_set_raw(name):
    from rag.evaluation.questions import BENCHMARK_QUESTIONS
    if name == "baseline":
        return BENCHMARK_QUESTIONS
    from rag.evaluation.questions_hngv import HNGV_QUESTIONS
    from rag.evaluation.dynamic_questions import build_dynamic_questions
    if name == "hngv":
        return list(HNGV_QUESTIONS)
    if name == "dynamic":
        return build_dynamic_questions()
    if name == "combined":
        return list(BENCHMARK_QUESTIONS) + list(HNGV_QUESTIONS)
    if name == "generated":
        import json
        path = os.environ.get("BENCHMARK_QUESTIONS_FILE")
        if not path:
            raise SystemExit("BENCHMARK_SET=generated needs BENCHMARK_QUESTIONS_FILE=<questions.json>")
        with open(path, encoding="utf-8") as f:
            return json.load(f)["questions"]
    return list(BENCHMARK_QUESTIONS) + list(HNGV_QUESTIONS) + build_dynamic_questions()


# ---- quick proof mode -------------------------------------------------
# BENCHMARK_IDS=quick (or a comma list of ids) runs only those questions;
# BENCHMARK_TAG=before|after adds a suffix so two runs never overwrite each other.
# Quick runs always write to a *_quick*.json file, never to the real results file.
QUICK_IDS = [
    "HD01", "HD07", "HD09", "HD13",   # direct, answer is in one notice
    "HP01", "HP05",                   # partial: criteria / reference date not stated
    "HU01", "HU02",                   # unsupported: unprocessed vacancy, no candidate data
    "HX01", "HX02", "HX05",           # cross-source: notice vs statute
    "HT01",                           # temporal
    "OS01", "DE04",                   # old-baseline controls: do they change once the corpus is added?
]


def _wanted_ids():
    raw = os.environ.get("BENCHMARK_IDS", "").strip()
    if not raw:
        return None
    return QUICK_IDS if raw.lower() == "quick" else [x.strip() for x in raw.split(",") if x.strip()]


def load_set(name):
    qs = _load_set_raw(name)
    ids = _wanted_ids()
    if ids is None:
        return qs
    by_id = {q["id"]: q for q in qs}
    missing = [i for i in ids if i not in by_id]
    if missing and name not in ("combined", "all"):
        raise SystemExit(f"BENCHMARK_IDS not in set {name!r}: {missing}")
    return [by_id[i] for i in ids if i in by_id]


def result_file(name):
    """Results file name for a set, with _quick / _TAG suffixes so runs never overwrite each other."""
    base = RESULT_FILES[name][:-5]
    if _wanted_ids() is not None:
        base += "_quick"
    tag = os.environ.get("BENCHMARK_TAG", "").strip()
    if tag:
        base += "_" + "".join(ch for ch in tag if ch.isalnum() or ch in "-_")
    return base + ".json"
