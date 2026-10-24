"""
Candidate-Document Matching.

For every requirement in the job's structured profile (education,
experience, skills, languages, certifications) decide one of four
statuses and keep the evidence behind it:

    matched | not_matched | insufficient_evidence | needs_human_review

Design rules (see the project task):
  * Rule-based first.  Education levels, languages and certification
    names are compared exactly / by normalised text.  Semantic cases
    (a requirement the rules cannot classify) REUSE the graded level the
    Rule Engine already computed for the same requirement in the same
    run -- no new embedding or LLM call is made here, nothing is read
    or extracted again.
  * A claim made only in the CV is labelled "cv_claim" and is NOT
    verified.  A fact found in a readable supporting document carries
    the document, the quote and the page (when known) and is labelled
    "document_verified".  Both: "cv_claim_and_document_verified".
  * Missing / unreadable / low-quality documents, conflicting values and
    name mismatches never produce an automatic rejection: they produce
    insufficient_evidence or needs_human_review.
  * Nothing is invented: a requirement with no evidence stays without
    evidence.
  * This module is informational.  It does not change eligibility,
    scores, weights or thresholds; the Rule Engine remains the source
    of the existing decision.

Pure Python, no database writes, no network.
"""

import re

from .documents import LEVELS, LEVEL_LABELS, _lines, _norm, level_of
from .models import ApplicationSupportingDocument
from .unified import same_certification

T = ApplicationSupportingDocument

SCHEMA_VERSION = 1

MATCHED = "matched"
NOT_MATCHED = "not_matched"
INSUFFICIENT = "insufficient_evidence"
NEEDS_REVIEW = "needs_human_review"

STATUSES = (MATCHED, NOT_MATCHED, INSUFFICIENT, NEEDS_REVIEW)

BASIS_CV = "cv_claim"
BASIS_DOC = "document_verified"
BASIS_BOTH = "cv_claim_and_document_verified"
BASIS_NONE = "none"

# Graded levels produced by the Rule Engine (ai_engine/services/
# recruitment_rules.py).  Mirrored here as plain strings so this module
# does not import the embedding stack; a regression test asserts they
# stay identical to the Rule Engine's own constants.
PARTIAL = "PARTIAL"
UNKNOWN = "UNKNOWN"
HARD_PASS_LEVELS = {"STRONG_MATCH", "MATCH", "RELATED", "NEAR_REQUIREMENT"}

LEVEL_RANK = {"secondary": 0, "diploma": 1, "bachelor": 2, "master": 3,
              "doctorate": 4}

POLICY_NOTE = (
    "Informational only: this matching does not change the eligibility, "
    "score or recommendation. Missing, unreadable or conflicting "
    "documents are flagged for a human reviewer, never treated as proof "
    "that a candidate lacks a qualification."
)


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------

def _key(text):
    return re.sub(r"[^a-z0-9]+", " ", _norm(text)).strip()


def _dedupe(items):
    seen, out = set(), []
    for item in items or []:
        text = str(item).strip()
        k = _key(text)
        if text and k not in seen:
            seen.add(k)
            out.append(text)
    return out


def _required_level(text):
    """Lowest education level named in a requirement ("at least")."""
    t = _norm(text)
    found = [lv for lv, pat in LEVELS if re.search(pat, t)]
    if not found:
        return None
    return min(found, key=lambda lv: LEVEL_RANK[lv])


def _row(kind, requirement, status, basis, evidence, reason, method="rule"):
    return {
        "requirement_type": kind,
        "requirement": requirement,
        "status": status,
        "basis": basis,
        "verified_by_document": basis in (BASIS_DOC, BASIS_BOTH),
        "method": method,
        "reason": reason,
        "evidence": evidence,
    }


def _cv_evidence(note, quote=None):
    return {"source": "cv", "document": "cv", "document_type": "cv",
            "page": None, "quote": quote, "note": note}


def _doc_evidence(doc, quote, page=None, field=None, note=None):
    return {"source": doc.doc_type, "document_id": doc.pk,
            "document": doc.original_name, "document_type": doc.doc_type,
            "page": page, "quote": quote, "field": field, "note": note}


def _from_unified_evidence(ev):
    return {
        "source": ev.get("document_type"),
        "document_id": ev.get("document_id"),
        "document": ev.get("document"),
        "document_type": ev.get("document_type"),
        "page": ev.get("page"),
        "quote": ev.get("quote"),
        "field": ev.get("field"),
        "note": ev.get("note"),
    }


