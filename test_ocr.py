from pathlib import Path

import cv2
import easyocr
import numpy as np
from pdf2image import convert_from_path

# Load model sekali saja
reader = easyocr.Reader(
    ['en', 'pt', 'id'],
    gpu=False
)

POPPLER_PATH = r"C:\poppler-26.02.0\Library\bin"

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp"
}


def preprocess(image):
    """
    Preprocessing sederhana untuk meningkatkan hasil OCR.
    """

    if isinstance(image, str):
        image = cv2.imread(image)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    gray = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]

    return gray


def read_image(image):
    """
    OCR untuk satu gambar.
    """

    image = preprocess(image)

    result = reader.readtext(
        image,
        detail=1,
        paragraph=False
    )

    # Urutkan dari atas ke bawah
    result = sorted(
        result,
        key=lambda x: (
            min(point[1] for point in x[0]),
            min(point[0] for point in x[0])
        )
    )

    texts = []

    for box, text, confidence in result:

        if confidence < 0.40:
            continue

        texts.append(text)

    return texts


def extract_text(file_path):

    ext = Path(file_path).suffix.lower()

    all_text = []

    if ext == ".pdf":

        images = convert_from_path(
            file_path,
            poppler_path=POPPLER_PATH,
            dpi=300
        )

        for image in images:

            image_np = np.array(image)

            image_np = cv2.cvtColor(
                image_np,
                cv2.COLOR_RGB2BGR
            )

            all_text.extend(
                read_image(image_np)
            )

    elif ext in IMAGE_EXTENSIONS:

        all_text.extend(
            read_image(file_path)
        )

    else:

        raise ValueError(
            f"Format tidak didukung : {ext}"
        )

    return "\n".join(all_text)


if __name__ == "__main__":

    file_path = r"D:\Handong Global University\SEMESTER 1\Digital Government Policy\ai_recruitment_platform\media\cv\Cartaun Eleitoral.JPG"

    text = extract_text(file_path)

    print("=" * 80)
    print(text)
    print("=" * 80)