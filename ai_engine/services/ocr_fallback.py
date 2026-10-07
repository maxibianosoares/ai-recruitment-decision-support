"""
Robust OCR fallback for scanned/image-based CV PDFs (improvement on
top of the Phase 20 baseline -- this module is new, Phase 20's
existing pipeline is unchanged).

This module is ONLY invoked by talent/utils.py:extract_text_from_pdf()
when native text-layer extraction (pypdf) yields insufficient text --
native, digitally-generated PDFs with a real text layer NEVER touch
this module, so their extraction speed is completely unaffected.

DESIGN NOTE -- why a new module instead of reviving the orphan
ai_engine/cv_parser.py:
    1. cv_parser.py's lang='eng+por+kor' includes Korean (very likely
       a copy/paste artifact) and omits Indonesian entirely.
    2. It duplicates PDF text extraction logic that talent/utils.py
       already owns, instead of being a clean fallback triggered only
       when the native path fails.
    3. Starting fresh keeps this change small, reviewable, and fully
       decoupled from the orphan file's other issues -- it can stay
       orphaned/removed later without affecting this.

HONEST LANGUAGE COVERAGE -- read before citing this in the thesis:
    Tesseract has no official trained model for Tetum ("tet"). This
    was verified against Tesseract's official supported-language
    list (tessdata_fast / tessdata_best, 100+ languages) -- Tetum is
    not present. The language config below uses Portuguese + English
    + Indonesian ("por+eng+ind"). For a CV written primarily in
    Tetum, Portuguese is used as the closest practical fallback
    (shared Latin script, heavy Portuguese loanwords in formal Tetum
    writing) -- this is NOT genuine Tetum language support, and OCR
    accuracy on Tetum-heavy text should be expected to be materially
    lower than on Portuguese/English/Indonesian text. Do not describe
    this as "Tetum OCR support" in the paper -- describe it exactly
    as what it is: a Portuguese-model fallback for Latin-script,
    Portuguese-influenced text.

SYSTEM DEPENDENCIES (not just pip packages -- document these for
Windows setup, since pytesseract/pdf2image are thin wrappers around
external binaries that must be installed separately):
    - Tesseract OCR engine (the `tesseract` binary itself), plus the
      Portuguese and Indonesian trained-data files (English ships by
      default). On Windows: install from
      https://github.com/UB-Mannheim/tesseract/wiki, then download
      por.traineddata / ind.traineddata from
      https://github.com/tesseract-ocr/tessdata and place them in the
      Tesseract "tessdata" folder.
    - Poppler (provides `pdftoppm`, used by pdf2image to rasterize
      PDF pages to images). On Windows: download a Poppler release
      and add its `bin/` folder to PATH.
    Both are already referenced in requirements.txt (pytesseract,
    pdf2image, pillow) from an earlier, unused experiment -- no new
    Python dependency is being added here, only these two system
    binaries need to actually be installed for OCR to work locally.
"""

import re
import time
from dataclasses import dataclass
from typing import Optional

from pdf2image import convert_from_path, pdfinfo_from_path
import pytesseract


# Portuguese + English + Indonesian. See module docstring for why
# Tetum is not included as its own code.
TESSERACT_LANG = "por+eng+ind"

# ---------------------------------------------------------------------
# TASK I (2026-10-06) -- page-by-page OCR settings. Chosen from a local
# benchmark, not assumed (3-page and 40-page synthetic scans, clean /
# degraded / 100-150 DPI sources, Tesseract 5.3 on 2 vCPU):
#   * 150 / 200 / 300 DPI recall was 99.4-100% in every case, so DPI is
#     not what loses information; 300 DPI costs ~35-40% more time and
#     ~2x memory than 200 DPI.
#   * Rendering ALL pages at once (what this module used to do) peaked
#     at 1.4GB (40 pages @ 200 DPI) and 3.0GB (@ 300 DPI); one page at
#     a time peaked at 136-165MB for the same total time. Railway's
#     trial plan caps RAM at 1GB, so the old approach would be OOM-killed
#     on a long scan.
# So: 200 DPI for every page, one page in memory at a time, and only a
# page whose first result looks weak is retried once at 300 DPI.
# ---------------------------------------------------------------------
OCR_DPI = 200
OCR_RETRY_DPI = 300

