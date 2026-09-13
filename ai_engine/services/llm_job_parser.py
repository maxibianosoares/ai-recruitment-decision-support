import json

from .llm_service import generate_json
# from .local_llm import generate_json
from .llm_candidate_profile import MULTILINGUAL_INSTRUCTION


DEFAULT_JOB_PROFILE = {
    "job_title": "",
    "education": "",
    "skills": [],
    "languages": [],
    "certifications": [],
    "years_experience": 0,
    "professional_summary": ""
}


def analyze_job_description(job_description):

    prompt = f"""
You are an expert HR Recruitment Analyst.

{MULTILINGUAL_INSTRUCTION}

Analyze the following Job Description.

Extract ONLY factual information.

Everything you extract (education, experience, skills, languages,
certifications) describes what THIS SPECIFIC VACANCY is asking for. Do not
present it as, or confuse it with, a national law or civil-service-wide
legal requirement -- a vacancy can ask for more (or less) than the legal
minimum, and this schema only captures what this posting states.

Return ONLY valid JSON.

Schema

{json.dumps(DEFAULT_JOB_PROFILE, indent=4)}

Rules

- Return JSON only.
- No markdown.
- No explanation.
- skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.

Job Description

{job_description}
"""

    try:

        result = generate_json(
            prompt=prompt
        )

        print("\n===== JOB PARSER RESPONSE =====\n")
        print(json.dumps(result, indent=4))
        print("\n===============================\n")

        return result

    except Exception as e:

        print(f"Job Parser Error: {e}")

        profile = DEFAULT_JOB_PROFILE.copy()
        profile["error"] = str(e)

        return profile