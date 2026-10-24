"""
Unified candidate object.

build_unified() merges what the existing CV profile extraction produced
with what was parsed from the supporting documents into ONE canonical
dict, keeping the source of every item, flagging conflicts instead of
resolving them, and listing why a human should look (review_reasons).

enrich_profile() hands the existing screening pipeline a profile in the
exact shape it already consumes (same keys, same types); it only adds
certifications and, when the CV states no / an unclassifiable education
level, the education found in the diploma.  Scoring, thresholds and the
rule engine are not touched.

Pure Python, no LLM call, no database writes.
"""

import copy
import re
from difflib import SequenceMatcher

from .documents import _norm, level_of, LEVEL_LABELS
from .models import ApplicationSupportingDocument

T = ApplicationSupportingDocument

SCHEMA_VERSION = 1


def _name_tokens(name):
    return {t for t in re.split(r"[^a-z]+", _norm(name)) if len(t) > 1}


def names_match(a, b):
    """True when two person names plausibly refer to the same person."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return True  # nothing to compare -> no claim of mismatch
    overlap = len(ta & tb)
    return overlap / min(len(ta), len(tb)) >= 0.5


def _key(text):
    return re.sub(r"[^a-z0-9]+", " ", _norm(text)).strip()


def same_certification(a, b):
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if min(len(ka), len(kb)) >= 8 and (ka in kb or kb in ka):
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= 0.85


def _doc_ref(doc):
    return {
        "document_id": doc.pk,
        "document_type": doc.doc_type,
        "document": doc.original_name,
    }


def _with_ref(doc, evidence):
    return [dict(ev, **_doc_ref(doc)) for ev in (evidence or [])]


def build_unified(application, profile=None):
    """
    application: talent.models.Application (its candidate and its
                 supporting documents are read, nothing is written)
    profile:     dict returned by analyze_cv (or None before screening)
    """

    profile = profile or {}
    candidate = application.candidate
    docs = list(application.supporting_documents.all())
    conflicts = []
    review_reasons = []

    cv_name = (
        candidate.cv_file.name.rsplit("/", 1)[-1] if candidate.cv_file else None
    )
    cv_text = candidate.extracted_text or ""
    cv_status = (
        "missing" if not cv_text
        else "low_quality" if cv_text.startswith("[OCR NOTICE:")
        else "processed_with_notice" if cv_text.startswith("[EXTRACTION NOTICE:")
        else "processed"
    )
    cv_ref = {"document_type": "cv", "document": cv_name}

    unified = {
        "schema_version": SCHEMA_VERSION,
        "personal_information": {
            "full_name": candidate.full_name or None,
            "email": candidate.email or None,
            "phone": candidate.phone or None,
            "address": candidate.address or None,
            "source": "candidate_record",
        },
        "education": [],
        "work_experience": {
            "years_experience": profile.get("years_experience"),
            "entries": [],
            "source": "cv" if profile else None,
            "note": "The CV profile records total years only; no per-job "
                    "entries are extracted by the current pipeline.",
        },
        "skills": [
            {"name": str(s), "source": "cv"} for s in profile.get("skills", []) or []
        ],
        "certifications": [],
        "languages": [
            {"name": str(l), "source": "cv"} for l in profile.get("languages", []) or []
        ],
        "supporting_information": [],
        "conflicts": conflicts,
        "evidence": [],
        "review_reasons": review_reasons,
        "needs_human_review": False,
        "document_processing_status": {},
    }

    # ---------------- document processing status ----------------

    statuses = []
    for d in docs:
        statuses.append({
            "document_id": d.pk,
            "document_type": d.doc_type,
            "document": d.original_name,
            "status": d.status,
            "error": d.error_message or None,
            "extraction_method": d.extraction_method or None,
            "pages": d.page_count,
            "extraction_seconds": d.extraction_seconds,
        })
        if d.status == T.STATUS_FAILED:
            review_reasons.append(
                f"document_unreadable: {d.original_name} ({d.get_doc_type_display()})")
        elif d.status == T.STATUS_LOW_QUALITY:
            review_reasons.append(
                f"document_low_scan_quality: {d.original_name} ({d.get_doc_type_display()})")

    uploaded_types = {d.doc_type for d in docs}
    unified["document_processing_status"] = {
        "cv": {"status": cv_status, **cv_ref},
        "documents": statuses,
        "optional_not_uploaded": [
            t for t, _ in T.TYPE_CHOICES
            if t not in uploaded_types
        ],
        "note": "A missing optional document is not treated as evidence that "
                "the candidate lacks the qualification.",
    }
    if cv_status == "low_quality":
        review_reasons.append("document_low_scan_quality: CV")
    elif cv_status == "processed_with_notice":
        review_reasons.append("document_partly_read: CV")

    usable = [d for d in docs if d.status != T.STATUS_FAILED]

    # ---------------- holder-name check (all document types) ----------------

    for d in usable:
        holder = (d.parsed or {}).get("holder_name")
        if holder and not names_match(holder, candidate.full_name):
            conflicts.append({
                "type": "holder_name_mismatch",
                "field": "personal_information.full_name",
                "values": [
                    {"source": "candidate_record", "value": candidate.full_name},
                    {"source": d.doc_type, "document": d.original_name,
                     "document_id": d.pk, "value": holder},
                ],
                "status": "needs_human_review",
            })
            review_reasons.append(
                f"conflict: name on {d.original_name} differs from the applicant's name")

    # ---------------- education ----------------

    cv_education = (profile.get("education") or "").strip()
    cv_level = level_of(cv_education) if cv_education else None
    cv_entry = None
    if cv_education:
        cv_entry = {
            "level": cv_level,
            "level_label": LEVEL_LABELS.get(cv_level),
            "statement": cv_education,
            "field": None,
            "institution": None,
            "year": None,
            "sources": ["cv"],
            "evidence": [dict(cv_ref, field="education", quote=None, page=None,
                              note="Read by the CV profile extraction; not a verbatim quote.")],
        }

    edu_docs = [d for d in usable if d.doc_type == T.TYPE_EDUCATION]
    doc_entries = []
    for d in edu_docs:
        for item in (d.parsed or {}).get("education", []):
            doc_entries.append((d, item))

    merged_cv = False
    for d, item in doc_entries:
        entry = {
            "level": item.get("level"),
            "level_label": item.get("level_label"),
            "statement": None,
            "field": item.get("field"),
            "institution": item.get("institution"),
            "year": item.get("year"),
            "sources": [d.doc_type],
            "evidence": _with_ref(d, item.get("evidence")),
        }
        if cv_entry is not None and not merged_cv:
            if cv_level and entry["level"] and cv_level == entry["level"]:
                entry["statement"] = cv_education
                entry["sources"] = ["cv", d.doc_type]
                entry["evidence"] = cv_entry["evidence"] + entry["evidence"]
                merged_cv = True
            elif cv_level and entry["level"] and cv_level != entry["level"]:
                conflicts.append({
                    "type": "education_level_mismatch",
                    "field": "education.level",
                    "values": [
                        {"source": "cv", "value": cv_education, "level": cv_level},
                        {"source": d.doc_type, "document": d.original_name,
                         "document_id": d.pk, "value": entry["level_label"],
                         "level": entry["level"]},
                    ],
                    "status": "needs_human_review",
                })
                review_reasons.append(
                    "conflict: education level in the CV differs from the "
                    "education certificate")
        unified["education"].append(entry)

    if cv_entry is not None and not merged_cv:
        unified["education"].insert(0, cv_entry)

    # ---------------- certifications ----------------

    certs = []  # {"name","issuer","issued_date","expiry_date","sources":[...],"evidence":[...]}

    for c in profile.get("certifications", []) or []:
        name = c.get("name") if isinstance(c, dict) else str(c)
        name = (name or "").strip()
        if not name:
            continue
        if any(same_certification(name, x["name"]) for x in certs):
            continue
        certs.append({
            "name": name, "issuer": None, "issued_date": None,
            "expiry_date": None, "sources": ["cv"],
            "evidence": [dict(cv_ref, field="name", quote=None, page=None,
                              note="Listed in the CV profile.")],
        })

    for d in [x for x in usable if x.doc_type == T.TYPE_CERTIFICATE]:
        for item in (d.parsed or {}).get("certifications", []):
            match = next((x for x in certs
                          if same_certification(item["name"], x["name"])), None)
            if match is None:
                certs.append({
                    "name": item["name"], "issuer": item.get("issuer"),
                    "issued_date": item.get("issued_date"),
                    "expiry_date": item.get("expiry_date"),
                    "sources": [d.doc_type],
                    "evidence": _with_ref(d, item.get("evidence")),
                })
                continue

            # Same certification seen before: one entry, extra source.
            if d.doc_type not in match["sources"]:
                match["sources"].append(d.doc_type)
            match["evidence"] += _with_ref(d, item.get("evidence"))
            for fld in ("issuer", "issued_date", "expiry_date"):
                new, old = item.get(fld), match.get(fld)
                if new and not old:
                    match[fld] = new
                elif new and old and _norm(new) != _norm(old):
                    conflicts.append({
                        "type": "certification_detail_mismatch",
                        "field": f"certifications.{fld}",
                        "values": [
                            {"source": "earlier_document", "value": old},
                            {"source": d.doc_type, "document": d.original_name,
                             "document_id": d.pk, "value": new},
                        ],
                        "status": "needs_human_review",
                    })
                    review_reasons.append(
                        f"conflict: {fld.replace('_', ' ')} differs between "
                        f"documents for '{match['name']}'")

    unified["certifications"] = certs

    # ---------------- supporting information ----------------

    for d in docs:
        if d.doc_type == T.TYPE_SUPPORTING:
            unified["supporting_information"].append({
                **_doc_ref(d),
                "status": d.status,
                "title": (d.parsed or {}).get("title"),
                "pages": d.page_count,
            })

    # ---------------- flat evidence list ----------------

    flat = []
    for e in unified["education"]:
        for ev in e["evidence"]:
            flat.append({"claim": f"education.{ev.get('field')}", **ev})
    for c in certs:
        for ev in c["evidence"]:
            flat.append({"claim": f"certification.{ev.get('field')}: {c['name']}", **ev})
    unified["evidence"] = flat

    unified["review_reasons"] = list(dict.fromkeys(review_reasons))
    unified["needs_human_review"] = bool(unified["review_reasons"])

    return unified


def enrich_profile(profile, unified):
    """
    Return a copy of the CV profile enriched with document-derived data, in
    the shape the existing screening pipeline already expects.
    """

    enriched = copy.deepcopy(profile)

    # certifications: CV list + document certifications the CV did not list
    existing = [str(c) for c in enriched.get("certifications", []) or []]
    added = []
    for c in unified.get("certifications", []):
        if "cv" in c["sources"]:
            continue
        if not any(same_certification(c["name"], e) for e in existing):
            existing.append(c["name"])
            added.append(c["name"])
    enriched["certifications"] = existing

    # education: only fill a gap, never overwrite a stated level
    doc_edu = next(
        (e for e in unified.get("education", [])
         if "education_certificate" in e["sources"] and e.get("level")),
        None,
    )
    education_source = "cv"
    if doc_edu is not None:
        has_conflict = any(
            c["type"] == "education_level_mismatch" for c in unified.get("conflicts", [])
        )
        cv_text = (enriched.get("education") or "").strip()
        cv_level = level_of(cv_text) if cv_text else None
        label = doc_edu["level_label"] + (
            f" in {doc_edu['field']}" if doc_edu.get("field") else "")
        if not has_conflict:
            if not cv_text:
                enriched["education"] = label
                education_source = "education_certificate"
            elif cv_level is None:
                enriched["education"] = f"{cv_text} ({label}, per education certificate)"
                education_source = "cv+education_certificate"

    unified["enrichment"] = {
        "certifications_added_from_documents": added,
        "education_source": education_source,
    }

    return enriched


def review_summary(unified):
    """Compact form stored on the Application next to the other AI context."""
    return {
        "needs_human_review": unified.get("needs_human_review", False),
        "review_reasons": unified.get("review_reasons", []),
        "conflicts": unified.get("conflicts", []),
        "documents": unified.get("document_processing_status", {}).get("documents", []),
        "enrichment": unified.get("enrichment", {}),
    }
