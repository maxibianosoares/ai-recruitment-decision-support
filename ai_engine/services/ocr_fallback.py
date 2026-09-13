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

from pdf2image import convert_from_path
import pytesseract


# Portuguese + English + Indonesian. See module docstring for why
# Tetum is not included as its own code.
TESSERACT_LANG = "por+eng+ind"

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


def extract_text_via_ocr(pdf_path):
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
        images = convert_from_path(pdf_path)
    except Exception as e:
        raise OCRProcessingError(
            f"Could not render PDF pages for OCR: {e}"
        ) from e

    if not images:
        raise OCRProcessingError("PDF rendered zero pages.")

    page_texts = []

    for image in images:

        try:
            page_text = pytesseract.image_to_string(
                image,
                lang=TESSERACT_LANG
            )
        except Exception as e:
            raise OCRProcessingError(
                f"Tesseract OCR failed: {e}"
            ) from e

        page_texts.append(page_text)

    full_text = "\n\n".join(page_texts)

    quality = _assess_quality(full_text)

    return full_text, quality, len(images)
