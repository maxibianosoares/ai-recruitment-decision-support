import os
import requests


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "gemma3:12b"
)


_session = requests.Session()


def generate(prompt: str, json_mode: bool = True) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1
        }
    }

    if json_mode:
        payload["format"] = "json"

    try:
        response = _session.post(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            json=payload,
            timeout=120
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Ollama request failed: {exc}"
        ) from exc

    text = data.get("response", "").strip()

    if not text:
        raise RuntimeError(
            "Ollama returned an empty response."
        )

    return text