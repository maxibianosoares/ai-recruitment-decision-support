"""
TASK G (2026-10-03) -- Azure AI Document Intelligence extractor
(Layout model, F0/free tier by default).

Verified against the official Microsoft documentation before writing
this (not assumed):
  - SDK: azure-ai-documentintelligence==1.0.2 (current stable Python
    SDK, API version 2024-11-30). Pulls in only azure-core and isodate
    as new dependencies -- both lightweight, no native/binary deps
    (unlike pytesseract/pdf2image, which need Tesseract/Poppler system
    binaries installed separately).
  - F0 (free tier) limits (see
    https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/ai-services/document-intelligence/service-limits.md):
      * max document size: 4 MB
      * max pages analyzed per document: 2 (the free tier only
        analyzes the FIRST TWO PAGES of a longer document -- this is
        an Azure-imposed limit, not something this code invents or
        can work around by chunking; a paid (S0) tier removes it)
      * 1 transaction per second
    This module enforces the 4 MB limit itself (skips Azure entirely
    for an oversized file, falling through to Tesseract) and reports a
    warning when a document has more pages than F0 can analyze, so the
    limitation is visible instead of silently losing content.

WHY THE SDK INSTEAD OF RAW REST (Decision 3, see chat): the SDK's
begin_analyze_document() returns a standard azure.core LROPoller that
handles the operation-location/Retry-After polling loop internally --
hand-rolling that polling loop with `requests` would be re-implementing
a well-tested piece of Azure's own SDK for no real benefit, and would
be MORE code and MORE ways to get the async/retry semantics subtly
wrong, not less. The dependency footprint is small (2 extra packages,
confirmed via `pip install --dry-run`), both pure-Python. This keeps
the error-classification pattern consistent with
model_config.py's OnlineGemmaError (status_code + is_transient), so
callers don't need to learn two different error shapes.
"""

import os
import time

# F0 verified limits (see module docstring). Kept as module constants,
# not magic numbers, and named so a future paid-tier switch is a
# one-line change, not a code change.
AZURE_MAX_FILE_SIZE_BYTES = 4 * 1024 * 1024
AZURE_MAX_PAGES_ANALYZED = 2

# Transient (worth falling back for *this* request, not a sign the
# credential/config itself is broken) vs permanent, same convention as
# ai_engine/services/model_config.py's _ONLINE_GEMMA_TRANSIENT_STATUSES.
_AZURE_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}


class AzureExtractionError(RuntimeError):
    def __init__(self, message, status_code=None, is_transient=True):
        super().__init__(message)
        self.status_code = status_code
        self.is_transient = is_transient


def is_configured():
    """
    True only when BOTH the endpoint and key are present. Never raises.
    Callers (router.py) use this to decide whether to attempt Azure at
    all -- Azure is never a prerequisite for the application to run.
    """
    return bool(
        os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").strip()
        and os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()
    )


def _build_client():
    # Imported lazily, exactly like talent/utils.py's import of
    # ocr_fallback -- so a server that never configures Azure (or
    # hasn't installed the SDK for some reason) never pays an import
    # cost or risks an ImportError at Django startup.
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").strip()
    key = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()

    return DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )


def _normalize_result(analyze_result, processing_time_ms, warnings):
    """
    Builds the DocumentExtractionResult from the SDK's AnalyzeResult.
    Preserves pages/tables (STEP: "do not immediately flatten"),
    without inventing fields Azure doesn't actually return.
    """
    from .result import DocumentExtractionResult

    # .content is Azure's own full-document text in correct reading
    # order (already assembled across pages/columns by the service) --
    # this is the "text" that stays backward-compatible with
    # candidate.extracted_text.
    text = analyze_result.content or ""

    pages = []
    for p in (analyze_result.pages or []):
        pages.append({
            "page_number": p.page_number,
            "width": p.width,
            "height": p.height,
            "line_count": len(p.lines or []),
        })

    tables = []
    for t in (analyze_result.tables or []):
        page_number = None
        if t.bounding_regions:
            page_number = t.bounding_regions[0].page_number
        tables.append({
            "row_count": t.row_count,
            "column_count": t.column_count,
            "page_number": page_number,
        })

    return DocumentExtractionResult(
        provider="azure_document_intelligence",
        text=text,
        quality=None,  # assessed by the router using the shared heuristic
        page_count=len(pages),
        pages=pages,
        tables=tables,
        confidence=None,  # prebuilt-layout does not return a single
                           # document-level confidence score (only
                           # per-field confidence for prebuilt models
                           # like invoice/receipt) -- left None rather
                           # than inventing one.
        warnings=warnings,
        processing_time_ms=processing_time_ms,
    )


def extract_with_azure(pdf_path, total_pages=None):
    """
    Raises AzureExtractionError on any failure (including "not
    configured" or "file too large for F0") -- router.py decides what
    to do about it (fall back to Tesseract). Never raises anything
    else: SDK/network errors are caught and wrapped.
    """

    if not is_configured():
        raise AzureExtractionError(
            "Azure Document Intelligence is not configured "
            "(AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT/KEY not set).",
            is_transient=False
        )

    file_size = os.path.getsize(pdf_path)
    if file_size > AZURE_MAX_FILE_SIZE_BYTES:
        raise AzureExtractionError(
            f"File is {file_size} bytes, over the Azure F0 free-tier "
            f"limit of {AZURE_MAX_FILE_SIZE_BYTES} bytes -- skipping "
            f"Azure for this document rather than sending a request "
            f"guaranteed to be rejected.",
            is_transient=False
        )

    warnings = []
    if total_pages is not None and total_pages > AZURE_MAX_PAGES_ANALYZED:
        warnings.append(
            f"Azure Document Intelligence F0 (free tier) only analyzes "
            f"the first {AZURE_MAX_PAGES_ANALYZED} page(s) of a "
            f"document; this document has {total_pages} page(s), so "
            f"pages {AZURE_MAX_PAGES_ANALYZED + 1}-{total_pages} were "
            f"not analyzed by Azure. Upgrade to a paid (S0) tier to "
            f"remove this limit."
        )

    start = time.perf_counter()

    try:
        client = _build_client()

        with open(pdf_path, "rb") as f:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=f
            )

        analyze_result = poller.result()

    except AzureExtractionError:
        raise

    except Exception as e:
        # azure.core.exceptions.HttpResponseError exposes .status_code;
        # ServiceRequestError (network/timeout) and others don't --
        # getattr keeps this one code path honest for every shape
        # instead of importing and enumerating every azure.core
        # exception class individually.
        status_code = getattr(e, "status_code", None)
        is_transient = (
            status_code is None
            or status_code in _AZURE_TRANSIENT_STATUSES
        )
        # Never include the key in the message -- str(e) from
        # azure-core does not echo request headers, only the response
        # body/reason, so this is safe by construction, not by luck of
        # omission.
        raise AzureExtractionError(
            f"Azure Document Intelligence request failed "
            f"(HTTP {status_code if status_code is not None else 'no-response'}): {e}",
            status_code=status_code,
            is_transient=is_transient
        ) from None

    processing_time_ms = (time.perf_counter() - start) * 1000

    return _normalize_result(analyze_result, processing_time_ms, warnings)