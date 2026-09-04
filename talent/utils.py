from pypdf import PdfReader


class CVExtractionError(Exception):
    """Raised when no usable text could be extracted from an uploaded CV PDF."""
    pass


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

    if len(text.strip()) < 50:
        raise CVExtractionError(
            "No readable text was found in this PDF. This usually means the "
            "file is a scanned image rather than a digital document. Please "
            "upload a digitally-generated PDF CV (not a scanned copy)."
        )

    return text
