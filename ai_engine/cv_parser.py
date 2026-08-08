from PyPDF2 import PdfReader
from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract

def extract_cv_text(pdf_path):

    text = ""

    reader = PdfReader(pdf_path)

    for page in reader.pages:

        page_text = page.extract_text()

        if page_text:
            text += page_text

    if len(text.strip()) > 100:
        return text

    images = convert_from_path(pdf_path)

    ocr_text = ""

    for image in images:

        ocr_text += pytesseract.image_to_string(
              image,
              lang='eng+por+kor'
        )

    return ocr_text


def calculate_match(
    cv_text,
    requirements
):

    skills = requirements.split(',')

    score = 0

    for skill in skills:

        if skill.lower() in cv_text.lower():
            score += 1

    return (score / len(skills)) * 100