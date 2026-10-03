from pypdf import PdfReader


class CVExtractionError(Exception):
    """Raised when no usable text could be extracted from an uploaded CV PDF."""
    pass


# Same threshold the native-extraction path always used -- kept as a
# module constant now that it's also referenced when deciding whether
# to fall back to OCR (see below), instead of a bare literal.
MIN_NATIVE_TEXT_CHARS = 50


def extract_text_from_pdf(pdf_path):

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        raise CVExtractionError(
            "The uploaded file could not be read as a PDF. "
            "Please upload a valid PDF file."
        ) from e

    text = ""

    for page in reader.pages:
        text += page.extract_text() or ""

    if len(text.strip()) >= MIN_NATIVE_TEXT_CHARS:
        # Native text layer present and usable -- this is the exact
        # same fast path Phase 20 already had. Nothing below is
        # invoked here, so digitally-generated PDFs (the common case)
        # see no added latency at all from the change below.
        return text

    # -----------------------------------------------------------
    # SCANNED-DOCUMENT PATH (TASK G, 2026-10-03) -- native extraction
    # found no usable text, which usually means this is a
    # scanned/image-based PDF rather than a digitally-generated one.
    # Smart-routes to Azure Document Intelligence (if configured) with
    # an automatic fallback to the existing Tesseract OCR path --
    # see ai_engine/services/document_extraction/router.py for the
    # full routing/caching design. Tesseract-only behavior (what this
    # function did before TASK G) is preserved exactly when Azure is
    # not configured.
    # -----------------------------------------------------------

    try:
        from ai_engine.services.document_extraction.router import (
            extract_scanned_document,
        )
        from ai_engine.services.ocr_fallback import (
            OCRQuality,
            OCRProcessingError,
        )
    except ImportError as e:
        raise CVExtractionError(
            "No readable text was found in this PDF (it may be a scanned "
            "image), and the document extraction fallback could not be "
            "loaded on this server. Please upload a digitally-generated "
            "PDF CV, or contact the administrator."
        ) from e

    try:
        extraction = extract_scanned_document(
            pdf_path, total_pages=len(reader.pages)
        )
    except OCRProcessingError as e:
        raise CVExtractionError(
            "No readable text was found in this PDF, and OCR processing "
            "failed. This usually means the file is corrupted or the scan "
            "quality is too low to even render. Please upload a clearer "
            "scan or a digitally-generated PDF."
        ) from e

    ocr_text = extraction.text
    quality = extraction.quality

    if quality == OCRQuality.FAILED:
        raise CVExtractionError(
            "No readable text could be extracted from this PDF, even with "
            "OCR. This usually means the scan quality is too low, or the "
            "document uses a language/script that could not be recognized. "
            "Please upload a clearer scan or a digitally-generated PDF."
        )

    if quality == OCRQuality.LOW:
        # Proceed, but flag clearly -- both for the human (the view
        # checks for this exact marker to show a warning message) and
        # for the LLM reading this text downstream (analyze_cv's
        # prompt), so low-confidence extraction output is never
        # silently treated as ground truth by either. This is the
        # existing "partial success, human review encouraged" path --
        # unchanged by TASK G, and now shared by both providers.
        ocr_text = (
            "[OCR NOTICE: This text was extracted via OCR from a scanned "
            "document, and extraction confidence is LOW. Some information "
            "below may be missing, garbled, or misread. Treat details "
            "from this document with appropriate caution rather than as "
            "certain fact.]\n\n" + ocr_text
        )

    if extraction.warnings:
        # e.g. the Azure F0 "only first 2 pages analyzed" notice --
        # surfaced the same way as the LOW-quality notice above, so a
        # human reviewing this candidate sees it without needing to
        # read server logs.
        ocr_text = (
            "[EXTRACTION NOTICE: " + " ".join(extraction.warnings) + "]\n\n"
            + ocr_text
        )

    return ocr_text