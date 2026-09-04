import os
from dotenv import load_dotenv
from google import genai
from ai_engine.services.llm_service import generate_json

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

print("====================================")
print("GEMINI TEST")
print("====================================")
print("API Key:", "configured" if api_key else "NOT CONFIGURED")
print("Model:", model)

if not api_key:
    print("ERROR: GEMINI_API_KEY is not configured.")
    raise SystemExit

try:
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents='Reply with exactly this JSON: {"status": "success", "message": "Gemini is working"}'
    )

    print(response.text)

except Exception as e:
    print("Gemini Error:", e)

print("====================================")


prompt_test = (
    "Berikan data 3 kota besar di Indonesia beserta jumlah penduduknya dalam format JSON. "
    "Contoh: {'kota': 'Nama', 'populasi': 1000000}"
)

hasil = generate_json(prompt=prompt_test, provider="gemini")
print(hasil)
