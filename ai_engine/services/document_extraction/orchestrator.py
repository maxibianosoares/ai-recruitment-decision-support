"""
TASK I (2026-10-06) -- document extraction orchestrator.

This is the single entry point the background WORKER uses to turn an
uploaded CV PDF into text. The web request no longer extracts anything
(see talent/views.py.apply_job): it only runs the cheap structural
check below and queues the application.

What it adds on top of the existing building blocks (it reuses them; it
does not replace them):

  * PER-PAGE accounting. Every page ends up in exactly one bucket:
      native      -- text came from the PDF's own text layer
      ocr         -- text came from OCR (Tesseract, or Azure for a whole
                     scan that fits its page limit)
      blank       -- OCR skipped/empty because the page is truly empty
      unreadable  -- the page has content but yielded (almost) no text
      failed      -- a technical failure (render error, OCR timeout,
                     time budget) so nothing is known about the page
    so "was every page processed?" and "did any page fail?" are
    answered from data, not guessed.

  * MIXED documents. The old rule ("enough native text overall => done")
    ignored scanned pages inside a partly-digital PDF. Now only the
    pages without a usable text layer are sent to OCR, and the result
    is merged back in page order.

  * A COMPLETENESS verdict, kept separate from the structural verdict:
      INVALID       corrupt / not a PDF / password-protected / no pages
                    / too many pages  -> DOCUMENT_INVALID
      INSUFFICIENT  valid PDF but no/too little readable text, or a
                    page failed technically  -> EXTRACTION_FAILED
      LOW_QUALITY   text is mostly noise  -> EXTRACTION_FAILED
      OK            safe to hand to the AI pipeline
    Anything other than OK must never reach the AI pipeline.

Pure functions, no Django models: easy to test, and the worker decides
what to do with the verdict.
"""

import logging
import os
import time
from dataclasses import dataclass, field

from .router import extract_scanned_document
from .structure import (
    MSG_LOW_QUALITY,
    MSG_NO_TEXT,
    MSG_RENDER_FAILED,
    check_pdf_structure,
    msg_failed_pages,
    _open_reader,
)
from ..ocr_fallback import (
    MIN_PAGE_CHARS,
    OCR_DPI,
    OCRProcessingError,
    OCRQuality,
    assess_text_quality,
    ocr_pdf_pages,
)

logger = logging.getLogger(__name__)


def _env_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        return value if value >= 1 else default
    except ValueError:
        return default


# Wall-clock ceiling for extracting ONE document. Pages that would
# start after it are recorded as failed instead of holding the worker.
EXTRACTION_TIME_BUDGET_SECONDS = _env_int(
    "EXTRACTION_TIME_BUDGET_SECONDS", 600
)

# A page with at least this much native text is treated as a text
# page; below it the page is also OCR'd (it may be an image page that
# only carries a stray header/footer string).
MIN_PAGE_NATIVE_CHARS = 25

# A page that has a text layer but ALSO embeds an image, and whose
# text layer is short (below this), may be a scanned page with only a
# typed header/footer on top, or a photo/certificate pasted into a
# digital CV. The text layer alone would silently miss the image's
# content, so such a page is ALSO OCR'd ("supplemental" OCR). Pages
# with at least this much native text are trusted as digital: a normal
# CV page with a photo has far more text than this.
SUPPLEMENTAL_OCR_BELOW_CHARS = 200

# Verdicts.
OK = "OK"
LOW_QUALITY = "LOW_QUALITY"
INSUFFICIENT = "INSUFFICIENT"
INVALID = "INVALID"

@dataclass
class ExtractionOutcome:
    state: str
    text: str = ""
    reason: str = ""
    report: dict = field(default_factory=dict)


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------

