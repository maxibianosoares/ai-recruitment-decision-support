from paddleocr import PaddleOCR

print("Loading model...")

ocr = PaddleOCR(
    lang="en"
)

print("Model loaded")

image = r"D:\Handong Global University\SEMESTER 1\Digital Government Policy\ai_recruitment_platform\media\cv\Bilhete Identiidade oin.jpg"

print("Start OCR...")

result = ocr.predict(image)

print("OCR Finished")

print(result)