"""
Optional supporting documents for an application (multi-document upload).

Three stages, matching how the CV already flows through the system:

  1. WEB REQUEST (cheap, no extraction):  validate_uploads() checks each
     file (PDF, size, header, structure) and store_supporting_documents()
     keeps the bytes in the database -- the worker is a separate
     container and cannot read the web server's disk.
  2. WORKER (after the CV was read):  process_pending_supporting_documents()
     reads each pending document ONCE with the existing document
     extraction orchestrator (native text, OCR only where needed), parses a
     few structured fields with deterministic rules -- NO extra LLM call --
     keeps the text, parsed fields and status, and releases the bytes.
  3. PIPELINE:  talent/unified.py merges the stored results; nothing is
     read again.

Nothing here invents information: a field the rules cannot find stays
None / absent, and a document that yields nothing is still recorded with
a note.  Document content is never written to the log.
"""

import hashlib
import logging
import os
import re
import tempfile
import unicodedata

from pypdf import PdfReader

from ai_engine.services.document_extraction.structure import (
    check_pdf_structure,
)

from .models import ApplicationSupportingDocument

logger = logging.getLogger(__name__)

MAX_DOC_FILE_SIZE_BYTES = 5 * 1024 * 1024   # same limit as the CV upload
MAX_SUPPORTING_TOTAL_BYTES = 20 * 1024 * 1024
MAX_CERTIFICATES = 10

NOTICE_PREFIXES = ("[OCR NOTICE:", "[EXTRACTION NOTICE:")

T = ApplicationSupportingDocument


# ---------------------------------------------------------------------
# Stage 1 -- web request
# ---------------------------------------------------------------------

def _safe_name(name):
    name = os.path.basename(name or "document.pdf")
    name = "".join(ch for ch in name if ch.isprintable())
    return name[:200] or "document.pdf"


def validate_uploads(education_file, certificate_files):
    """
    Validate the diploma (required) and the certificates (optional)
    before anything is stored.

    Returns (items, error).  error is a user-facing message (the whole
    submission is then rejected, like an invalid CV) or None; items is a
    list of {"doc_type", "name", "data", "sha256"} ready for
    store_supporting_documents().  Identical files in one submission are
    kept once.
    """

    if len(certificate_files) > MAX_CERTIFICATES:
        return [], f"You can upload at most {MAX_CERTIFICATES} certificates."
    if not education_file:
        return [], ("Please upload your latest education certificate / "
                    "diploma (PDF).")

    wanted = [(T.TYPE_EDUCATION, education_file)]
    wanted += [(T.TYPE_CERTIFICATE, f) for f in certificate_files]

    items, seen, total = [], set(), 0

    for doc_type, upload in wanted:
        name = _safe_name(upload.name)

        if not name.lower().endswith(".pdf"):
            return [], f"'{name}': only PDF files are accepted."
        if upload.size == 0:
            return [], f"'{name}' is empty."
        if upload.size > MAX_DOC_FILE_SIZE_BYTES:
            return [], (f"'{name}' is too large. Please upload a PDF under "
                        f"{MAX_DOC_FILE_SIZE_BYTES // (1024 * 1024)}MB.")

        data = upload.read()
        upload.seek(0)

        structure = check_pdf_structure(data)
        if not structure.ok:
            return [], f"'{name}': {structure.reason}"

        digest = hashlib.sha256(data).hexdigest()
        if (doc_type, digest) in seen:
            continue
        seen.add((doc_type, digest))

        total += len(data)
        if total > MAX_SUPPORTING_TOTAL_BYTES:
            return [], (f"The supporting documents together are larger than "
                        f"{MAX_SUPPORTING_TOTAL_BYTES // (1024 * 1024)}MB.")

        items.append({"doc_type": doc_type, "name": name,
                      "data": data, "sha256": digest})

    return items, None


def store_supporting_documents(application, items):
    """
    Save the validated uploads for this application as pending.  For each
    type that was uploaded again, the earlier documents of that type are
    replaced (re-upload after a CV problem); types not uploaded are left
    alone.  Returns the created rows.
    """

    for doc_type in {i["doc_type"] for i in items}:
        application.supporting_documents.filter(doc_type=doc_type).delete()

    return [
        T.objects.create(
            application=application,
            doc_type=i["doc_type"],
            pdf_bytes=i["data"],
            original_name=i["name"],
            sha256=i["sha256"],
        )
        for i in items
    ]


# ---------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------

