"""
Generate RAG corpus documents (Markdown) from ANY vacancy-rules pack.

    python -m rag.build_vacancy_corpus --src knowledge_base/vacancy_rules/<pack>.json \\
        --out knowledge_base/documents_staging/<name> [--vacancy CODE ...] [--prefix name]

* Opt-in: it only writes the vacancies you name with --vacancy (or all of a
  pack with --all). Nothing is generated for new jobs by itself.
* Flexible: a section is written only if the vacancy declares the matching
  rule (R01..R14). Institution-specific wording (programme of subjects,
  where results are published, ...) lives in the pack's "corpus_notes"
  (pack level) and in a vacancy's own "corpus_notes", with {code} and
  {field} placeholders.
* Output goes to a staging folder; copy files into knowledge_base/documents/
  and rebuild the index yourself (see docs/HNGV_INTEGRATION.md).

Every content line carries the vacancy code because rag/text_splitter.py
(700 characters) can cut a section anywhere. Standard library only.
"""

import argparse
import json
from pathlib import Path

LEVEL_TEXT = {
    "licenciatura": "Licenciatura (bachelor's degree)",
    "bacharelatu": "Bacharelatu (3-year diploma)",
}
DOC_TEXT = {
    "bi_card": "a valid identity card (Bilhete de Identidade)",
    "voter_card": "a voter card",
    "birth_certificate": "an RDTL birth certificate",
}


def _slug(text):
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def vacancy_lines(v, pack):
    r = v.get("requirements", {})
    c = v["code"]
    t = v["job_title"]
    inst = v.get("institution") or pack.get("institution_label") or "the institution"
    field = r.get("R04", {}).get("field", t)
    L = []
    a = L.append
    a(f"# Vacancy notice {c} - {t}")
    a("")
    src = v.get("source_file")
    a(f"Source: public notice {src} ({pack.get('corpus_source_label', 'public vacancy notice')}). "
      + ("Content was extracted by OCR and is not yet verified against the PDF."
         if v.get("verification", {}).get("status") != "human_verified"
         else "Content was verified against the original notice."))
    a(f"Authority note for vacancy {c}: this notice is a secondary source; where it differs from the statutes "
      "in the reference law corpus, the statute is the reference and the difference must be flagged, not silently followed. "
      f"The specific rules of vacancy {c} are additions that apply to this vacancy only; the reference law applies to every civil service vacancy.")
    a("")
    a("## Position")
    a(f"Vacancy {c} is for the position {t} at {inst}.")
    if "positions" in v:
        extra = f" in the category {v['category_grade']}" if v.get("category_grade") else ""
        a(f"Vacancy {c} offers {v['positions']} positions{extra}.")
    if "salary_usd" in v:
        a(f"The monthly salary for vacancy {c} is {v['salary_usd']} US dollars.")
    if v.get("appointment"):
        prob = f" with a probation period of {v['probation_years']} year" if v.get("probation_years") else ""
        a(f"Vacancy {c} is a {v['appointment']} appointment{prob}.")
    if v.get("location"):
        a(f"The place of work for vacancy {c} is {v['location']}.")
    if v.get("regime"):
        a(f"Vacancy {c} falls under the {v['regime']}.")

    if "R01" in r or "R02" in r:
        a("")
        a("## Citizenship and age")
    if "R01" in r:
        docs = _join(DOC_TEXT.get(k, k.replace("_", " ")) for k in r["R01"].get("proof_documents", []))
        who = "a citizen" if r["R01"].get("citizen") else "an applicant"
        a(f"For vacancy {c}, the applicant must be {who}" + (f", proven by {docs}." if docs else "."))
    if "R02" in r:
        q = r["R02"]
        a(f"For vacancy {c}, the minimum age is {q['min_age']} years and the maximum age is {q['max_age']} years.")
        g = pack.get("general_regime_reference")
        if g and (g.get("min_age"), g.get("max_age")) != (q["min_age"], q["max_age"]):
            a(f"This {q['min_age']}-{q['max_age']} age range differs from the general public administration "
              f"age range of {g['min_age']}-{g['max_age']} years.")
        if q.get("reference_date_stated") is False:
            a("The notice does not state the date at which age is measured.")

    if "R03" in r:
        q = r["R03"]
        a("")
        a("## Education")
        a(f"For vacancy {c}, the required qualification is: {q['education_text']}.")
        a(f"The required level is {LEVEL_TEXT.get(q['required_level'], q['required_level'])}.")
        if q.get("legalisation_by"):
            a(f"The diploma copy must be legalised by {q['legalisation_by']} and the original must be shown.")
        if any("education text" in x for x in v.get("verification", {}).get("flags", [])):
            a(f"Note: the education text of notice {c} is inconsistent and needs checking against the PDF.")

    if "R04" in r:
        q = r["R04"]
        a("")
        a("## Experience")
        fac = f" in a {q['facility']}" if q.get("facility") else ""
        a(f"For vacancy {c}, the applicant needs at least {q['min_months']:g} months of work experience in {q['field']}{fac}.")

    if "R05" in r:
        a("")
        a("## Language")
        a(f"Language requirement for vacancy {c}: {r['R05'].get('languages')}.")

    others = [k for k in ("R06", "R07", "R08") if k in r]
    if others:
        a("")
        a("## Other mandatory requirements")
        for k in others:
            q = r[k]
            doc = q["document"].replace("_", " ")
            issuer = f" from {q['issuer']}" if q.get("issuer") else ""
            due = q.get("due_stage")
            when = f", presented at the {due} stage" if due and due != "not stated" else ""
            a(f"Vacancy {c} requires: {doc}{issuer}{when}.")

    if "R09" in r:
        q = r["R09"]
        a("")
        a("## Documents to submit and period")
        for i in q.get("items", []):
            a(f"Item {i['no']} for vacancy {c}: {i['text']}.")
        hours = _join(f"{h[0]}-{h[1]}" for h in q.get("hours", []))
        days = " on working days" if q.get("weekdays_only") else ""
        a(f"Documents for vacancy {c} are submitted from {q['window_start']} to {q['window_end']}"
          + (f", between {hours}{days}." if hours else "."))

    if any(k in r for k in ("R10", "R11", "R12", "R13", "R14")):
        a("")
        a("## Selection method and scoring")
    if "R10" in r:
        st = [s.replace("_", " ") for s in r["R10"]["stages"]]
        a(f"The selection for vacancy {c} has {len(st)} sequential stages: {_join(st)}"
          + ("; the process is eliminatory." if r["R10"].get("eliminatory") else "."))
    if "R11" in r:
        a(f"Candidates who pass the written test with a score of {r['R11']['written_min_score']} continue to the next stage.")
    if "R12" in r:
        q = r["R12"]
        a(f"The final classification is the {q.get('method', 'combined score')}, on a scale of 0 to {q['scale_max']} points.")
        a(f"A candidate is considered suitable when the classification is equal to or higher than {q['final_pass_score']} points.")
    if "R13" in r:
        q = r["R13"]
        a(f"The written test content is weighted {round(q['general_weight']*100)}% general subjects and "
          f"{round(q['specific_weight']*100)}% specific subjects.")
    if r.get("R14", {}).get("criteria_stated") is False:
        a("The notice does not say how the document-assessment stage (stage I) is scored or what criteria the jury uses.")

    notes = [n.format(code=c, field=field) for n in pack.get("corpus_notes", []) + v.get("corpus_notes", [])]
    if notes:
        a("")
        a("## Additional notes")
        L.extend(notes)

    out = []
    for ln in L:
        if ln and not ln.startswith("#") and c not in ln:
            ln = f"For vacancy {c}: {ln[0].lower() + ln[1:]}"
        out.append(ln)
    return out


