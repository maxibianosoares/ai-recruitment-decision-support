"""
STEP 3.2 (lanjutan) -- diagnostik HTTP 404: panggil endpoint resmi
Google "ListModels" untuk melihat model APA SAJA yang benar-benar
tersedia untuk API key Anda, lalu filter yang berhubungan dengan
Gemma.

CARA MENJALANKAN (folder project, venv aktif):

    python diagnose_gemma_models.py

Skrip ini TIDAK PERNAH mencetak API key Anda -- hanya jumlah
karakternya. Aman untuk Anda copy-paste seluruh isi terminal ke saya.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("ONLINE_GEMMA_API_KEY", "")

base_url = os.environ.get(
    "ONLINE_GEMMA_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta"
)

print("=" * 60)
print("DIAGNOSTIK: Daftar model resmi Google untuk API key Anda")
print("=" * 60)

if not api_key:
    print("\nGAGAL: ONLINE_GEMMA_API_KEY tidak ditemukan di .env")
    sys.exit(1)

print(f"\n1. API key ditemukan ({len(api_key)} karakter). Tidak dicetak.")
print(f"2. Base URL: {base_url}")

import requests

list_url = f"{base_url.rstrip('/')}/models"

print(f"3. Memanggil: GET {list_url}?key=***\n")

try:
    response = requests.get(
        list_url,
        params={"key": api_key},
        timeout=30
    )
except Exception as e:
    print(f"GAGAL total memanggil endpoint: {e}")
    sys.exit(1)

print(f"4. HTTP Status: {response.status_code}\n")

if response.status_code != 200:
    # Scrub the key from anything before printing, just in case.
    text = response.text.replace(api_key, "***REDACTED***")
    print("Response body (key sudah disensor kalau ada):")
    print(text[:2000])
    sys.exit(1)

data = response.json()
models = data.get("models", [])

print(f"5. Total model yang dikembalikan untuk akun Anda: {len(models)}\n")

gemma_models = [
    m for m in models
    if "gemma" in m.get("name", "").lower()
]

print(f"6. Model yang mengandung 'gemma': {len(gemma_models)}\n")

if not gemma_models:
    print("   TIDAK ADA model Gemma ditemukan untuk API key/region Anda.")
else:
    for m in gemma_models:
        name = m.get("name", "?")
        display_name = m.get("displayName", "?")
        methods = m.get("supportedGenerationMethods", [])
        print(f"   - name           : {name}")
        print(f"     displayName    : {display_name}")
        print(f"     supported ops  : {methods}")
        print(f"     supports generateContent: {'generateContent' in methods}")
        print()

print("=" * 60)
print("Selesai. Salin SELURUH output di atas (aman, tidak ada key).")
print("=" * 60)
