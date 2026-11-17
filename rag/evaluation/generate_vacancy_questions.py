"""
Generate benchmark questions from a vacancy-rules pack (any job).

    python -m rag.evaluation.generate_vacancy_questions --src <pack.json> \\
        --vacancy CPI/9/2026 [--vacancy ...] | --all  --out <questions.json>

Opt-in and flexible:
* Only the vacancies you name are used; nothing happens for new jobs by itself.
* A question is generated only for a rule the vacancy declares (R02 age,
  R03 qualification, R04 experience, R09 period, R11 pass mark, R13 weights,
  R10 stages, plus positions and salary when present).
* Only questions whose label can be derived from the data are generated:
  direct (supported), "criteria not stated" (R14, partially_supported,
  borderline) and "no candidate data" (unsupported). Cross-source and
  temporal questions need a human author (see questions_hngv.py).
* Each question carries `needles`: strings that must occur in the corpus text
  built by rag/build_vacancy_corpus.py from the same pack, so the benchmark
  and corpus can be checked for agreement without any model.

Generated labels are the data's, not a second labeller's. `labeler_2` is
left empty for a person to fill. No benchmark result is produced here.
Standard library only.
"""

import argparse
import json
from pathlib import Path


def _qs_for(v):
    c, t = v["code"], v["job_title"]
    r = v.get("requirements", {})
    pid = c.replace("/", "_")
    out = []

    def add(kind, cat, expected, question, needles=None, note=None, parts=None, conf="high"):
        q = {"id": f"GEN-{pid}-{kind}", "category": cat, "question": question,
             "expected": expected, "label_confidence": conf, "labeler_2": None,
             "vacancy": c}
        if needles:
            q["needles"] = needles
        if note:
            q["reference_note"] = note
        if parts:
            q["supported_parts"], q["unsupported_parts"] = parts
        out.append(q)

    if "positions" in v:
        add("POS", "gen_direct", "supported", f"How many positions does vacancy {c} ({t}) offer?",
            [f"offers {v['positions']} positions"], f"{c}: {v['positions']} positions.")
    if "salary_usd" in v:
        add("SAL", "gen_direct", "supported", f"What is the monthly salary for vacancy {c} ({t})?",
            [f"is {v['salary_usd']} US dollars"], f"{c}: USD {v['salary_usd']}.")
    if "R02" in r:
        q = r["R02"]
        add("AGE", "gen_direct", "supported",
            f"What are the minimum and maximum ages for applicants to vacancy {c}?",
            [f"minimum age is {q['min_age']}", f"maximum age is {q['max_age']}"],
            f"{c}: age {q['min_age']} to {q['max_age']}.")
        if q.get("reference_date_stated") is False:
            add("AGEREF", "gen_partial", "partially_supported",
                f"On what date is an applicant's age measured to check the age limits of vacancy {c}?",
                parts=([f"Age limits are {q['min_age']} and {q['max_age']} years."],
                       ["The reference date is not stated."]))
    if "R03" in r:
        add("EDU", "gen_direct", "supported", f"Which qualification is required for vacancy {c} ({t})?",
            [r["R03"]["education_text"]], f"{c}: {r['R03']['education_text']}")
    if "R04" in r:
        q = r["R04"]
        add("EXP", "gen_direct", "supported",
            f"How much work experience is required for vacancy {c} ({t})?",
            [f"at least {q['min_months']:g} months", q["field"]],
            f"{c}: at least {q['min_months']:g} months in {q['field']}.")
    if "R09" in r:
        q = r["R09"]
        add("WIN", "gen_direct", "supported", f"During which dates can applicants submit documents for vacancy {c}?",
            [q["window_start"], q["window_end"]], f"{c}: {q['window_start']} to {q['window_end']}.")
    if "R10" in r:
        st = [s.replace("_", " ") for s in r["R10"]["stages"]]
        add("STG", "gen_direct", "supported", f"In what order are the selection stages of vacancy {c} carried out?",
            st, f"{c}: " + ", ".join(st) + ".")
    if "R11" in r:
        add("PASS", "gen_direct", "supported",
            f"What written-test score allows a candidate in vacancy {c} to continue?",
            [f"score of {r['R11']['written_min_score']}"], f"{c}: {r['R11']['written_min_score']}.")
    if "R13" in r:
        q = r["R13"]
        g, s = round(q["general_weight"] * 100), round(q["specific_weight"] * 100)
        add("WGT", "gen_direct", "supported",
            f"How is the written test of vacancy {c} weighted between general and specific subjects?",
            [f"{g}% general subjects and {s}% specific subjects"], f"{c}: {g}/{s}.")
    if r.get("R14", {}).get("criteria_stated") is False:
        add("R14", "gen_partial", "partially_supported",
            f"How are applications scored in the document assessment stage of vacancy {c}, and what score is needed to pass it?",
            parts=(["Document assessment is a stage of the selection."],
                   ["Scoring criteria and pass score of the document stage are not stated."]),
            conf="borderline")
    add("NOCAND", "gen_unsupported", "unsupported", f"How many candidates applied for vacancy {c}?",
        note="No candidate or application-count data in any corpus built from a vacancy notice.")
    return out


def generate(src, codes=None, all_vacancies=False):
    pack = json.loads(Path(src).read_text(encoding="utf-8"))
    chosen = [v for v in pack["vacancies"] if all_vacancies or (codes and v["code"] in codes)]
    if not chosen:
        raise SystemExit("No vacancy selected: pass --vacancy CODE (repeatable) or --all.")
    if codes:
        missing = set(codes) - {v["code"] for v in chosen}
        if missing:
            raise SystemExit(f"Unknown vacancy code(s): {sorted(missing)}")
    qs = [q for v in chosen for q in _qs_for(v)]
    return {"set": "generated_from_pack", "source_pack": Path(src).name,
            "status": "labels derived from pack data; second labeller pending; no results produced",
            "questions": qs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vacancy", action="append")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    doc = generate(a.src, a.vacancy, a.all)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(doc['questions'])} questions to {a.out}")


if __name__ == "__main__":
    main()