def catalog_lines(pack):
    L = [f"# {pack.get('catalogue_title', 'Vacancy rule catalogue')}", ""]
    if pack.get("catalogue_intro"):
        L += [pack["catalogue_intro"], ""]
    kinds = {"code": "can be coded as a deterministic rule",
             "partial": "can be partly coded but needs a mapping list or document verification",
             "human": "needs human judgement"}
    for rl in pack.get("rules", []):
        L.append(f"Rule {rl['id']}: {rl['summary']}. This rule {kinds[rl['type']]}. Gap or doubt: {rl['gap']}.")
        L.append("")
    if pack.get("catalogue_outro"):
        L.append(pack["catalogue_outro"])
    conflicts = pack.get("statute_conflicts", [])
    if conflicts:
        L += ["", "## Differences between the notices and the reference statutes", ""]
        for c in conflicts:
            L.append(f"Difference on {c['topic']}: the notices say {c['notice']}; the statute says {c['statute']}. "
                     "The statute is the reference law; the notice value must be flagged for a person to decide.")
            L.append("")
    return L


def build(src, out, codes=None, prefix=None, all_vacancies=False):
    pack = json.loads(Path(src).read_text(encoding="utf-8"))
    chosen = [v for v in pack["vacancies"] if all_vacancies or (codes and v["code"] in codes)]
    if not chosen:
        raise SystemExit("No vacancy selected: pass --vacancy CODE (repeatable) or --all.")
    if codes:
        missing = set(codes) - {v["code"] for v in chosen}
        if missing:
            raise SystemExit(f"Unknown vacancy code(s): {sorted(missing)}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    prefix = prefix or _slug(pack.get("dataset", "vacancies"))
    written = []
    for v in chosen:
        name = f"{prefix}_{_slug(v['code'])}_{_slug(v['job_title'].split(' (')[0])}.md"
        (out / name).write_text("\n".join(vacancy_lines(v, pack)) + "\n", encoding="utf-8")
        written.append(name)
    if pack.get("rules"):
        name = f"{prefix}_rule_catalogue.md"
        (out / name).write_text("\n".join(catalog_lines(pack)) + "\n", encoding="utf-8")
        written.append(name)
    if pack.get("overview_text") or len(chosen) > 1:
        name = f"{prefix}_overview.md"
        L = [f"# {pack.get('dataset', 'Vacancies')}: overview table", ""]
        total = sum(v.get("positions", 0) for v in chosen)
        L.append(f"{len(chosen)} vacancy notices were processed, together offering {total} positions.")
        L.append("")
        for v in chosen:
            L.append(f"{v['code']}: {v['job_title']}, {v.get('positions', '?')} positions"
                     + (f", salary {v['salary_usd']} US dollars" if 'salary_usd' in v else "")
                     + (f", category {v['category_grade']}" if v.get('category_grade') else "") + ".")
        if pack.get("overview_text"):
            L += ["", pack["overview_text"]]
        (out / name).write_text("\n".join(L) + "\n", encoding="utf-8")
        written.append(name)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vacancy", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--prefix")
    a = ap.parse_args(argv)
    written = build(a.src, a.out, a.vacancy, a.prefix, a.all)
    print(f"Wrote {len(written)} files to {a.out}")
    for w in written:
        print(" ", w)


if __name__ == "__main__":
    main()
