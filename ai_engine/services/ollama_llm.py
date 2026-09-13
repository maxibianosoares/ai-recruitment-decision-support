import requests

from .model_config import (
    MODEL_NAME,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT_SECONDS,
    LLM_PROVIDER,
    call_online_gemma
)


_session = requests.Session()


def generate(prompt: str, json_mode: bool = True) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    if LLM_PROVIDER == "online_gemma":

        try:
            text = call_online_gemma(prompt, want_json=json_mode)
        except Exception as exc:
            raise RuntimeError(
                f"Online Gemma request failed: {exc}"
            ) from exc

        if not text or not text.strip():
            raise RuntimeError(
                "Online Gemma returned an empty response."
            )

        return text.strip()

    payload = {
        "model": MODEL_NAME,
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
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS
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