def _dedupe_evidence(evidence):
    seen, out = set(), []
    for ev in evidence:
        k = (ev.get("document_id"), ev.get("document"),
             _key(ev.get("quote") or ""), ev.get("note"))
        if k not in seen:
            seen.add(k)
            out.append(ev)
    return out


def _word_find(term, text):
    t = _norm(term)
    if len(t) < 3:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])",
                     _norm(text)) is not None


def _search_documents(term, documents, doc_types):
    """
    Exact word-boundary search for `term` in the text of readable
    documents of the given types.  Returns evidence dicts (the whole
    matching line is the quote).  Page is unknown at this point because
    only the joined text is stored.
    """
    hits = []
    for d in documents:
        if d.doc_type not in doc_types or d.status != T.STATUS_PROCESSED:
            continue
        for line in _lines(d.extracted_text or ""):
            if _word_find(term, line):
                hits.append(_doc_evidence(
                    d, line, page=None,
                    note="page not recorded for free-text search"))
                break
    return hits


class _Context:
    """Facts about the documents, derived once per run."""

    def __init__(self, unified, documents):
        self.unified = unified or {}
        self.documents = list(documents or [])
        self.by_id = {d.pk: d for d in self.documents}

        self.unreadable = [
            d for d in self.documents
            if d.status in (T.STATUS_FAILED, T.STATUS_LOW_QUALITY)
        ]
        self.pending = [d for d in self.documents
                        if d.status == T.STATUS_PENDING]

        self.conflicts = self.unified.get("conflicts", []) or []

        # documents whose holder name differs from the applicant: their
        # content is not used as verification
        self.mismatched_ids = set()
        for c in self.conflicts:
            if c.get("type") == "holder_name_mismatch":
                for v in c.get("values", []):
                    if v.get("document_id") is not None:
                        self.mismatched_ids.add(v["document_id"])

    def unreadable_of(self, doc_types):
        return [d for d in self.unreadable if d.doc_type in doc_types]

    def usable(self, doc):
        return (doc.status == T.STATUS_PROCESSED
                and doc.pk not in self.mismatched_ids)

    def has_conflict(self, ctype):
        return any(c.get("type") == ctype for c in self.conflicts)


def _matrix_levels(rule_result):
    out = {}
    for row in (rule_result or {}).get("matrix", []) or []:
        out[row.get("requirement")] = row
    return out


# ---------------------------------------------------------------------
# per-dimension matching
# ---------------------------------------------------------------------

