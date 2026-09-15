"""
STEP 5 -- validates BREVO_API_KEY directly against Brevo's own
account-info endpoint (GET /v3/account), which is Brevo's official
recommended way to check whether an API key authenticates
successfully -- without spending any of your 300/day send quota.

HOW TO RUN:
    python test_brevo_manual.py

This reads BREVO_API_KEY from your local .env. To test the EXACT
value currently configured on Render (which is what actually matters
for the production 401), temporarily copy that same value into your
local .env, run this, then remove it again -- or run the equivalent
check via Render's Build Command as a one-off (ask if you want that
version instead).

Never prints the full key -- only whether it exists, its length, and
its first few characters (enough to eyeball whether the right key
got pasted, e.g. "xkeysib-..." vs something else entirely).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("BREVO_API_KEY", "")

print("=" * 60)
print("STEP 5 -- Brevo API key validation")
print("=" * 60)

print(f"\nBREVO_API_KEY exists: {bool(api_key)}")

if not api_key:
    print("FAIL -- BREVO_API_KEY not found in your .env.")
    sys.exit(1)

print(f"BREVO_API_KEY length: {len(api_key)}")
print(f"BREVO_API_KEY prefix: {api_key[:10]}...")

import requests

try:
    response = requests.get(
        "https://api.brevo.com/v3/account",
        headers={"api-key": api_key, "Accept": "application/json"},
        timeout=10,
    )
except requests.exceptions.RequestException as e:
    print(f"\nFAIL -- could not reach Brevo at all: {e}")
    sys.exit(1)

print(f"\nHTTP status: {response.status_code}")

try:
    body = response.json()
except ValueError:
    body = {"raw": response.text[:300]}

if response.status_code == 200:
    print("\nPASS -- API key is valid and authenticated.")
    print(f"Account email: {body.get('email')}")
    print(f"Company name: {body.get('companyName')}")
    plan = body.get("plan", [])
    if plan:
        print(f"Plan type: {plan[0].get('type')}")
else:
    print("\nFAIL -- Brevo rejected this API key.")
    print(f"Brevo error code: {body.get('code')}")
    print(f"Brevo error message: {body.get('message')}")