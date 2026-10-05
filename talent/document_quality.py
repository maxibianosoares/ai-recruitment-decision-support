"""
APPLY JOB OPTIMIZATION & REMOTE PILOT READINESS -- FINAL FINISHING
SESSION (2026-10-04): Document/CV quality gate.

WHY A SEPARATE MODULE (not a change inside talent/utils.py or the OCR
engine): this wraps the EXISTING extract_text_from_pdf() (talent/
utils.py -- itself wrapping ai_engine's native-text + OCR/Azure/
Tesseract extraction, none of which is touched here) into ONE
deterministic result object, so Apply Job can decide -- BEFORE an
Application row is created and BEFORE any expensive AI call runs --
whether the uploaded document is usable. No OCR rewrite, no new
extraction logic: this classifies the SAME outcome
extract_text_from_pdf() already produces (either returned text, or a
raised CVExtractionError) into explicit fields instead of a bare
error string, so the decision is auditable/loggable.

Distinguishes DOCUMENT_INVALID (this module) from AI_PROCESSING_FAILED
(recruitment_pipeline.py) and AI_PROCESSING_SUCCESS -- these are
different states per the task instructions. A document classified
invalid here never reaches analyze_cv/Rule Engine/Skill
Matching/RAG/fused reasoning at all.
"""

from dataclasses import dataclass
from typing import Optional

from .utils import (
    extract_text_from_pdf,
    CVExtractionError,
    MIN_NATIVE_TEXT_CHARS,
)


@dataclass
class DocumentQualityResult:
    valid: bool
    reason: str
    extracted_text: Optional[str]
    extracted_text_length: int
    extraction_method: str  # "native" | "ocr" | "unknown" (unknown only when invalid)
    ocr_used: bool
    quality_notice: Optional[str]  # e.g. OCR LOW-confidence / extraction notice, if any


# User-facing message for the generic "could not be read" case, kept
# separate from the more specific messages already raised by
# extract_text_from_pdf() (which are themselves already candidate-safe,
# non-technical text -- see talent/utils.py). Used only as a fallback
# if a future CVExtractionError message were ever technical; today
# every existing message is shown as-is because it already is
# candidate-appropriate and more actionable than this generic text.
GENERIC_INVALID_DOCUMENT_MESSAGE = (
    "Your CV could not be read correctly by the system. Please upload "
    "a clear and complete CV in PDF format and make sure the document "
    "is not corrupted or password-protected."
)


def check_document_quality(pdf_path):
    """
    Runs the EXISTING extraction path exactly once and classifies the
    result. Never raises -- CVExtractionError is caught here and
    turned into a valid=False result instead of propagating, so the
    caller gets one consistent decision object instead of needing its
    own try/except around extraction internals.
    """

    try:
        text = extract_text_from_pdf(pdf_path)
    except CVExtractionError as e:
        # The message raised by extract_text_from_pdf() is already
        # candidate-safe, non-technical text (see talent/utils.py) --
        # no stack trace, no internal detail. Shown as-is.
        return DocumentQualityResult(
            valid=False,
            reason=str(e) or GENERIC_INVALID_DOCUMENT_MESSAGE,
            extracted_text=None,
            extracted_text_length=0,
            extraction_method="unknown",
            ocr_used=False,
            quality_notice=None,
        )

    ocr_used = text.startswith("[OCR NOTICE:") or text.startswith(
        "[EXTRACTION NOTICE:"
    )

    quality_notice = None
    if ocr_used:
        # Existing convention (talent/utils.py): the notice is a
        # bracketed prefix ending in "]\n\n" before the real text.
        end = text.find("]\n\n")
        if end != -1:
            quality_notice = text[1:end]

    extraction_method = "ocr" if ocr_used else "native"

    # Defense-in-depth, not new logic duplicating a different
    # threshold: extract_text_from_pdf() already guarantees usable
    # text length via MIN_NATIVE_TEXT_CHARS (native path) or
    # OCRQuality.FAILED (OCR path) before ever returning text. This is
    # a second, independent confirmation using the same constant, in
    # case a future caller/path ever returns text without going
    # through those guards.
    stripped_length = len(text.strip())

    if stripped_length < MIN_NATIVE_TEXT_CHARS:
        return DocumentQualityResult(
            valid=False,
            reason=(
                "The extracted document text is too short to be a "
                "usable CV. " + GENERIC_INVALID_DOCUMENT_MESSAGE
            ),
            extracted_text=text,
            extracted_text_length=stripped_length,
            extraction_method=extraction_method,
            ocr_used=ocr_used,
            quality_notice=quality_notice,
        )

    return DocumentQualityResult(
        valid=True,
        reason="",
        extracted_text=text,
        extracted_text_length=stripped_length,
        extraction_method=extraction_method,
        ocr_used=ocr_used,
        quality_notice=quality_notice,
    )