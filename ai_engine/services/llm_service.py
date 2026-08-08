import json
import requests


OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL_NAME = "llama3.2"


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