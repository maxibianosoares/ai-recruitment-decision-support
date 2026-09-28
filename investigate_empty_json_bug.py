"""
Investigation script for the local Ollama gemma3:4b "returns literal {}"
bug in CV profile generation (observed 2026-09-26, 3/3 attempts on
job_id=17, all responses: 2 chars, eval_count=2, raw text "{}").

Purpose
-------
Determine, with real repeated data (not a single anecdote), whether the
empty-{}-response is:
  (A) tied to format="json" grammar-constrained decoding specifically,
  (B) a property of THIS prompt's structure/length,
  (C) a general gemma3:4b generation quirk independent of prompt/format,
  (D) something else (Ollama version, options, etc.)

This script does NOT touch production code, the database, any Django
model, or any candidate's real CV data. It talks to Ollama directly,
using the SAME endpoint, model name and keep_alive setting as
llm_service.py (imported, not duplicated) so results are representative
of the real request shape. The "CV" used is a short SYNTHETIC fixture
(no real candidate data) built to resemble the structure/length of a
real CV profile-extraction prompt.

It runs N repeated attempts under each of several conditions and
classifies every raw response into one of:
    EMPTY_OBJECT      -- literal "{}" (the bug being investigated)
    VALID_OBJECT       -- a JSON object with at least one DEFAULT_PROFILE key
    ARRAY_WRAPPED       -- a JSON array (the already-fixed online_gemma shape,
                           included here only so a genuinely mixed result
                           doesn't get miscounted as "invalid")
    INVALID_JSON        -- json.loads() itself raised
    OTHER               -- valid JSON but none of the above shapes

Conditions tested (A-D from the ticket; E is a repeated-calls sanity
check baked into every condition via --runs):
    baseline         : exact production request shape (format="json",
                       options={} beyond keep_alive) -- what
                       llm_service.generate_json() sends today
    no_json_format   : same prompt, same options, but WITHOUT
                       format="json" (tests whether grammar-constrained
                       decoding itself is implicated)
    explicit_instruct: baseline request shape, but the prompt has one
                       extra explicit line added at the very end
                       reinforcing "you MUST return the complete JSON
                       object with all fields filled in, never an empty
                       object" (tests whether prompt wording alone
                       changes the failure rate)

Nothing here changes analyze_cv(), generate_json(), or any production
file. It is purely a measurement tool -- diagnostic only, no
commit/push/deploy implied.

Usage:
    python investigate_empty_json_bug.py
    python investigate_empty_json_bug.py --runs 15
    python investigate_empty_json_bug.py --runs 15 --conditions baseline,no_json_format
"""

import argparse
import json
import sys
import time
from datetime import datetime

import requests

# No Django settings needed -- model_config.py only imports os/requests,
# so this works from the repo root without touching manage.py/Django.
from ai_engine.services.model_config import (
    MODEL_NAME,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_KEEP_ALIVE,
)

DEFAULT_PROFILE_KEYS = [
    "education",
    "skills",
    "languages",
    "certifications",
    "years_experience",
    "professional_summary",
]

# Synthetic CV -- structurally similar to a real one (same rough length
# and section shape as production CVs), but entirely fabricated, no
# real candidate's data. Only used to reproduce the REQUEST SHAPE that
# triggers the bug, not to test extraction accuracy.
SYNTHETIC_CV_TEXT = """
John Doe
ICT Support Officer

Education
Bachelor of Computer Science, National University (2018-2022)

Professional Experience
IT Support Technician, Example Corp (2022-2025)
- Provided desktop and network troubleshooting for 200+ staff
- Maintained Windows Server infrastructure
- Administered basic SQL databases for internal reporting
- Documented technical procedures for the helpdesk knowledge base

Skills
Windows Administration, Network Troubleshooting, SQL, Technical
Documentation, Help Desk Support, Active Directory, Basic Python
scripting, Customer service, Hardware diagnostics, Printer and
peripheral support

Languages
English (fluent), Tetum (native)

Certifications
CompTIA A+ (2021)
""".strip()

MULTILINGUAL_INSTRUCTION = """
The CV and Job Description may be written in English, Portuguese, Tetum,
Indonesian, or a mixture of these languages.

You must understand the meaning regardless of the language used.

Perform semantic analysis across languages.

Treat equivalent concepts as identical.

Extract information based on meaning rather than exact wording. Do not
translate the source text yourself and do not lose legal/recruitment
meaning by paraphrasing loosely -- read in the original language, extract
the meaning, and write the structured output in the field's expected
format.

Extract only information that is actually stated or clearly implied in the
source document. Do not infer, guess, or fill in missing qualifications,
years of experience, certifications, employment history, or skills that
are not supported by the text. If information for a field is not present,
leave it empty rather than inventing a plausible-sounding value.
""".strip()

DEFAULT_PROFILE_SCHEMA = {
    "education": "",
    "skills": [],
    "languages": [],
    "certifications": [],
    "years_experience": 0,
    "professional_summary": ""
}


def build_prompt(cv_text, extra_instruction=""):
    """
    Byte-for-byte the same template as
    ai_engine/services/llm_candidate_profile.py::analyze_cv(), so this
    probe exercises the real production prompt shape. `extra_instruction`
    is appended only for the explicit_instruct condition.
    """
    prompt = f"""
You are an expert AI Recruitment Analyst.

{MULTILINGUAL_INSTRUCTION}

Analyze the following CV.

Extract the candidate profile.

Return ONLY valid JSON.

Schema

{json.dumps(DEFAULT_PROFILE_SCHEMA, indent=4)}

Rules

- Return JSON only.
- No markdown.
- No explanation.
- skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.
{extra_instruction}
CV

{cv_text}
"""
    return prompt


