import json
import re

import ollama
from ai_engine.services.llm_candidate_profile import (
    MULTILINGUAL_INSTRUCTION
)

MODEL_NAME = "gemma3:12b"

def extract_json(text):

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

    return json.loads(text.strip())


def extract_job_requirements(job_description):

    prompt = f"""
You are an expert HR analyst.
{MULTILINGUAL_INSTRUCTION}
Extract structured information from the following Job Description.

Return ONLY valid JSON.

Schema:

{{
    "job_title":"",
    "education":"",
    "minimum_experience":0,

    "required_skills":[],

    "preferred_skills":[],

    "soft_skills":[],

    "languages":[],

    "certifications":[],

    "responsibilities":[],

    "employment_type":"",

    "location":"",

    "summary":""
}}

Rules:

- Return JSON only.
- No markdown.
- Empty string if unavailable.
- Empty list if unavailable.
- Experience must be numeric.

Job Description:

{job_description}
"""

    try:

        response = ollama.chat(

            model=MODEL_NAME,

            messages=[
                {
                    "role":"user",
                    "content":prompt
                }
            ]

        )

        content = response["message"]["content"]

        print("\n===== JOB REQUIREMENT =====\n")
        print(content)
        print("\n===========================\n")

        return extract_json(content)

    except Exception as e:

        return {

            "job_title":"",

            "education":"",

            "minimum_experience":0,

            "required_skills":[],

            "preferred_skills":[],

            "soft_skills":[],

            "languages":[],

            "certifications":[],

            "responsibilities":[],

            "employment_type":"",

            "location":"",

            "summary":"",

            "error":str(e)

        }