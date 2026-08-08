from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract
import os

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

POPPLER_PATH = os.getenv(
    "POPPLER_PATH",
    r"C:\poppler-26.02.0\Library\bin"
)

def extract_cv_text(pdf_path):

    text = ""

    try:

        reader = PdfReader(pdf_path)

        for page in reader.pages:

            page_text = page.extract_text()

            if page_text:
                text += page_text

    except Exception as e:

        print(f"PDF Extract Error: {e}")

    # PDF digital
    if len(text.strip()) > 100:

        print("PDF text layer found")

        return text

    # PDF scan → OCR

    print("Using OCR...")

    images = convert_from_path(
        pdf_path,
        poppler_path=POPPLER_PATH
    )

    ocr_text = ""

    for image in images:

        page_text = pytesseract.image_to_string(
            image,
            lang='eng+por+tet'
        )

        ocr_text += page_text + "\n"

    return ocr_text