EXTRA_INSTRUCTION_TEXT = (
    "- You MUST return the complete JSON object with every field filled "
    "in based on the CV. NEVER return an empty object {}.\n"
)


def classify_response(raw_text):
    """
    Returns (category, parsed_or_none). Never raises.
    """
    if raw_text == "{}" or raw_text.strip() == "{}":
        return "EMPTY_OBJECT", {}

    try:
        parsed = json.loads(raw_text)
    except Exception:
        return "INVALID_JSON", None

    if isinstance(parsed, dict):
        if not parsed:
            return "EMPTY_OBJECT", parsed
        if any(key in parsed for key in DEFAULT_PROFILE_KEYS):
            return "VALID_OBJECT", parsed
        return "OTHER", parsed

    if isinstance(parsed, list):
        if len(parsed) == 1 and isinstance(parsed[0], dict):
            return "ARRAY_WRAPPED", parsed
        return "OTHER", parsed

    return "OTHER", parsed


def ns_to_s(ns):
    return (ns / 1e9) if isinstance(ns, (int, float)) else None


def call_ollama(prompt, use_json_format):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    if use_json_format:
        payload["format"] = "json"

    start = time.perf_counter()
    response = requests.post(
        OLLAMA_GENERATE_URL,
        json=payload,
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    wall_time = time.perf_counter() - start
    response.raise_for_status()
    data = response.json()

    raw_text = data.get("response", "")

    return {
        "raw_text": raw_text,
        "response_length_chars": len(raw_text),
        "wall_time_s": round(wall_time, 3),
        "total_duration_s": ns_to_s(data.get("total_duration")),
        "load_duration_s": ns_to_s(data.get("load_duration")),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration_s": ns_to_s(data.get("prompt_eval_duration")),
        "eval_count": data.get("eval_count"),
        "eval_duration_s": ns_to_s(data.get("eval_duration")),
    }


CONDITIONS = {
    "baseline": {
        "use_json_format": True,
        "extra_instruction": "",
        "description": "format=\"json\" (exact production shape today)",
    },
    "no_json_format": {
        "use_json_format": False,
        "extra_instruction": "",
        "description": "same prompt, WITHOUT format=\"json\"",
    },
    "explicit_instruct": {
        "use_json_format": True,
        "extra_instruction": EXTRA_INSTRUCTION_TEXT,
        "description": "format=\"json\" + explicit anti-empty-object instruction",
    },
}


def run_condition(name, config, runs):
    prompt = build_prompt(SYNTHETIC_CV_TEXT, config["extra_instruction"])

    print(f"\n{'=' * 70}")
    print(f"CONDITION: {name} -- {config['description']}")
    print(f"{'=' * 70}")

    results = []

    for i in range(1, runs + 1):
        try:
            call_result = call_ollama(prompt, config["use_json_format"])
            category, parsed = classify_response(call_result["raw_text"])
        except Exception as e:
            category = "REQUEST_ERROR"
            parsed = None
            call_result = {
                "raw_text": f"<request failed: {e}>",
                "response_length_chars": None,
                "wall_time_s": None,
                "total_duration_s": None,
                "load_duration_s": None,
                "prompt_eval_count": None,
                "prompt_eval_duration_s": None,
                "eval_count": None,
                "eval_duration_s": None,
            }

        results.append({"run": i, "category": category, **call_result})

        print(
            f"  run {i}/{runs}: {category:14s} | "
            f"len={call_result['response_length_chars']} chars | "
            f"eval_count={call_result['eval_count']} | "
            f"eval_duration={call_result['eval_duration_s']}s | "
            f"total_duration={call_result['total_duration_s']}s"
        )

    return results


def print_summary(all_results):
    print(f"\n{'=' * 70}")
    print("SUMMARY (per condition)")
    print(f"{'=' * 70}")

    for condition_name, results in all_results.items():
        total = len(results)
        counts = {}
        for r in results:
            counts[r["category"]] = counts.get(r["category"], 0) + 1

        print(f"\n{condition_name} (n={total}):")
        for category, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            pct = (count / total * 100) if total else 0
            print(f"  {category:14s}: {count}/{total}  ({pct:.0f}%)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of repeated attempts per condition (default: 10)",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default="baseline,no_json_format,explicit_instruct",
        help="Comma-separated condition names to run (default: all three)",
    )
    args = parser.parse_args()

    selected = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CONDITIONS]
    if unknown:
        print(f"Unknown condition(s): {unknown}. Valid: {list(CONDITIONS)}")
        sys.exit(1)

    print(f"Investigation started at {datetime.now().isoformat()}")
    print(f"Model: {MODEL_NAME} | Ollama: {OLLAMA_GENERATE_URL} | keep_alive={OLLAMA_KEEP_ALIVE}")
    print(f"Runs per condition: {args.runs}")
    print(f"Conditions: {selected}")

    all_results = {}
    for name in selected:
        all_results[name] = run_condition(name, CONDITIONS[name], args.runs)

    print_summary(all_results)

    print(f"\nInvestigation finished at {datetime.now().isoformat()}")
    print("No production code, database, or Django model was touched by this script.")


if __name__ == "__main__":
    main()