# Hard ceiling for one Tesseract call on one page. A page that exceeds
# it is recorded as failed instead of hanging the worker.
PAGE_OCR_TIMEOUT_SECONDS = 60

# A page whose OCR output is shorter than this (and which is not
# blank) is "weak" and gets the one 300-DPI retry.
MIN_PAGE_CHARS = 25

# Fraction of clearly dark pixels below which a page counts as
# genuinely blank rather than unreadable. Deliberately tiny (0.005%,
# ~185 dark pixels on a 200-DPI letter page): a sparse page with a
# couple of short lines is still far above it, while a clean empty
# sheet is far below it. When in doubt the page is OCR'd, not skipped.
BLANK_INK_RATIO = 0.00005

# Same bar as the native-extraction check in talent/utils.py, so
# both extraction paths agree on what counts as "usable text".
MIN_USABLE_CHARS = 50

# Below this ratio of alphabetic characters to non-whitespace
# characters, treat OCR output as noise even if it cleared the
# character-count bar -- garbled scans often produce long strings of
# symbol/punctuation noise that a length-only check would miss.
MIN_ALPHA_RATIO = 0.4


class OCRQuality:
    OK = "OK"
    LOW = "LOW"
    FAILED = "FAILED"


class OCRProcessingError(Exception):
    """Raised when the PDF itself could not even be rendered to images
    (a more fundamental failure than poor OCR quality)."""
    pass


def _assess_quality(text):
    """Simple, explainable heuristic -- not a learned quality model.
    Deliberately conservative: prefers to under-trust borderline
    output rather than silently pass noise downstream to the LLM."""

    stripped = text.strip()

    if len(stripped) < MIN_USABLE_CHARS:
        return OCRQuality.FAILED

    non_space = re.sub(r"\s", "", stripped)

    if not non_space:
        return OCRQuality.FAILED

    alpha_count = sum(1 for c in non_space if c.isalpha())

    alpha_ratio = alpha_count / len(non_space)

    if alpha_ratio < MIN_ALPHA_RATIO:
        return OCRQuality.LOW

    return OCRQuality.OK


# TASK G (2026-10-03): exported alias so the new document_extraction
# router can reuse the EXACT same quality heuristic for Azure Document
# Intelligence results, instead of duplicating/re-implementing it.
# Both extraction providers must agree on what counts as
# OK/LOW/FAILED, since talent/utils.py's downstream behavior (proceed
# with a warning vs. reject outright) is keyed on that enum, not on
# which provider produced the text.
assess_text_quality = _assess_quality


def extract_text_via_ocr(pdf_path, details=None, deadline=None):
    """
    Renders every page of the PDF as an image and runs Tesseract OCR
    on each, in page order (so multi-page CVs are not reduced to
    just the first page). Returns (text, quality, page_count).

    Does NOT raise for a merely bad/noisy OCR result -- the caller
    (talent/utils.py) decides what to do with a FAILED/LOW quality
    result. Only raises OCRProcessingError if the PDF could not be
    rendered to images at all.
    """

    try:
        total_pages = pdf_page_count(pdf_path)
    except Exception as e:
        raise OCRProcessingError(
            f"Could not render PDF pages for OCR: {e}"
        ) from e

    if total_pages < 1:
        raise OCRProcessingError("PDF rendered zero pages.")

    results = ocr_pdf_pages(
        pdf_path, range(1, total_pages + 1), deadline=deadline
    )

    # Optional side channel: callers that want the per-page detail
    # (the extraction router/orchestrator) pass a list and get the
    # PageOCR objects appended; every existing caller keeps getting the
    # unchanged (text, quality, page_count) return value.
    if details is not None:
        details.extend(results)

    # Same contract as before: only raise when NOTHING could be
    # processed at all (every page failed technically). A partially
    # failed document still returns what it got; the orchestrator
    # (document_extraction/orchestrator.py) is what decides whether a
    # partial result is acceptable, using the per-page detail.
    # A caller that asked for the per-page detail (the orchestrator)
    # gets the failures reported per page instead of an exception, so
    # "every page timed out" is classed as an extraction failure (the
    # candidate's file may be fine), not as an invalid document.
    if details is None and all(r.error for r in results):
        raise OCRProcessingError(
            f"OCR failed on every page: {results[0].error}"
        )

    full_text = "\n\n".join(r.text for r in results)

    quality = _assess_quality(full_text)

    return full_text, quality, total_pages


