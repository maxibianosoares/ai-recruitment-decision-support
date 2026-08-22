import json
import re
from ollama import Client


MODEL_NAME = "gemma3:12b"

OLLAMA_HOST = "http://127.0.0.1:11434"

client = Client(
    host=OLLAMA_HOST
)


def clean_response(text):

    text = text.strip()

    text = re.sub(
        r"^```json",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```",
        "",
        text
    )

    text = re.sub(
        r"```$",
        "",
        text
    )

    return text.strip()


def extract_json(text):

    text = clean_response(text)

    return json.loads(text)


def generate(
    prompt,
    temperature=0,
    num_predict=700
):

    response = client.chat(

        model=MODEL_NAME,

        options={
            "temperature": temperature,
            "num_predict": num_predict
        },

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]

    )

    return response["message"]["content"]


def generate_json(
    prompt,
    default=None,
    temperature=0,
    num_predict=700,
    retries=2
):

    last_error = None

    for i in range(retries):

        try:

            content = generate(
                prompt,
                temperature=temperature,
                num_predict=num_predict
            )

            print(
                f"\n===== LLM RESPONSE ({i+1}) =====\n"
            )

            print(content)

            print(
                "\n===============================\n"
            )

            return extract_json(content)

        except Exception as e:

            last_error = e

            print(
                f"Retry {i+1} failed : {e}"
            )

    print(
        f"LLM failed : {last_error}"
    )

    if default is not None:

        return default

    return {
        "error": str(last_error)
    }