import json
import re

import ollama

from ai_engine.services.llm_candidate_profile import (
    MULTILINGUAL_INSTRUCTION
)

MODEL_NAME = "gemma3:12b"
# MODEL_NAME = "qwen3:8b"


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


def semantic_match(
    candidate_profile,
    job
):

    prompt = f"""
You are an expert recruitment analyst.

{MULTILINGUAL_INSTRUCTION}

Evaluate how well this candidate matches the job.

The candidate profile and job description may be written in different languages.

Evaluate based on:

- Education
- Professional Experience
- Technical Skills
- Soft Skills
- Certifications
- Languages
- Overall suitability

Return ONLY valid JSON.

Schema:

{{
    "overall_score": 0,

    "dimension_scores": {{
        "education": 0,
        "experience": 0,
        "technical_skills": 0,
        "soft_skills": 0,
        "certifications": 0,
        "languages": 0
    }},

    "strengths": [],

    "weaknesses": [],

    "reasoning": {{
        "education": "",
        "experience": "",
        "technical_skills": "",
        "soft_skills": "",
        "certifications": "",
        "languages": ""
    }},

    "recommendation": ""
}}

Candidate Profile

{json.dumps(candidate_profile, indent=2)}

Job Title

{job.title}

Job Description

{job.description}

Job Requirements

{job.requirements}
"""

    try:

        response = ollama.chat(

            model=MODEL_NAME,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]

        )

        content = response["message"]["content"]

        print("\n===== SEMANTIC MATCH =====\n")
        print(content)
        print("\n==========================\n")

        return extract_json(content)

    except json.JSONDecodeError:

        return {

            "overall_score": 0,

            "dimension_scores": {
                "education": 0,
                "experience": 0,
                "technical_skills": 0,
                "soft_skills": 0,
                "certifications": 0,
                "languages": 0
            },

            "strengths": [],

            "weaknesses": [],

            "reasoning": {},

            "recommendation": "Invalid JSON returned by Ollama"

        }

    except Exception as e:

        return {

            "overall_score": 0,

            "dimension_scores": {
                "education": 0,
                "experience": 0,
                "technical_skills": 0,
                "soft_skills": 0,
                "certifications": 0,
                "languages": 0
            },

            "strengths": [],

            "weaknesses": [],

            "reasoning": {},

            "recommendation": str(e)

        }