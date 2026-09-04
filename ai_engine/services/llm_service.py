import json
import requests

# $env:LLM_PROVIDER="ollama"
# $env:OLLAMA_MODEL="gemma3:12b"


# $env:LLM_PROVIDER="gemini"
# $env:GEMINI_API_KEY="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"
# $env:GEMINI_MODEL="gemini-2.5-flash"

# GEMINI_API_KEY = "AQ.Ab8RN6LcbZcW6PGVvACZ1PG9FppBNequJmhGQzUp4QIaM7KI9Q"
# MODEL_NAME = "gemini-2.5-flash"

# # URL yang sudah diperbaiki strukturnya
# OLLAMA_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"


# def generate_json(prompt, default=None):

#     payload = {
#         "contents": [{"parts": [{"text": prompt}]}],
#         "generationConfig": {"responseMimeType": "application/json"},
#     }

#     try:

#         response = requests.post(OLLAMA_URL, json=payload, timeout=180)

#         response.raise_for_status()

#         data = response.json()

#         # Mengambil output teks JSON dari response Google Gemini
#         raw_response = (
#             data.get("candidates", [{}])[0]
#             .get("content", {})
#             .get("parts", [{}])[0]
#             .get("text", "")
#         )

#         if not raw_response:
#             return default or {}

#         return json.loads(raw_response)

#     except Exception as e:

#         print("LLM Error:", str(e))

#         return default or {}




OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL_NAME = "gemma3:12b"


def generate_json(
    prompt,
    default=None
):

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }

    try:

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=180
        )

        response.raise_for_status()

        data = response.json()

        raw_response = data.get(
            "response",
            ""
        )

        if not raw_response:
            return default or {}

        return json.loads(
            raw_response
        )

    except Exception as e:

        print(
            "LLM Error:",
            str(e)
        )

        return default or {}
