"""
TASK G (2026-10-03) -- smart routing + caching for the SCANNED-DOCUMENT
branch only.

IMPORTANT: this module is only ever reached from talent/utils.py AFTER
native (pypdf) text extraction has already been tried and judged
insufficient. It never sees a normal digital PDF -- that fast path is
completely unchanged (see talent/utils.py). This preserves the exact
flow the user specified:

    native extraction -> good text -> done (never touches this file)
                       -> poor/no text -> extract_scanned_document() (here)

Routing priority inside this module (smallest safe addition on top of
the existing Tesseract-only behavior):

    1. Azure Document Intelligence, if configured AND the file is
       within the F0 size limit.
    2. Tesseract (ai_engine/services/ocr_fallback.py, UNCHANGED), if
       Azure is not configured, the file is too large for F0, or Azure
       fails for any reason (transient or permanent -- see rationale
       below).
    3. If both fail (or neither is usable), propagate the failure to
       talent/utils.py exactly as before this task -- no new failure
       mode is introduced.

WHY AZURE FAILURES DON'T RETRY AZURE BEFORE FALLING BACK: a bounded
retry (like the LLM reliability fix in model_config.py) makes sense
when there's no alternative provider to fall back to. Here there
already IS a working alternative (Tesseract), and Azure F0 is limited
to 1 request/second -- retrying Azure first would only add latency for
no extra reliability benefit. So any Azure failure (transient or
permanent) falls straight through to Tesseract instead. This is a
deliberate simplicity choice per the "do not optimize for more code"
instruction, not an oversight -- documented here so it isn't mistaken
for one.

CACHING (Decision 2, see chat): keyed by SHA-256 of the file's actual
bytes, stored in Django's cache framework (django.core.cache.cache).
No database migration, no new model field -- Django's cache defaults
to LocMemCache with zero configuration, which is enough to cover the
realistic repeat case here (the SAME candidate re-applying to a
DIFFERENT job with the SAME CV file, which re-triggers extraction
today). A persistent (DB-backed) cache was deliberately NOT used:
nothing currently repeats this exact extraction across process
restarts in a way that would justify a migration, and LocMemCache
already lines up with the Procfile's single gunicorn worker. If a
multi-worker deployment is adopted later, this degrades gracefully to
"no cache hit across workers" (correct but less effective) rather than
breaking -- not "needs a migration to keep working."
"""

import hashlib
import logging
import time

from django.core.cache import cache

from . import azure_extractor
from ..ocr_fallback import (
    extract_text_via_ocr,
    assess_text_quality,
    OCRQuality,
)
from .result import DocumentExtractionResult

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "docext:v1:"
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h -- generous enough to cover a
                                  # candidate re-applying same-day,
                                  # short enough that a stale result
                                  # from a since-fixed Azure config
                                  # doesn't linger indefinitely.


def _file_sha256(pdf_path):
    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _try_azure(pdf_path, total_pages):
    start = time.perf_counter()
    try:
        result = azure_extractor.extract_with_azure(
            pdf_path, total_pages=total_pages
        )
    except azure_extractor.AzureExtractionError as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.warning(
            "[DOCUMENT-EXTRACTION] Azure attempt failed after "
            "%.0fms (status=%s transient=%s): %s -- falling back to "
            "Tesseract.",
            elapsed, e.status_code, e.is_transient, e
        )
        return None

    result.quality = assess_text_quality(result.text)

    if result.quality == OCRQuality.FAILED:
        logger.warning(
            "[DOCUMENT-EXTRACTION] Azure returned FAILED-quality text "
            "(empty/too little content) -- falling back to Tesseract "
            "in case it does better on this specific document."
        )
        return None

    return result


def _try_tesseract(pdf_path):
    start = time.perf_counter()
    text, quality, page_count = extract_text_via_ocr(pdf_path)
    processing_time_ms = (time.perf_counter() - start) * 1000

    return DocumentExtractionResult(
        provider="tesseract",
        text=text,
        quality=quality,
        page_count=page_count,
        processing_time_ms=processing_time_ms,
    )


def extract_scanned_document(pdf_path, total_pages=None):
    """
    Returns a DocumentExtractionResult. Raises OCRProcessingError only
    if EVERY available method failed to even produce output (mirrors
    extract_text_via_ocr's existing contract exactly, so
    talent/utils.py's except block needs no change).
    """

    file_hash = _file_sha256(pdf_path)
    cache_key = CACHE_KEY_PREFIX + file_hash

    cached = cache.get(cache_key)
    if cached is not None:
        cached.from_cache = True
        logger.info(
            "[DOCUMENT-EXTRACTION] cache hit (hash=%s..., provider=%s) "
            "-- skipping re-extraction.",
            file_hash[:12], cached.provider
        )
        return cached

    result = None

    if azure_extractor.is_configured():
        result = _try_azure(pdf_path, total_pages)

    if result is None:
        # Azure not configured, too-large file, or Azure failed --
        # Tesseract is the existing, always-available fallback.
        # extract_text_via_ocr() itself still raises
        # OCRProcessingError if the PDF can't even be rendered, which
        # propagates unchanged to talent/utils.py.
        result = _try_tesseract(pdf_path)

    if result.quality != OCRQuality.FAILED:
        # Only cache a usable result -- a FAILED attempt might succeed
        # later (e.g. once Azure is configured, or after a transient
        # outage clears), so it must not be "stuck" in the cache.
        cache.set(cache_key, result, timeout=CACHE_TTL_SECONDS)

    return result