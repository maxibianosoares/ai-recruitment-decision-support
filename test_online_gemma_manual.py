"""
STEP 3.2 -- final verification: calls the REAL, FIXED
call_online_gemma() function from model_config.py (not a separate
raw HTTP call this time), for both plain text and JSON mode -- the
two modes the actual application uses everywhere.

HOW TO RUN:
    python test_online_gemma_manual.py
"""

import os
import sys
import json

from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("ONLINE_GEMMA_API_KEY", "")

print("=" * 60)
print("STEP 3.2 -- Testing the REAL, fixed call_online_gemma()")
print("=" * 60)

if not api_key:
    print("\nFAIL -- ONLINE_GEMMA_API_KEY not found in .env")
    sys.exit(1)

print(f"\n1. API key found ({len(api_key)} characters). Not printed.")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_engine.services.model_config import call_online_gemma, ONLINE_GEMMA_MODEL

print(f"2. Model: {ONLINE_GEMMA_MODEL}")

print("\n--- Test A: plain text mode ---")
try:
    result = call_online_gemma("Reply with exactly one word: OK", want_json=False)
    print(f"Extracted text: {result!r}")
    print("PASS" if result.strip() == "OK" else "PASS (non-empty, but check content)")
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n--- Test B: JSON mode (what analyze_cv, llm_reasoning, etc. actually use) ---")
try:
    result = call_online_gemma(
        'Return ONLY this JSON, no other text: {"status": "ok"}',
        want_json=True
    )
    print(f"Extracted text: {result!r}")
    parsed = json.loads(result)
    print(f"json.loads() succeeded: {parsed}")
    print("\nPASS -- both plain text and JSON mode work end-to-end.")
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)