def _norm(text):
    """Lower-case, accent-stripped, whitespace-collapsed (comparison only)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _lines(text):
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line.startswith(NOTICE_PREFIXES):
            continue
        out.append(line)
    return out


def _clip(text, n=200):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "janeiro|fevereiro|marco|maio|junho|julho|agosto|setembro|outubro|"
    "novembro|dezembro|januari|februari|maret|mei|juni|juli|agustus|"
    "oktober|desember|janeiru|fevereiru|marsu|maiu|junu|jullu|agostu|"
    "setembru|outubru|novembru|dezembru"
)

DATE_RE = re.compile(
    r"(?:\b\d{1,2}(?:st|nd|rd|th)?\s+(?:de\s+)?(?:" + MONTHS + r")\.?,?\s+(?:de\s+)?(?:19|20)\d{2}\b)"
    r"|(?:\b(?:" + MONTHS + r")\.?\s+\d{1,2},?\s+(?:19|20)\d{2}\b)"
    r"|(?:\b(?:" + MONTHS + r")\.?,?\s+(?:19|20)\d{2}\b)"
    r"|(?:\b(?:19|20)\d{2}-\d{2}-\d{2}\b)"
    r"|(?:\b\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}\b)"
    r"|(?:\b(?:19|20)\d{2}\b)",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

ISSUE_KEYS = re.compile(
    r"issued|date of issue|awarded on|completed on|graduat|conferred|"
    r"tanggal terbit|tanggal lulus|diterbitkan|lulus|data de emiss|emitido em|"
    r"concluido|data de conclus|dated|date\b|tanggal|data\b",
    re.IGNORECASE,
)

EXPIRY_KEYS = re.compile(
    r"valid until|valid through|valid thru|expires?|expiry|expiration|"
    r"berlaku sampai|berlaku hingga|masa berlaku|valido ate|validade|vence|"
    r"valid to",
    re.IGNORECASE,
)

NAME_LABEL_RE = re.compile(
    r"(?:this is to certify that|certify that|awarded to|presented to|"
    r"issued to|granted to|conferred (?:up)?on|diberikan kepada|"
    r"dengan ini menyatakan bahwa|menyatakan bahwa|certificamos que|"
    r"conferido a|name|nama|nome|naran)\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)

ORG_WORDS = (
    "universit", "universid", "institut", "politekn", "polytechnic", "college", "academy",
    "akademi", "academia", "escola", "school", "ministry", "ministerio",
    "kementerian", "commission", "comissao", "komisi", "foundation",
    "fundacao", "yayasan", "centre", "center", "centro", "pusat", "agency",
    "agencia", "badan", "department", "departamento", "microsoft", "google",
    "cisco", "oracle", "amazon", "comptia", "coursera", "udemy", "edx",
    "linkedin", "ibm", "un ", "united nations", "koica", "undp", "unicef",
)

UNIVERSITY_WORDS = (
    "universit", "universid", "institut", "politekn", "polytechnic", "college",
    "akademi", "academy", "academia", "escola", "school", "sekolah tinggi",
)

CERT_TITLE_KEYS = (
    "certificate", "certification", "certified", "sertifikat", "certificado",
    "training", "course", "workshop", "pelatihan", "formacao", "kursus",
    "bootcamp", "seminar", "diploma of completion", "attestation",
)

# Highest level first: the first match wins.
LEVELS = [
    ("doctorate", r"\b(ph\.?d|doctor(?:ate)?|doutoramento|doktor|s3)\b"),
    ("master", r"\b(master|mestrado|magister|m\.?sc|mba|s2)\b"),
    ("bachelor", r"\b(bachelor|b\.?sc|licenciatura|bacharelato|sarjana|"
                 r"graus? universitari\w*|undergraduate degree|s1)\b"),
    ("diploma", r"\b(diploma|associate degree|d[1-4]|diplom\w*|"
                r"politeknik diploma)\b"),
    ("secondary", r"\b(high school|senior high|secondary school|sma|smk|"
                  r"ensino secundario|ensino medio|escola secundaria|"
                  r"sekolah menengah atas)\b"),
]

LEVEL_LABELS = {
    "doctorate": "Doctorate",
    "master": "Master's degree",
    "bachelor": "Bachelor's degree",
    "diploma": "Diploma",
    "secondary": "Secondary school",
}


def level_of(text):
    """Map free text to one canonical education level, or None."""
    t = _norm(text)
    for level, pattern in LEVELS:
        if re.search(pattern, t):
            return level
    return None


def _match_dates(line):
    return [m.group(0) for m in DATE_RE.finditer(line)]


def _page_texts(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        return [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        return []


def _locate_page(pages, quote):
    """1-based page whose native text contains the quote, else None."""
    if not pages or not quote:
        return None
    needle = _norm(quote)
    for i, page in enumerate(pages, start=1):
        if needle and needle in _norm(page):
            return i
    return None


def _evidence(field, quote, pages):
    return {
        "field": field,
        "quote": _clip(quote),
        "page": _locate_page(pages, quote),
    }


def _holder_name(lines, pages):
    for i, line in enumerate(lines):
        m = NAME_LABEL_RE.search(line)
        if not m:
            continue
        value = m.group(1).strip(" :-")
        quote = line
        if not value and i + 1 < len(lines):
            value = lines[i + 1].strip()
            quote = f"{line} {value}"
        if 2 <= len(value) <= 80 and not re.search(r"\d", value):
            return value, _evidence("holder_name", quote, pages)
    return None, None


# ---------------------------------------------------------------------
# Deterministic parsers (one per document type)
# ---------------------------------------------------------------------

def parse_education_certificate(text, pages=None):
    lines = _lines(text)
    evidence = []
    notes = []

    # The highest level named anywhere in the document wins; a bare
    # "DIPLOMA" heading must not outrank "Bachelor of ..." on another line.
    level = None
    level_line = None
    for name, _pattern in LEVELS:
        for line in lines:
            if level_of(line) == name:
                level, level_line = name, line
                break
        if level:
            break
    if level_line:
        evidence.append(_evidence("level", level_line, pages))

    field = None
    labelled = re.compile(
        r"(?:field of study|major|study program(?:me)?|program studi|jurusan|"
        r"programa|area de estudo|curso)\s*[:\-]\s*(.+)$", re.IGNORECASE)
    inline = re.compile(
        r"(?:bachelor|master|doctor\w*|licenciatura|mestrado|sarjana|"
        r"magister|diploma|ph\.?d)\b[^\n]*\b(?:in|em|dalam)\s+"
        r"([A-Za-z][A-Za-z&' \-]{2,60})", re.IGNORECASE)
    for line in lines:
        m = labelled.search(line) or inline.search(line)
        if m:
            candidate_field = m.group(1).strip(" .,;:-")
            if 2 < len(candidate_field) <= 70:
                field = candidate_field
                evidence.append(_evidence("field", line, pages))
                break

    institution = None
    for line in lines:
        n = _norm(line)
        if any(w in n for w in UNIVERSITY_WORDS) and len(line) <= 120:
            institution = line.strip(" .,;:-")
            evidence.append(_evidence("institution", line, pages))
            break

    year = None
    for line in lines:
        if ISSUE_KEYS.search(line):
            dates = _match_dates(line)
            if dates:
                year = int(YEAR_RE.search(dates[0]).group(0))
                evidence.append(_evidence("year", line, pages))
                break
    if year is None:
        years = {int(y) for y in YEAR_RE.findall(text or "")}
        if len(years) == 1:
            year = years.pop()

    holder, holder_ev = _holder_name(lines, pages)
    if holder_ev:
        evidence.append(holder_ev)

    education = []
    if level or institution:
        education.append({
            "level": level,
            "level_label": LEVEL_LABELS.get(level),
            "field": field,
            "institution": institution,
            "year": year,
            "evidence": evidence,
        })
    else:
        notes.append(
            "No education level or institution could be recognised in this "
            "document; it is listed but contributes no education data."
        )

    return {"education": education, "holder_name": holder, "notes": notes}


def parse_certificate(text, pages=None):
    lines = _lines(text)
    evidence = []
    notes = []

    title = None
    after = re.compile(
        r"(?:has successfully completed|successfully completed|completed the|"
        r"has completed|telah menyelesaikan|telah mengikuti|concluiu|"
        r"completou)\s*[:\-]?\s*(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = after.search(line)
        if m:
            value = m.group(1).strip(" .,;:-")
            if not value and i + 1 < len(lines):
                value = lines[i + 1].strip(" .,;:-")
            if 3 <= len(value) <= 120:
                title = value
                evidence.append(_evidence("name", line, pages))
                break
    if title is None:
        for line in lines:
            n = _norm(line)
            if any(k in n for k in CERT_TITLE_KEYS) and 6 <= len(line) <= 120:
                title = line.strip(" .,;:-")
                evidence.append(_evidence("name", line, pages))
                break

    issuer = None
    by = re.compile(
        r"(?:issued by|awarded by|organi[sz]ed by|offered by|provided by|"
        r"diterbitkan oleh|diselenggarakan oleh|emitido por|"
        r"organizado por)\s*[:\-]?\s*(.+)$", re.IGNORECASE)
    for line in lines:
        m = by.search(line)
        if m and 2 <= len(m.group(1).strip()) <= 120:
            issuer = m.group(1).strip(" .,;:-")
            evidence.append(_evidence("issuer", line, pages))
            break
    if issuer is None:
        for line in lines:
            if title and line.strip(" .,;:-") == title:
                continue
            n = _norm(line)
            if any(w in n for w in ORG_WORDS) and len(line) <= 120:
                issuer = line.strip(" .,;:-")
                evidence.append(_evidence("issuer", line, pages))
                break

    issued = expiry = None
    for line in lines:
        dates = _match_dates(line)
        if not dates:
            continue
        if EXPIRY_KEYS.search(line) and expiry is None:
            expiry = dates[-1]
            evidence.append(_evidence("expiry_date", line, pages))
        elif ISSUE_KEYS.search(line) and issued is None:
            issued = dates[0]
            evidence.append(_evidence("issued_date", line, pages))

    holder, holder_ev = _holder_name(lines, pages)
    if holder_ev:
        evidence.append(holder_ev)

    certifications = []
    if title:
        certifications.append({
            "name": title,
            "issuer": issuer,
            "issued_date": issued,
            "expiry_date": expiry,
            "evidence": evidence,
        })
    else:
        notes.append(
            "No certificate title could be recognised in this document; it "
            "is listed but no certification is claimed from it."
        )

    return {"certifications": certifications, "holder_name": holder,
            "notes": notes}


def parse_supporting(text, pages=None):
    lines = _lines(text)
    title = lines[0][:120] if lines else None
    holder, _ = _holder_name(lines, pages)
    notes = [
        "Supporting documents are stored for human review; no qualification "
        "is extracted from them."
    ]
    return {"title": title, "holder_name": holder, "notes": notes}


PARSERS = {
    ApplicationSupportingDocument.TYPE_EDUCATION: parse_education_certificate,
    ApplicationSupportingDocument.TYPE_CERTIFICATE: parse_certificate,
    ApplicationSupportingDocument.TYPE_SUPPORTING: parse_supporting,
}


# ---------------------------------------------------------------------
# Stage 2 -- worker
# ---------------------------------------------------------------------

PARSERS = {
    T.TYPE_EDUCATION: parse_education_certificate,
    T.TYPE_CERTIFICATE: parse_certificate,
    T.TYPE_SUPPORTING: parse_supporting,
}

MSG_UNOPENABLE = (
    "This document could not be opened. It may be corrupted or "
    "password-protected."
)
MSG_NO_TEXT = (
    "No readable text could be extracted from this document. Please "
    "upload a clearer scan or a digitally-generated PDF."
)
MSG_UNEXPECTED = (
    "This document could not be processed. Please upload a clearer or "
    "digitally-generated PDF."
)


def process_pending_supporting_documents(application):
    """
    Read every pending supporting document of this application once.
    Never raises: an unreadable document is recorded as failed (with a
    reason a candidate can act on) and the others continue.  Returns the
    processed rows.  Only ids, types and states are logged.
    """

    done = []

    for doc in application.supporting_documents.filter(status=T.STATUS_PENDING):
        try:
            _process_one(doc)
        except Exception:
            logger.exception("Supporting document %s failed unexpectedly", doc.pk)
            doc.status = T.STATUS_FAILED
            doc.error_message = MSG_UNEXPECTED
            doc.save()
        else:
            logger.info("Supporting document %s (%s): %s",
                        doc.pk, doc.doc_type, doc.status)
        done.append(doc)

    return done


def _process_one(doc):
    # Imported here, not at module level: the web request imports this
    # module and must not pull in the OCR stack (see structure.py).
    from ai_engine.services.document_extraction import orchestrator

    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(bytes(doc.pdf_bytes))
        outcome = orchestrator.extract_document(path)
        pages = _page_texts(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    report = outcome.report or {}
    doc.page_count = report.get("pages_total") or len(pages)
    doc.extraction_method = report.get("method", "") or ""
    doc.extraction_seconds = report.get("seconds", 0) or 0
    # The PDF bytes are KEPT so that authorised reviewers can open the
    # original document from the candidate page (talent.views.
    # supporting_document_file); the extracted text and parsed fields
    # are stored alongside.

    if outcome.state == orchestrator.INVALID:
        doc.status = T.STATUS_FAILED
        doc.error_message = MSG_UNOPENABLE
    elif outcome.state == orchestrator.INSUFFICIENT:
        doc.status = T.STATUS_FAILED
        doc.error_message = (
            "Some pages of this document could not be processed."
            if report.get("pages_failed") else MSG_NO_TEXT
        )
    else:
        low = outcome.state == orchestrator.LOW_QUALITY
        doc.extracted_text = outcome.text
        doc.status = T.STATUS_LOW_QUALITY if low else T.STATUS_PROCESSED
        # Page numbers are only reliable when the page has a native text
        # layer; for OCR pages the quote is kept without a page.
        doc.parsed = PARSERS[doc.doc_type](outcome.text, pages)

    doc.save()