def _match_education(job_profile, profile, ctx, matrix):
    required = (job_profile.get("education") or "").strip()
    if not required:
        return []

    kind = "education"
    entries = ctx.unified.get("education", []) or []
    edu_docs = [d for d in ctx.documents if d.doc_type == T.TYPE_EDUCATION]
    unreadable_edu = [d for d in ctx.unreadable if d.doc_type == T.TYPE_EDUCATION]
    mismatched_edu = [d for d in edu_docs if d.pk in ctx.mismatched_ids]

    cv_entry = next((e for e in entries if "cv" in e.get("sources", [])), None)
    cv_text = (cv_entry or {}).get("statement") or ""
    cv_level = (cv_entry or {}).get("level")

    doc_levels = []
    doc_evidence = []
    for e in entries:
        if "education_certificate" in e.get("sources", []) and e.get("level"):
            # only entries whose document is usable
            ev_docs = {ev.get("document_id") for ev in e.get("evidence", [])
                       if ev.get("document_id") is not None}
            if ev_docs and all(i in ctx.mismatched_ids for i in ev_docs):
                continue
            doc_levels.append(e["level"])
            doc_evidence += [_from_unified_evidence(ev)
                             for ev in e.get("evidence", [])
                             if ev.get("document_id") is not None]

    doc_level = (max(doc_levels, key=lambda lv: LEVEL_RANK[lv])
                 if doc_levels else None)

    evidence_cv = ([_cv_evidence("Education stated in the CV profile.", cv_text)]
                   if cv_text else [])

    req_level = _required_level(required)
    req = f"Education: {required}"

    # -- conflicts / unreliable documents always go to a human --------
    if ctx.has_conflict("education_level_mismatch"):
        return [_row(kind, req, NEEDS_REVIEW, BASIS_NONE,
                     evidence_cv + doc_evidence,
                     "The education level in the CV differs from the "
                     "education certificate.")]
    if mismatched_edu:
        return [_row(kind, req, NEEDS_REVIEW, BASIS_NONE,
                     evidence_cv + doc_evidence,
                     "The name on the education certificate differs from "
                     "the applicant's name.")]

    # -- the rules cannot classify the requirement: reuse the graded
    #    level the Rule Engine already computed (no second embedding) --
    if req_level is None:
        row = matrix.get(f"Education: {required}", {})
        level = row.get("level")
        has_text = bool(cv_text or doc_levels)
        has_doc = bool(doc_levels)
        if level is None or level == UNKNOWN or not has_text:
            status, reason = INSUFFICIENT, (
                "The requirement is free text and no education was "
                "found to compare it with.")
        elif level in HARD_PASS_LEVELS:
            status, reason = MATCHED, (
                f"Semantic match by the Rule Engine ({level}).")
        else:
            status, reason = NEEDS_REVIEW, (
                f"Free-text requirement; semantic level {level} is not "
                "conclusive, so a reviewer should decide.")
        basis = (BASIS_BOTH if has_doc and cv_text else
                 BASIS_DOC if has_doc else
                 BASIS_CV if cv_text else BASIS_NONE)
        if status != MATCHED:
            basis = BASIS_NONE if status == INSUFFICIENT else basis
        return [_row(kind, req, status, basis,
                     _dedupe_evidence(evidence_cv + doc_evidence),
                     reason, method="semantic_from_rule_engine")]

    need = LEVEL_RANK[req_level]
    req_label = LEVEL_LABELS[req_level]

    # -- a readable certificate states a level -------------------------
    if doc_level is not None:
        if LEVEL_RANK[doc_level] >= need:
            both = cv_level is not None and LEVEL_RANK[cv_level] >= need
            return [_row(
                kind, req, MATCHED, BASIS_BOTH if both else BASIS_DOC,
                _dedupe_evidence((evidence_cv if both else []) + doc_evidence),
                f"{LEVEL_LABELS[doc_level]} found in the education "
                f"certificate (required: {req_label} or higher).")]
        return [_row(
            kind, req, NOT_MATCHED, BASIS_DOC,
            _dedupe_evidence(evidence_cv + doc_evidence),
            f"The education certificate shows {LEVEL_LABELS[doc_level]}; "
            f"required: {req_label} or higher.")]

    # -- no usable certificate level ----------------------------------
    if unreadable_edu:
        return [_row(
            kind, req, NEEDS_REVIEW, BASIS_NONE, evidence_cv,
            "The education certificate could not be read reliably; the "
            "CV statement is unverified.")]
    if edu_docs and any(d.status == T.STATUS_PROCESSED for d in edu_docs):
        return [_row(
            kind, req, NEEDS_REVIEW, BASIS_NONE, evidence_cv,
            "The education certificate was read but no education level "
            "could be recognised in it.")]
    if edu_docs:  # still pending
        return [_row(
            kind, req, INSUFFICIENT, BASIS_NONE, evidence_cv,
            "The education certificate has not been read yet.")]

    if cv_level is not None:
        if LEVEL_RANK[cv_level] >= need:
            return [_row(
                kind, req, MATCHED, BASIS_CV, evidence_cv,
                f"The CV states {LEVEL_LABELS[cv_level]}; not verified by "
                "a document.")]
        return [_row(
            kind, req, NOT_MATCHED, BASIS_CV, evidence_cv,
            f"The CV states {LEVEL_LABELS[cv_level]}; required: "
            f"{req_label} or higher. No certificate was provided.")]

    return [_row(kind, req, INSUFFICIENT, BASIS_NONE, evidence_cv,
                 "No education level was found in the CV or in any "
                 "document.")]


def _match_experience(job_profile, profile, ctx, matrix):
    try:
        required = float(job_profile.get("years_experience") or 0)
    except (TypeError, ValueError):
        required = 0
    if required <= 0:
        return []

    try:
        years = float(profile.get("years_experience") or 0)
    except (TypeError, ValueError):
        years = 0

    kind = "experience"
    req_label = f"Experience: {required:g}+ years"
    row = matrix.get(f"Experience: {required}+ years", {})
    level = row.get("level")

    evidence = [_cv_evidence(
        f"{years:g} total years from the CV profile extraction.")]
    note = ("Work experience is taken from the CV only; the uploaded "
            "documents do not verify it.")

    if level in HARD_PASS_LEVELS:
        return [_row(kind, req_label, MATCHED, BASIS_CV, evidence,
                     f"CV states enough experience ({level}). {note}",
                     method="semantic_from_rule_engine")]
    if years <= 0:
        return [_row(kind, req_label, INSUFFICIENT, BASIS_NONE, evidence,
                     "No years of experience could be read from the CV.")]
    if level == PARTIAL:
        return [_row(kind, req_label, NEEDS_REVIEW, BASIS_CV, evidence,
                     "Experience is below the requirement but not "
                     f"negligible ({level}); a reviewer should decide. "
                     + note,
                     method="semantic_from_rule_engine")]
    return [_row(kind, req_label, NOT_MATCHED, BASIS_CV, evidence,
                 f"CV states {years:g} years; required {required:g}+. "
                 + note, method="semantic_from_rule_engine")]