def _empty_report(total_pages=0):
    return {
        "pages_total": total_pages,
        "method": "",
        "provider": "",
        "dpi": OCR_DPI,
        "pages": [],
        "pages_failed": [],
        "pages_unreadable": [],
        "pages_blank": [],
        "pages_retried": [],
        "pages_supplemental_ocr": [],
        "chars": 0,
        "quality": "",
        "complete": False,
        "warnings": [],
        "seconds": 0.0,
        "from_cache": False,
    }


def _page_has_image(page):
    """True if the page embeds at least one raster image. Cheap (reads
    the page's resource dictionary only); any problem reading it means
    'unknown', treated as no image."""
    try:
        resources = page.get("/Resources")
        xobjects = resources.get_object().get("/XObject") if resources else None
        if not xobjects:
            return False
        for ref in xobjects.get_object().values():
            if ref.get_object().get("/Subtype") == "/Image":
                return True
    except Exception:
        return False
    return False


def extract_document(pdf_path, budget_seconds=None):
    """
    Read a CV PDF completely and return an ExtractionOutcome. Never
    raises for a document problem -- the verdict says what happened.
    """

    started = time.perf_counter()

    budget = (
        EXTRACTION_TIME_BUDGET_SECONDS
        if budget_seconds is None else budget_seconds
    )
    deadline = time.monotonic() + budget

    report = _empty_report()

    check = check_pdf_structure(pdf_path)

    if not check.ok:
        report["pages_total"] = check.page_count
        report["warnings"].append(check.reason)
        report["seconds"] = round(time.perf_counter() - started, 2)
        return ExtractionOutcome(INVALID, reason=check.reason, report=report)

    reader = _open_reader(pdf_path)
    total = check.page_count
    report["pages_total"] = total

    # 1. Native text layer, page by page.
    native = {}
    for number, page in enumerate(reader.pages, start=1):
        try:
            native[number] = page.extract_text() or ""
        except Exception as e:
            native[number] = ""
            logger.warning(
                "[EXTRACTION] native text failed on page %s: %s", number, e
            )

    # Pages with no usable text layer MUST be OCR'd. Pages that have a
    # short text layer plus an embedded image are OCR'd as a
    # supplement (see SUPPLEMENTAL_OCR_BELOW_CHARS).
    required_ocr = [
        n for n in range(1, total + 1)
        if len(native[n].strip()) < MIN_PAGE_NATIVE_CHARS
    ]
    supplemental_ocr = [
        n for n in range(1, total + 1)
        if n not in required_ocr
        and len(native[n].strip()) < SUPPLEMENTAL_OCR_BELOW_CHARS
        and _page_has_image(reader.pages[n - 1])
    ]
    needs_ocr = sorted(required_ocr + supplemental_ocr)

    page_text = dict(native)
    methods = {n: "native" for n in range(1, total + 1)}
    errors = {}
    detail = {}
    azure_text = None

    if not needs_ocr:
        report["method"] = "native"
        report["provider"] = "native"

    else:
        report["method"] = (
            "ocr" if len(required_ocr) == total else "mixed"
        )
        report["pages_supplemental_ocr"] = list(supplemental_ocr)

        try:
            if len(required_ocr) == total:
                # Whole document is a scan: the router may use Azure
                # (only if it can read every page) or Tesseract, and
                # caches usable results by file hash.
                result = extract_scanned_document(
                    pdf_path, total_pages=total, deadline=deadline
                )
                report["provider"] = result.provider
                report["from_cache"] = result.from_cache
                report["warnings"].extend(result.warnings or [])

                if result.provider == "tesseract":
                    for p in result.pages:
                        detail[p["page_number"]] = p
                else:
                    azure_text = result.text
                    for n in needs_ocr:
                        methods[n] = "ocr"
            else:
                # Mixed: only the pages without a usable text layer.
                report["provider"] = "mixed (native + tesseract)"
                for r in ocr_pdf_pages(pdf_path, needs_ocr, deadline):
                    detail[r.page_number] = {
                        "page_number": r.page_number,
                        "chars": len(r.text.strip()),
                        "seconds": round(r.seconds, 2),
                        "dpi": r.dpi,
                        "retried": r.retried,
                        "blank": r.blank,
                        "error": r.error,
                        "text": r.text,
                    }

        except OCRProcessingError as e:
            report["warnings"].append(str(e))
            report["seconds"] = round(time.perf_counter() - started, 2)
            return ExtractionOutcome(
                INVALID, reason=MSG_RENDER_FAILED, report=report
            )

        for n in needs_ocr:
            d = detail.get(n)
            if d is None:
                continue

            supplemental = n in supplemental_ocr

            if d.get("error"):
                if supplemental:
                    # The page already has a usable native text layer;
                    # the extra OCR pass failed. Keep the native text
                    # and say so, rather than failing a digital CV
                    # because of an optional pass.
                    report["warnings"].append(
                        f"Page {n}: the embedded image on this page "
                        "could not be read by OCR; only its digital "
                        "text was used."
                    )
                    continue
                errors[n] = d["error"]
                methods[n] = "failed"
                continue

            ocr_text = d.get("text", "")

            if len(ocr_text.strip()) > len(native[n].strip()):
                page_text[n] = ocr_text
                methods[n] = "ocr"

            if d.get("retried"):
                report["pages_retried"].append(n)

            if supplemental:
                # Native text exists, so never "blank"/"unreadable".
                continue

            if d.get("blank"):
                methods[n] = "blank"
            elif len(page_text[n].strip()) < MIN_PAGE_CHARS:
                methods[n] = "unreadable"
            else:
                methods[n] = "ocr"

    # 2. Assemble in page order.
    if azure_text is not None:
        text = azure_text
    else:
        text = "\n".join(
            page_text[n] for n in range(1, total + 1)
            if page_text[n].strip()
        )

    # 3. Per-page report (no page text is stored in it).
    for n in range(1, total + 1):
        d = detail.get(n, {})
        report["pages"].append({
            "page": n,
            "method": methods[n],
            "chars": len(page_text[n].strip()),
            "dpi": d.get("dpi"),
            "seconds": d.get("seconds"),
            "retried": bool(d.get("retried")),
            "error": errors.get(n),
        })

    report["pages_failed"] = [
        {"page": n, "error": e} for n, e in errors.items()
    ]
    report["pages_unreadable"] = [
        n for n in range(1, total + 1) if methods[n] == "unreadable"
    ]
    report["pages_blank"] = [
        n for n in range(1, total + 1) if methods[n] == "blank"
    ]
    report["chars"] = len(text.strip())

    quality = assess_text_quality(text)
    report["quality"] = quality
    # "complete" means ONLY: every page was processed, none failed
    # technically, none had content that yielded no text. It does NOT
    # claim the OCR text is 100% accurate -- that cannot be guaranteed
    # (see report["quality"] for the text-quality grade).
    report["complete"] = not errors and not report["pages_unreadable"]
    report["seconds"] = round(time.perf_counter() - started, 2)

    # 4. Verdict.
    if errors:
        return ExtractionOutcome(
            INSUFFICIENT, text=text,
            reason=msg_failed_pages(sorted(errors)), report=report
        )

    if quality == OCRQuality.FAILED:
        return ExtractionOutcome(
            INSUFFICIENT, text=text, reason=MSG_NO_TEXT, report=report
        )

    if quality == OCRQuality.LOW:
        return ExtractionOutcome(
            LOW_QUALITY, text=text, reason=MSG_LOW_QUALITY, report=report
        )

    notices = list(report["warnings"])

    if report["pages_unreadable"]:
        pages = ", ".join(str(p) for p in report["pages_unreadable"])
        notices.append(
            f"Page(s) {pages} contain content that could not be read "
            "by OCR; information on those pages may be missing."
        )

    if notices:
        text = "[EXTRACTION NOTICE: " + " ".join(notices) + "]\n\n" + text

    return ExtractionOutcome(OK, text=text, report=report)