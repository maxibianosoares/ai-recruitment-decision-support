import json
import requests

from .model_config import (
    MODEL_NAME,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT_SECONDS,
    LLM_PROVIDER,
    call_online_gemma
)


def generate_json(
    prompt,
    default=None
):

    try:

        if LLM_PROVIDER == "online_gemma":

            raw_response = call_online_gemma(prompt, want_json=True)

        else:

            payload = {
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }

            response = requests.post(
                OLLAMA_GENERATE_URL,
                json=payload,
                timeout=OLLAMA_TIMEOUT_SECONDS
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