def _match_skills(job_profile, profile, ctx, matrix):
    rows = []
    cv_skills = profile.get("skills", []) or []
    for skill in _dedupe(job_profile.get("skills")):
        kind, req = "skill", f"Skill: {skill}"
        row = matrix.get(f"Skill: {skill}", {})
        level = row.get("level")
        cv_ok = level in HARD_PASS_LEVELS
        cv_ev = ([_cv_evidence(
            "Skill listed in the CV profile"
            + (f" (matched '{row.get('matched_candidate_skill')}')"
               if row.get("matched_candidate_skill") else "") + ".")]
                 if cv_ok else [])
        doc_ev = _search_documents(
            skill, ctx.documents,
            (T.TYPE_CERTIFICATE, T.TYPE_EDUCATION))
        doc_ev = [e for e in doc_ev
                  if e.get("document_id") not in ctx.mismatched_ids]

        if cv_ok and doc_ev:
            rows.append(_row(kind, req, MATCHED, BASIS_BOTH,
                             _dedupe_evidence(cv_ev + doc_ev),
                             "Listed in the CV and found in a document."))
        elif doc_ev:
            rows.append(_row(kind, req, MATCHED, BASIS_DOC,
                             _dedupe_evidence(doc_ev),
                             "Found in a supporting document; not listed "
                             "in the CV skills."))
        elif cv_ok:
            rows.append(_row(
                kind, req, MATCHED, BASIS_CV, cv_ev,
                f"Listed in the CV ({level}); not verified by a document.",
                method="exact" if level in ("STRONG_MATCH",)
                else "semantic_from_rule_engine"))
        elif level == PARTIAL:
            rows.append(_row(
                kind, req, NEEDS_REVIEW, BASIS_NONE, [],
                "Only a partial semantic similarity to a CV skill; a "
                "reviewer should decide.",
                method="semantic_from_rule_engine"))
        elif not cv_skills:
            rows.append(_row(kind, req, INSUFFICIENT, BASIS_NONE, [],
                             "No skills could be read from the CV."))
        elif ctx.unreadable:
            rows.append(_row(
                kind, req, NEEDS_REVIEW, BASIS_NONE, [],
                "Not found in the CV, and a supporting document could not "
                "be read reliably, so absence is not established."))
        else:
            rows.append(_row(kind, req, NOT_MATCHED, BASIS_NONE, [],
                             "Not found in the CV skills or in any readable "
                             "document."))
    return rows


def _match_languages(job_profile, profile, ctx, matrix):
    rows = []
    cv_languages = profile.get("languages", []) or []
    for language in _dedupe(job_profile.get("languages")):
        kind, req = "language", f"Language: {language}"
        listed = [l for l in cv_languages if _key(l) == _key(language)]
        doc_ev = [e for e in _search_documents(
            language, ctx.documents, (T.TYPE_CERTIFICATE,))
            if e.get("document_id") not in ctx.mismatched_ids]
        cv_ev = ([_cv_evidence(f"Language listed in the CV: {listed[0]}.")]
                 if listed else [])

        if listed and doc_ev:
            rows.append(_row(kind, req, MATCHED, BASIS_BOTH,
                             _dedupe_evidence(cv_ev + doc_ev),
                             "Listed in the CV and named in a certificate."))
        elif listed:
            rows.append(_row(kind, req, MATCHED, BASIS_CV, cv_ev,
                             "Listed in the CV; not verified by a document."))
        elif doc_ev:
            rows.append(_row(kind, req, MATCHED, BASIS_DOC, doc_ev,
                             "Named in a certificate; not listed in the CV."))
        elif not cv_languages:
            rows.append(_row(kind, req, INSUFFICIENT, BASIS_NONE, [],
                             "No languages could be read from the CV."))
        elif ctx.unreadable_of((T.TYPE_CERTIFICATE,)):
            rows.append(_row(kind, req, NEEDS_REVIEW, BASIS_NONE, [],
                             "Not listed in the CV, and a certificate could "
                             "not be read reliably."))
        else:
            rows.append(_row(kind, req, NOT_MATCHED, BASIS_NONE, [],
                             "Not listed in the CV and not named in any "
                             "readable certificate."))
    return rows


