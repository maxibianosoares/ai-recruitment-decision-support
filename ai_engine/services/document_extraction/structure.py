"""
TASK I (2026-10-06) -- cheap structural check of an uploaded PDF.

Deliberately its own tiny module with ONE dependency (pypdf): the web
request imports it on every CV upload, and it must not pull in the OCR
stack (pdf2image / pytesseract), whose import is kept lazy elsewhere so
a server without those binaries still starts. Takes milliseconds; does
NOT extract any text.

Used by BOTH the web request (on the uploaded bytes, to reject an
unusable file instantly, before anything is stored) and the worker (on
the temp file, as the first step of extraction).
"""

import io
import os
from dataclasses import dataclass

from pypdf import PdfReader


def _env_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        return value if value >= 1 else default
    except ValueError:
        return default


# Upper bound on pages per CV. Work is linear in pages (about 2 s per
# scanned page here), so an unbounded page count is an unbounded
# worker job. 50 is far above any real CV and still bounded.
MAX_PAGES = _env_int("CV_MAX_PAGES", 50)

# Candidate-safe wording (no stack traces, no internals).
MSG_NOT_A_PDF = (
    "The uploaded file could not be read as a PDF. "
    "Please upload a valid PDF file."
)
MSG_ENCRYPTED = (
    "This PDF is password-protected, so it cannot be read. "
    "Please remove the password and upload it again."
)
MSG_NO_PAGES = "This PDF has no pages. Please upload your complete CV."
MSG_RENDER_FAILED = (
    "No readable text was found in this PDF, and OCR processing "
    "failed. This usually means the file is corrupted or the scan "
    "quality is too low to even render. Please upload a clearer "
    "scan or a digitally-generated PDF."
)
MSG_NO_TEXT = (
    "No readable text could be extracted from this PDF, even with "
    "OCR. This usually means the scan quality is too low, or the "
    "document uses a language/script that could not be recognized. "
    "Please upload a clearer scan or a digitally-generated PDF."
)
MSG_LOW_QUALITY = (
    "Your CV could only be read with very low confidence (the "
    "extracted text is mostly unreadable symbols). Please upload a "
    "clearer scan or a digitally-generated PDF."
)


def msg_too_many_pages(count):
    return (
        f"This PDF has {count} pages, which is more than the "
        f"{MAX_PAGES}-page limit for a CV. Please upload a shorter "
        "document."
    )


def msg_failed_pages(pages):
    listed = ", ".join(str(p) for p in pages)
    return (
        f"Some pages of your CV could not be processed (page {listed}), "
        "so the CV would be read incompletely. Please upload a clearer "
        "scan or a digitally-generated PDF."
    )


@dataclass
class StructureCheck:
    ok: bool
    reason: str = ""
    page_count: int = 0


# ---------------------------------------------------------------------
# Structural check -- cheap (milliseconds), run by BOTH the web request
# (on the uploaded bytes) and the worker (on the temp file).
# ---------------------------------------------------------------------

def _open_reader(source):
    """PdfReader over bytes or a path, decrypted if it opens with an
    empty password. Raises ValueError(reason) for anything unusable."""

    if isinstance(source, (bytes, bytearray)):
        head = bytes(source[:1024])
        stream = io.BytesIO(source)
    else:
        with open(source, "rb") as f:
            head = f.read(1024)
        stream = source

    if b"%PDF-" not in head:
        raise ValueError(MSG_NOT_A_PDF)

    try:
        reader = PdfReader(stream)
    except Exception as e:
        raise ValueError(MSG_NOT_A_PDF) from e

    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception as e:
            raise ValueError(MSG_ENCRYPTED) from e
        if not decrypted:
            raise ValueError(MSG_ENCRYPTED)

    return reader


def check_pdf_structure(source):
    """Is this a PDF we can even attempt to read? Never raises."""

    try:
        reader = _open_reader(source)
        page_count = len(reader.pages)
    except ValueError as e:
        return StructureCheck(ok=False, reason=str(e))
    except Exception:
        return StructureCheck(ok=False, reason=MSG_NOT_A_PDF)

    if page_count < 1:
        return StructureCheck(ok=False, reason=MSG_NO_PAGES)

    if page_count > MAX_PAGES:
        return StructureCheck(
            ok=False,
            reason=msg_too_many_pages(page_count),
            page_count=page_count
        )

    return StructureCheck(ok=True, page_count=page_count)