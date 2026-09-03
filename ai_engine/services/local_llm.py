import json
import logging

from .ollama_llm import generate


logger = logging.getLogger(__name__)


def generate_json(prompt, default=None):
    default = default or {}

    try:
        raw = generate(
            prompt,
            json_mode=True
        )

        return json.loads(raw)

    except (json.JSONDecodeError, RuntimeError, ValueError) as exc:
        logger.error(
            "LLM JSON generation failed: %s",
            exc
        )

        return default