def _match_certifications(job_profile, profile, ctx, matrix):
    rows = []
    certs = ctx.unified.get("certifications", []) or []
    cert_docs = [d for d in ctx.documents if d.doc_type == T.TYPE_CERTIFICATE]
    cert_conflicts = [c for c in ctx.conflicts
                      if c.get("type") == "certification_detail_mismatch"]

    for name in _dedupe(job_profile.get("certifications")):
        kind, req = "certification", f"Certification: {name}"
        found = next((c for c in certs if same_certification(name, c["name"])),
                     None)

        if found is not None:
            doc_sources = [s for s in found.get("sources", []) if s != "cv"]
            evidence = _dedupe_evidence(
                [_from_unified_evidence(ev) for ev in found.get("evidence", [])])
            conflicted = any(c.get("certification") == found["name"]
                             for c in cert_conflicts)
            holder_bad = any(
                ev.get("document_id") in ctx.mismatched_ids
                for ev in found.get("evidence", []))
            if conflicted or holder_bad:
                rows.append(_row(
                    kind, req, NEEDS_REVIEW, BASIS_NONE, evidence,
                    "Conflicting details between documents, or the name on "
                    "the certificate differs from the applicant's name."))
            elif doc_sources and "cv" in found.get("sources", []):
                rows.append(_row(kind, req, MATCHED, BASIS_BOTH, evidence,
                                 "Listed in the CV and confirmed by a "
                                 "certificate."))
            elif doc_sources:
                rows.append(_row(kind, req, MATCHED, BASIS_DOC, evidence,
                                 "Confirmed by an uploaded certificate."))
            else:
                rows.append(_row(kind, req, MATCHED, BASIS_CV, evidence,
                                 "Listed in the CV; no certificate was "
                                 "uploaded for it."))
            continue

        if ctx.unreadable_of((T.TYPE_CERTIFICATE, T.TYPE_SUPPORTING)):
            rows.append(_row(kind, req, NEEDS_REVIEW, BASIS_NONE, [],
                             "Not found, and a certificate could not be read "
                             "reliably, so absence is not established."))
        elif not cert_docs:
            rows.append(_row(kind, req, INSUFFICIENT, BASIS_NONE, [],
                             "Not listed in the CV and no certificate was "
                             "uploaded (certificates are optional)."))
        elif all(d.status == T.STATUS_PROCESSED for d in cert_docs):
            rows.append(_row(kind, req, NOT_MATCHED, BASIS_NONE, [],
                             "Not listed in the CV and not found in the "
                             f"{len(cert_docs)} uploaded certificate(s)."))
        else:
            rows.append(_row(kind, req, INSUFFICIENT, BASIS_NONE, [],
                             "Certificates have not all been read yet."))
    return rows


# ---------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------

def match_requirements(job_profile, profile, unified, rule_result,
                       documents):
    """
    job_profile: structured job profile (application.job.ai_job_profile)
    profile:     candidate profile as given to the Rule Engine
    unified:     talent.unified.build_unified() result (may be {})
    rule_result: evaluate_recruitment_rules() result (its matrix is reused)
    documents:   iterable of ApplicationSupportingDocument rows

    Returns a JSON-serialisable dict.
    """

    job_profile = job_profile or {}
    profile = profile or {}
    ctx = _Context(unified, documents)
    matrix = _matrix_levels(rule_result)

    rows = []
    rows += _match_education(job_profile, profile, ctx, matrix)
    rows += _match_experience(job_profile, profile, ctx, matrix)
    rows += _match_skills(job_profile, profile, ctx, matrix)
    rows += _match_languages(job_profile, profile, ctx, matrix)
    rows += _match_certifications(job_profile, profile, ctx, matrix)

    summary = {s: 0 for s in STATUSES}
    for r in rows:
        summary[r["status"]] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "summary": summary,
        "needs_human_review": summary[NEEDS_REVIEW] > 0,
        "rows": rows,
        "note": POLICY_NOTE,
    }
