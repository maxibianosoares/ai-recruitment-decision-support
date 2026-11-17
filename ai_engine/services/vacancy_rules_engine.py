"""
Deterministic vacancy-eligibility rules ("law in code"), data-driven.

What changed in v2 (2026-11-17)
-------------------------------
1. GENERIC PROFILES. A job's rules live in a JSON "profile" (same schema as
   knowledge_base/vacancy_rules/hngv_2026_vacancy_rules.json). Any *.json file
   in knowledge_base/vacancy_rules/ that has a "vacancies" list is searched by
   code, or a vacancy dict can be passed directly. Nothing is applied to a new
   job automatically: a job is only evaluated if the caller names a profile.
   Each rule block (R01..R14) is OPTIONAL; a missing block gives NOT_APPLICABLE.
2. REFERENCE LAW STAYS AUTHORITATIVE. knowledge_base/vacancy_rules/
   reference_law_baseline.json holds constraints transcribed from the statutes
   already in the RAG corpus (age 17-55, pass mark, language, probation...).
   A notice is a secondary source. Every age / pass-mark check is evaluated
   twice, once per the notice and once per the law:
     * same answer            -> that answer (PASS or FAIL);
     * different answers      -> REVIEW, with both readings and the citation in
                                 `law_conflicts` (default policy "review").
   Policies (parameter `conflict_policy`): "review" (default, safe), "notice",
   "law" (what-if runs only). The engine never silently follows a notice that
   contradicts the law.
3. THE LAW APPLIES TO EVERY JOB. The reference-law constraints are mandatory for
   all civil-service vacancies, whether or not a profile declares the matching
   block: a job with no R02 is still checked against the law's age range, and a
   job with no R11 is still checked against the law's pass-mark rule. A profile's
   own rules are ADDITIONS that apply to that one vacancy only. The law layer
   can be switched off only with `allow_no_law=True` (what-if / tests); a result
   produced that way can never be AUTOMATED_CHECKS_PASSED.
4. `audit_vacancy_against_law(vacancy)` lists the static differences between a
   profile and the law (no candidate needed).

Principles kept from v1: every check returns a rule ID; rules of type "human"
are never decided here; the output is decision SUPPORT (`decision_authority`
is always "jury"); standard library only; no network; candidate data stays in
process.

Outcomes per rule: PASS, FAIL, REVIEW, HUMAN, NOT_DUE, NOT_APPLICABLE.
Overall: REJECT_RECOMMENDED (>=1 FAIL), HUMAN_REVIEW (no FAIL, >=1
REVIEW/HUMAN), AUTOMATED_CHECKS_PASSED. REJECT_RECOMMENDED is a
recommendation to the jury, not a rejection.

Assumptions not stated in notices (reported on every result): age measured on
the closing date in completed years, limits inclusive; public holidays not
modelled; mean over the stage scores supplied.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
REVIEW = "REVIEW"
HUMAN = "HUMAN"
NOT_DUE = "NOT_DUE"
NOT_APPLICABLE = "NOT_APPLICABLE"

POLICIES = ("review", "notice", "law")

RULES_DIR = Path(__file__).resolve().parents[2] / "knowledge_base" / "vacancy_rules"
RULES_PATH = RULES_DIR / "hngv_2026_vacancy_rules.json"      # default profile (kept for v1 callers)
LAW_PATH = RULES_DIR / "reference_law_baseline.json"

_CACHE = {}


# ------------------------------------------------------------ loading

def _read(path):
    path = Path(path)
    key = str(path.resolve())
    if key not in _CACHE:
        with open(path, encoding="utf-8") as f:
            _CACHE[key] = json.load(f)
    return _CACHE[key]


def load_rules(path=None):
    """One profile file (default: the HNGV 2026 file)."""
    return _read(path or RULES_PATH)


def load_law(path=None):
    """Reference-law constraints (the statutes in the RAG corpus)."""
    return _read(path or LAW_PATH)["constraints"]


def list_rule_files(directory=None):
    """Profile files = *.json in the folder (not recursive) with a 'vacancies' list."""
    found = []
    for p in sorted(Path(directory or RULES_DIR).glob("*.json")):
        try:
            if isinstance(_read(p).get("vacancies"), list):
                found.append(p)
        except (ValueError, OSError):
            continue
    return found


def get_vacancy(code, path=None):
    """Find a vacancy by code. With `path`, only that file; otherwise every profile file."""
    files = [Path(path)] if path else list_rule_files()
    for f in files:
        for v in _read(f).get("vacancies", []):
            if v["code"] == code:
                return v
    raise KeyError(f"Unknown vacancy code: {code}")


def list_vacancies(path=None):
    """Codes of the vacancies in one profile file, or in every profile file."""
    files = [Path(path)] if path else list_rule_files()
    return [v["code"] for f in files for v in _read(f).get("vacancies", [])]


def find_vacancy(code):
    """(vacancy, profile_path) searched over every profile file in RULES_DIR.

    Raises KeyError if absent and ValueError if two files define the same code
    (so a job is never silently evaluated against the wrong rules).
    """
    hits = [(v, f) for f in list_rule_files() for v in _read(f).get("vacancies", []) if v["code"] == code]
    if not hits:
        raise KeyError(f"Unknown vacancy code: {code}")
    if len(hits) > 1:
        raise ValueError(f"Vacancy code {code} is defined in several profile files: "
                         + ", ".join(str(f) for _, f in hits))
    return hits[0]


# ---------------------------------------------------------------- helpers

def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def age_in_years(date_of_birth, reference_date):
    dob = _to_date(date_of_birth)
    ref = _to_date(reference_date)
    years = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        years -= 1
    return years


def _add_months(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError("invalid date")


def full_months(start, end_inclusive):
    """Completed calendar months between start and end (end inclusive)."""
    s = _to_date(start)
    e = _to_date(end_inclusive) + timedelta(days=1)
    if e <= s:
        return 0
    months = (e.year - s.year) * 12 + (e.month - s.month)
    if _add_months(s, months) > e:
        months -= 1
    return max(months, 0)


def _merge_intervals(intervals):
    ivs = sorted((_to_date(a), _to_date(b)) for a, b in intervals)
    merged = []
    for a, b in ivs:
        if merged and a <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def months_of_experience(entries, field=None, facility=None):
    """Total completed months over merged (non-overlapping) intervals."""
    chosen = []
    for e in entries or []:
        if field and str(e.get("field", "")).strip().lower() != field.lower():
            continue
        if facility and str(e.get("facility_type", "")).strip().lower() != facility.lower():
            continue
        chosen.append((e["start"], e["end"]))
    return sum(full_months(a, b) for a, b in _merge_intervals(chosen))


def _r(rule_id, outcome, message, evidence=None, conflict=None):
    out = {"rule_id": rule_id, "outcome": outcome, "message": message, "evidence": evidence or {}}
    if conflict:
        out["conflict"] = conflict
    return out


def _na(rule_id):
    return _r(rule_id, NOT_APPLICABLE, "Rule not defined in this job profile.")


def _dual(rule_id, notice_ok, law_ok, ok_msg, fail_msg, notice_value, law_value, citation,
          policy, evidence, conflicts, topic):
    """Resolve a check evaluated under the notice and under the reference law."""
    if law_ok is None or notice_ok == law_ok:
        return _r(rule_id, PASS if notice_ok else FAIL, ok_msg if notice_ok else fail_msg, evidence)
    conflict = {"rule_id": rule_id, "topic": topic, "notice": notice_value, "law": law_value,
                "citation": citation, "notice_outcome": PASS if notice_ok else FAIL,
                "law_outcome": PASS if law_ok else FAIL, "policy": policy}
    conflicts.append(conflict)
    if policy == "notice":
        return _r(rule_id, PASS if notice_ok else FAIL, ok_msg if notice_ok else fail_msg,
                  evidence, conflict)
    if policy == "law":
        return _r(rule_id, PASS if law_ok else FAIL,
                  f"(law reading) {ok_msg if law_ok else fail_msg}", evidence, conflict)
    return _r(rule_id, REVIEW,
              f"Notice and reference law disagree ({topic}): notice -> "
              f"{'PASS' if notice_ok else 'FAIL'}, law -> {'PASS' if law_ok else 'FAIL'}. "
              "A person must decide.", evidence, conflict)


# ------------------------------------------------------------ rule checks

def check_r01_citizenship(vac, cand):
    req = vac["requirements"].get("R01")
    if req is None:
        return _na("R01")
    docs = cand.get("documents", {})
    problems, ok = [], []
    for key in req["proof_documents"]:
        d = docs.get(key)
        if not d or not d.get("present"):
            problems.append(f"{key} missing")
        elif d.get("valid") is False:
            problems.append(f"{key} not valid")
        else:
            ok.append(key)
    if problems:
        return _r("R01", FAIL, "Citizenship proof incomplete: " + "; ".join(problems), {"ok": ok})
    return _r("R01", PASS, "ID card, voter card and birth certificate present and valid.", {"ok": ok})


def check_r02_age(vac, cand, reference_date, assumptions, law, policy, conflicts):
    req = vac["requirements"].get("R02")
    law_only = False
    if req is None:
        if not law.get("age"):
            return _na("R02")
        # the law applies to every job even if the profile adds no age rule
        req = {"min_age": law["age"]["min"], "max_age": law["age"]["max"]}
        law_only = True
    if not cand.get("date_of_birth"):
        return _r("R02", REVIEW, "Date of birth not provided.")
    ref = _to_date(reference_date or req.get("default_reference_date"))
    if ref is None:
        return _r("R02", REVIEW, "No reference date for age (none given, none in the profile).")
    age = age_in_years(cand["date_of_birth"], ref)
    assumptions.append(
        f"R02: age measured on {ref.isoformat()} in completed years, limits inclusive "
        "(the notice does not state the reference date)."
    )
    ev = {"age": age, "reference_date": ref.isoformat(), "min": req["min_age"], "max": req["max_age"]}
    if law_only:
        ev["source"] = "reference law only (profile declares no age rule)"
    notice_ok = req["min_age"] <= age <= req["max_age"]
    law_age = law.get("age")
    law_ok = None
    if law_age:
        law_ok = law_age["min"] <= age <= law_age["max"]
        ev["law_min"], ev["law_max"] = law_age["min"], law_age["max"]
    return _dual(
        "R02", notice_ok, law_ok,
        f"Age {age} is within {req['min_age']}-{req['max_age']}.",
        f"Age {age} is outside {req['min_age']}-{req['max_age']}.",
        f"{req['min_age']}-{req['max_age']}",
        f"{law_age['min']}-{law_age['max']}" if law_age else None,
        law_age["citation"] if law_age else None,
        policy, ev, conflicts, "age range")


def check_r03_education(vac, cand):
    req = vac["requirements"].get("R03")
    if req is None:
        return _na("R03")
    rank = req["level_rank"]
    level = str(cand.get("education_level", "")).strip().lower()
    field = str(cand.get("education_field", "")).strip().lower()
    ev = {"required_level": req["required_level"], "candidate_level": level or None,
          "accepted_fields": req["accepted_fields"], "candidate_field": field or None}
    if level not in rank:
        return _r("R03", REVIEW, "Education level missing or not recognised.", ev)
    if rank[level] < rank[req["required_level"]]:
        return _r("R03", FAIL, f"Level {level} is below required {req['required_level']}.", ev)
    notes = []
    outcome = PASS
    if rank[level] > rank[req["required_level"]]:
        outcome = REVIEW
        notes.append("level is higher than required (notice is silent on over-qualification)")
    if field not in [f.lower() for f in req["accepted_fields"]]:
        outcome = REVIEW
        notes.append("field of study is not in the accepted list (needs a person / mapping list)")
    if cand.get("diploma_legalised") is not True:
        outcome = REVIEW
        notes.append("MESCC legalisation not confirmed")
    flags = vac.get("verification", {}).get("flags") or []
    if any("education text" in x for x in flags):
        outcome = REVIEW
        notes.append("notice education text is inconsistent; check the PDF")
    if outcome == PASS:
        return _r("R03", PASS, "Level, field and legalisation match.", ev)
    return _r("R03", outcome, "; ".join(notes) + ".", ev)


def check_r04_experience(vac, cand):
    req = vac["requirements"].get("R04")
    if req is None:
        return _na("R04")
    entries = cand.get("work_history", [])
    exact = months_of_experience(entries, field=req["field"], facility=req.get("facility"))
    anyfield = months_of_experience(entries)
    ev = {"required_months": req["min_months"], "matching_months": exact, "all_months": anyfield}
    if exact >= req["min_months"]:
        return _r("R04", PASS, f"{exact} month(s) of matching experience.", ev)
    if anyfield < req["min_months"]:
        return _r("R04", FAIL,
                  f"Only {anyfield} month(s) of experience in total; {req['min_months']} required.", ev)
    return _r("R04", REVIEW,
              "Enough months in total but not clearly in the required field or facility; needs a person.", ev)


def _doc_check(rule_id, vac, cand, label):
    req = vac["requirements"].get(rule_id)
    if req is None:
        return _na(rule_id)
    d = cand.get("documents", {}).get(req["document"])
    if not d or not d.get("present"):
        return _r(rule_id, REVIEW, f"{label} not yet provided (stage when due: {req.get('due_stage', 'not stated')}).")
    if d.get("valid") is False:
        return _r(rule_id, FAIL, f"{label} is not valid.")
    return _r(rule_id, PASS, f"{label} present and valid (content checked by a person).")


def check_r06_medical(vac, cand, stage):
    req = vac["requirements"].get("R06")
    if req is None:
        return _na("R06")
    if stage != req.get("due_stage", "interview"):
        return _r("R06", NOT_DUE, f"Medical certificate is due at the {req.get('due_stage', 'interview')} stage.")
    return _doc_check("R06", vac, cand, "Medical certificate")


def check_r09_submission(vac, cand, assumptions):
    req = vac["requirements"].get("R09")
    if req is None:
        return _na("R09")
    problems = []
    submitted = cand.get("documents", {})
    cv_lists = cand.get("cv_lists_training_certificates", True)
    missing = []
    for item in req["items"]:
        if item["kind"] != "document":
            continue
        if item.get("required_if") == "cv_lists_training_certificates" and not cv_lists:
            continue
        key = item["key"]
        d = submitted.get(key)
        if key == "diploma_legalised" and not d:
            d = submitted.get("diploma")
        if not d or not d.get("present"):
            missing.append(item["no"])
    if missing:
        problems.append("missing item(s) " + ", ".join(str(m) for m in missing))
    ts = cand.get("submission_datetime")
    if ts is None:
        problems.append("submission timestamp not provided")
    else:
        dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        d0 = dt.date()
        start, end = _to_date(req["window_start"]), _to_date(req["window_end"])
        if not (start <= d0 <= end):
            problems.append(f"submitted on {d0.isoformat()}, outside {start}..{end}")
        elif req["weekdays_only"] and d0.weekday() >= 5:
            problems.append(f"submitted on a weekend ({d0.isoformat()})")
        else:
            t = dt.time()
            inside = any(time.fromisoformat(a) <= t <= time.fromisoformat(b) for a, b in req["hours"])
            if not inside:
                problems.append(f"submitted at {t.strftime('%H:%M')}, outside working hours")
        assumptions.append("R09: public holidays are not modelled; only weekdays and the stated hours.")
    if cand.get("submission_place_ok") is False:
        problems.append("not submitted at the stated place")
    if problems:
        return _r("R09", FAIL, "; ".join(problems) + ".", {"missing_items": missing})
    return _r("R09", PASS, "Complete submission within the period and hours.", {})


# ------------------------------------------------------------- entry points

def _resolve(vacancy_code, vacancy, rules_path):
    if vacancy is not None:
        return vacancy
    if vacancy_code is None:
        raise ValueError("give a vacancy_code or a vacancy dict")
    return get_vacancy(vacancy_code, rules_path)


def _law_or_refuse(law, allow_no_law):
    law = load_law() if law is None else law
    if not law and not allow_no_law:
        raise ValueError("The reference law is mandatory for every civil-service job; "
                         "pass allow_no_law=True only for a what-if run.")
    return law


def _check_policy(policy):
    if policy not in POLICIES:
        raise ValueError(f"conflict_policy must be one of {POLICIES}")


def evaluate_vacancy_eligibility(candidate, vacancy_code=None, reference_date=None,
                                 stage="document_assessment", rules_path=None,
                                 vacancy=None, law=None, conflict_policy="review", allow_no_law=False):
    """Run the automatable checks for one candidate on one job profile.

    The reference law is always applied. Passing `law={}` is refused unless
    `allow_no_law=True` (what-if runs only).
    """
    _check_policy(conflict_policy)
    vac = _resolve(vacancy_code, vacancy, rules_path)
    law = _law_or_refuse(law, allow_no_law)
    assumptions, conflicts = [], []
    req = vac["requirements"]
    results = [
        check_r01_citizenship(vac, candidate),
        check_r02_age(vac, candidate, reference_date, assumptions, law, conflict_policy, conflicts),
        check_r03_education(vac, candidate),
        check_r04_experience(vac, candidate),
    ]
    if "R05" in req:
        results.append(_r(
            "R05", HUMAN, "Language mastery is assessed by people (no test or threshold in the notice).",
            {"requirement": req["R05"].get("languages"),
             "law_min_official_languages": (law.get("language") or {}).get("min_official_languages")}))
    else:
        results.append(_na("R05"))
    results += [
        check_r06_medical(vac, candidate, stage),
        _doc_check("R07", vac, candidate, "Good-conduct certificate"),
        _doc_check("R08", vac, candidate, "Professional card (MdS)"),
        check_r09_submission(vac, candidate, assumptions),
    ]
    if "R14" in req:
        results.append(_r("R14", HUMAN, "Criteria for the document-assessment stage are not stated in the "
                          "notice (accountability gap).", {}))
    else:
        results.append(_na("R14"))
    outcomes = {r["outcome"] for r in results}
    if not law:
        assumptions.append("WARNING: reference law switched off (what-if run); not a valid eligibility result.")
    if FAIL in outcomes:
        overall = "REJECT_RECOMMENDED"
    elif outcomes & {REVIEW, HUMAN} or not law:
        overall = "HUMAN_REVIEW"
    else:
        overall = "AUTOMATED_CHECKS_PASSED"
    return {
        "vacancy": vac["code"],
        "law_applied": bool(law),
        "stage": stage,
        "overall": overall,
        "decision_authority": "jury",
        "conflict_policy": conflict_policy,
        "rules": results,
        "failed_rule_ids": [r["rule_id"] for r in results if r["outcome"] == FAIL],
        "review_rule_ids": [r["rule_id"] for r in results if r["outcome"] in (REVIEW, HUMAN)],
        "not_applicable_rule_ids": [r["rule_id"] for r in results if r["outcome"] == NOT_APPLICABLE],
        "law_conflicts": conflicts,
        "assumptions": sorted(set(assumptions)),
        "rules_status": vac.get("verification", {}).get("status", "unknown"),
    }


def weighted_written_score(general, specific, vacancy_code=None, rules_path=None, vacancy=None):
    """R13: written test = general x w1 + specific x w2 (scores on 0-100).

    With no job named the HNGV default 25/75 is used. With a job named, its own
    weights are used and a job without R13 raises ValueError (no silent default).
    """
    wg, ws = 0.25, 0.75
    if vacancy is not None or vacancy_code:
        v = _resolve(vacancy_code, vacancy, rules_path)
        r13 = v["requirements"].get("R13")
        if not r13:
            raise ValueError(f"{v['code']} defines no R13 weights; refusing to assume 25/75")
        wg, ws = r13["general_weight"], r13["specific_weight"]
    return round(general * wg + specific * ws, 4)


def evaluate_stage_progress(vacancy_code=None, written_score=None, interview_score=None,
                            document_stage_passed=None, document_stage_score=None,
                            rules_path=None, statute_strict=False, vacancy=None, law=None,
                            conflict_policy="review", allow_no_law=False):
    """R10-R12: sequential eliminatory stages, pass mark, final = mean.

    Notice reading: score >= mark passes. Law reading (Decree-Law 34/2008
    Art. 35(1)): score <= threshold is disqualified. They differ exactly at
    the boundary; by default that is REVIEW. `statute_strict=True` is kept as
    an alias for conflict_policy="law".
    """
    if statute_strict:
        conflict_policy = "law"
    _check_policy(conflict_policy)
    vac = _resolve(vacancy_code, vacancy, rules_path)["requirements"]
    law = _law_or_refuse(law, allow_no_law)
    law_pm = law.get("pass_mark")
    r11, r12 = vac.get("R11"), vac.get("R12")
    out = {"vacancy": (vacancy or {}).get("code", vacancy_code), "rules": [], "law_conflicts": [],
           "conflict_policy": conflict_policy, "decision_authority": "jury",
           "assumptions": ["R12: mean over the stage scores supplied; how stage I is scored is not stated (R14)."]}
    add = out["rules"].append

    def judge(rule_id, score, mark, label):
        notice_ok = score >= mark
        law_ok = (score > law_pm["threshold"]) if law_pm else None
        res = _dual(rule_id, notice_ok, law_ok,
                    f"{label} {score} passes (notice: >= {mark}).",
                    f"{label} {score} does not pass (notice: >= {mark}).",
                    f">= {mark}", f"> {law_pm['threshold']}" if law_pm else None,
                    law_pm["citation"] if law_pm else None, conflict_policy,
                    {"score": score}, out["law_conflicts"], "pass-mark boundary")
        add(res)
        return res["outcome"]

    if document_stage_passed is None:
        add(_r("R10", HUMAN, "Stage I result not supplied (criteria not stated, R14)."))
        out["next_stage"], out["final_score"] = None, None
        return out
    if not document_stage_passed:
        add(_r("R10", FAIL, "Eliminated at stage I (document assessment)."))
        out["next_stage"], out["final_score"] = None, None
        return out
    add(_r("R10", PASS, "Passed stage I; proceeds to the written test."))
    if written_score is None:
        out["next_stage"], out["final_score"] = "written_test", None
        return out
    if r11:
        oc = judge("R11", written_score, r11["written_min_score"], "Written score")
    elif law_pm:
        # the profile adds no pass mark: the law still disqualifies 60 or less in an eliminatory phase
        ok = written_score > law_pm["threshold"]
        add(_r("R11", PASS if ok else FAIL,
               f"(reference law only) Written score {written_score} "
               f"{'passes' if ok else 'is disqualified'}: {law_pm['citation']}.", {"score": written_score}))
        oc = PASS if ok else FAIL
    else:
        add(_na("R11"))
        oc = PASS
    if oc != PASS:
        out["next_stage"] = "HUMAN_DECISION" if oc == REVIEW else None
        out["final_score"] = None
        return out
    if interview_score is None:
        out["next_stage"], out["final_score"] = "interview", None
        return out
    scores = [written_score, interview_score]
    if document_stage_score is not None:
        scores.insert(0, document_stage_score)
    final = round(sum(scores) / len(scores), 4)
    out["final_score"], out["scores_used"], out["next_stage"] = final, scores, None
    if r12:
        judge("R12", final, r12["final_pass_score"], "Final score")
    else:
        add(_na("R12"))
    return out


def audit_vacancy_against_law(vacancy, law=None):
    """Static differences between a job profile and the reference law (no candidate needed)."""
    law = load_law() if law is None else law
    req = vacancy["requirements"]
    diffs = []

    def add(topic, notice, lawv, cite, note):
        diffs.append({"topic": topic, "notice": notice, "law": lawv, "citation": cite, "note": note})

    a, la = req.get("R02"), law.get("age")
    if a and la and (a["min_age"], a["max_age"]) != (la["min"], la["max"]):
        stricter = a["min_age"] > la["min"] or a["max_age"] < la["max"]
        add("age range", f"{a['min_age']}-{a['max_age']}", f"{la['min']}-{la['max']}", la["citation"],
            "notice is stricter than the law" if stricter else "notice is looser than the law")
    r11, pm = req.get("R11"), law.get("pass_mark")
    if r11 and pm:
        if r11["written_min_score"] != pm["threshold"]:
            add("pass mark", r11["written_min_score"], pm["threshold"], pm["citation"], "different threshold")
        else:
            add("pass-mark boundary", f">= {r11['written_min_score']} passes",
                f"<= {pm['threshold']} disqualified", pm["citation"],
                "at the threshold value the notice passes and the law disqualifies")
    r05, lg = req.get("R05"), law.get("language")
    if r05 and lg:
        add("official languages", r05.get("languages"), f"at least {lg['min_official_languages']} official language",
            lg["citation"], "notice wording differs; check whether it is stricter than the law")
    pr = vacancy.get("probation_years")
    if pr is not None and law.get("probation_months") and pr * 12 != law["probation_months"]["value"]:
        add("probation", f"{pr * 12} months", f"{law['probation_months']['value']} months",
            law["probation_months"]["citation"], "different length")
    if "appeal" not in json.dumps(vacancy).lower() and law.get("appeal_working_days"):
        add("appeal clause", "not mentioned in the notice", f"{law['appeal_working_days']['value']} working days",
            law["appeal_working_days"]["citation"], "notice is silent; the statute applies")
    return diffs


def vacancy_to_job_requirement(vacancy_code=None, rules_path=None, vacancy=None):
    """Adapter to the dict shape used by recruitment_rules.evaluate_recruitment_rules.

    Lets the graded (embedding-based) engine and this deterministic engine run
    side by side on the same job. Not wired into the live pipeline.
    """
    vac = _resolve(vacancy_code, vacancy, rules_path)
    r = vac["requirements"]
    return {
        "job_title": vac["job_title"],
        "education": (r.get("R03") or {}).get("education_text", ""),
        "years_experience": ((r.get("R04") or {}).get("min_months", 0)) / 12.0,
        "languages": [],
        "certifications": [],
        "skills": [],
    }
