import json
import re

import ollama

from ai_engine.services.llm_candidate_profile import (
    MULTILINGUAL_INSTRUCTION
)

MODEL_NAME = "gemma3:12b"

DEFAULT_RESULT = {
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
    "recommendation": ""
}


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
    job_profile
):
    """
    Evaluates candidate-to-job fit per dimension using the LLM,
    so it can reason about synonyms/ontology (e.g. "Database
    Management" ~ "PostgreSQL Administration") instead of pure
    vector similarity.

    Both arguments are plain dicts (candidate profile / AI-extracted
    job profile), consistent with the rest of the pipeline.
    """

    prompt = f"""You are an expert recruitment analyst. Score how well the candidate matches the job, dimension by dimension.

{MULTILINGUAL_INSTRUCTION}

Treat synonymous or related terms as matching (e.g. "Database Management" and "PostgreSQL Administration" should be scored as related skills, not unrelated ones).

All numeric scores are integers from 0 to 100. Keep "reasoning" values to one short sentence each. Return ONLY this JSON, no markdown, no extra text:

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

Job Profile
{json.dumps(job_profile, indent=2)}
"""

    try:

        response = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            format="json"
        )

        content = response["message"]["content"]

        return extract_json(content)

    except Exception as e:

        result = DEFAULT_RESULT.copy()
        result["dimension_scores"] = DEFAULT_RESULT["dimension_scores"].copy()
        result["recommendation"] = f"Semantic matching unavailable: {e}"

        return result