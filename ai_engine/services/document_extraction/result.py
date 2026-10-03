"""
TASK G (2026-10-03) -- normalized, provider-independent extraction
result.

This is deliberately a thin dataclass, not a new framework: the rest of
the application (talent/utils.py, candidate.extracted_text) only ever
sees the existing (text, quality) shape it already understood before
this task -- this object exists so the *richer* Document Understanding
data (pages/tables/confidence/warnings) isn't thrown away at the
provider boundary, for later research use (RQ1/RQ2 in the thesis),
without forcing every existing caller to change.

Kept intentionally small: only the fields Azure's Layout model and the
existing Tesseract path can BOTH plausibly populate (Tesseract leaves
pages/tables/confidence empty -- that's an honest reflection of what
plain OCR actually gives you, not a bug).
"""

from dataclasses import dataclass, field


@dataclass
class DocumentExtractionResult:
    provider: str                 # "azure_document_intelligence" | "tesseract"
    text: str
    quality: str                  # ocr_fallback.OCRQuality value: OK/LOW/FAILED
    page_count: int = 0
    pages: list = field(default_factory=list)      # [{"page_number", "width", "height", "line_count"}]
    tables: list = field(default_factory=list)      # [{"row_count", "column_count", "page_number"}]
    confidence: float | None = None
    warnings: list = field(default_factory=list)    # list[str], human-readable
    processing_time_ms: float = 0.0
    from_cache: bool = False