@dataclass
class PageOCR:
    """Outcome of OCR on one page. `error` is set only for a technical
    failure (render error, Tesseract error/timeout, time budget);
    `blank` pages and pages that simply contain no readable text are
    NOT errors -- they are reported separately so the caller can tell
    them apart."""
    page_number: int
    text: str = ""
    seconds: float = 0.0
    dpi: int = OCR_DPI
    retried: bool = False
    blank: bool = False
    error: Optional[str] = None


def pdf_page_count(pdf_path):
    """Page count via Poppler (the same toolchain used for rendering)."""
    return int(pdfinfo_from_path(pdf_path)["Pages"])


def _ink_ratio(image):
    """Fraction of clearly dark pixels, from the grayscale histogram of
    the FULL-resolution page (a C-speed pass, a few ms). Do not
    downscale first: averaging thin, small text into a thumbnail washes
    it out and makes a page with real (if sparse) text look empty --
    this was caught by the multi-page scan test."""
    gray = image.convert("L")
    total = gray.size[0] * gray.size[1]
    if total == 0:
        return 0.0
    histogram = gray.histogram()
    return sum(histogram[:210]) / total


def _render_page(pdf_path, page_number, dpi):
    pages = convert_from_path(
        pdf_path, dpi=dpi,
        first_page=page_number, last_page=page_number
    )
    if not pages:
        raise OCRProcessingError(
            f"Page {page_number} rendered no image."
        )
    return pages[0]


def _ocr_one_page(pdf_path, page_number, dpi):
    """Render + OCR a single page at `dpi`. Returns (text, blank)."""
    image = _render_page(pdf_path, page_number, dpi)
    try:
        if _ink_ratio(image) < BLANK_INK_RATIO:
            return "", True
        text = pytesseract.image_to_string(
            image,
            lang=TESSERACT_LANG,
            timeout=PAGE_OCR_TIMEOUT_SECONDS
        )
        return text, False
    finally:
        del image


def ocr_pdf_pages(pdf_path, page_numbers, deadline=None):
    """
    OCR the given 1-based pages, ONE PAGE IN MEMORY AT A TIME, and
    return a list[PageOCR] in the order given. Never raises for a
    per-page problem -- the problem is recorded on that page's
    PageOCR.error so one bad page cannot discard the others.

    `deadline` is an optional time.monotonic() value; a page that would
    start after it is recorded as failed (time budget exceeded) rather
    than letting a huge document hold the worker indefinitely.
    """

    results = []

    for page_number in page_numbers:

        result = PageOCR(page_number=page_number)
        started = time.perf_counter()

        if deadline is not None and time.monotonic() > deadline:
            result.error = "Extraction time budget exceeded before this page."
            results.append(result)
            continue

        try:
            text, blank = _ocr_one_page(pdf_path, page_number, OCR_DPI)
        except Exception:
            # One retry for a transient failure (e.g. a Tesseract
            # timeout on a heavy page) before giving up on the page.
            try:
                text, blank = _ocr_one_page(pdf_path, page_number, OCR_DPI)
                result.retried = True
            except Exception as second_error:
                result.error = (
                    f"{type(second_error).__name__}: {second_error}"
                )
                result.seconds = time.perf_counter() - started
                results.append(result)
                continue

        result.text = text
        result.blank = blank

        # Weak (non-blank) page: one retry at higher resolution, keep
        # whichever result has more text. Cost is only paid on pages
        # that actually look like they lost something.
        if not blank and len(text.strip()) < MIN_PAGE_CHARS:
            try:
                better, _ = _ocr_one_page(
                    pdf_path, page_number, OCR_RETRY_DPI
                )
                result.retried = True
                if len(better.strip()) > len(text.strip()):
                    result.text = better
                    result.dpi = OCR_RETRY_DPI
            except Exception:
                # The 200-DPI result stands; this retry is optional.
                pass

        result.seconds = time.perf_counter() - started
        results.append(result)

    return results