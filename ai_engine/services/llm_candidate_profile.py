import json

from .llm_service import generate_json

MULTILINGUAL_INSTRUCTION = """
The CV and Job Description may be written in English, Portuguese, Tetum,
Indonesian, or a mixture of these languages.

You must understand the meaning regardless of the language used.

Perform semantic analysis across languages.

Treat equivalent concepts as identical.

Examples

Bachelor Degree
Licenciatura
Sarjana
Graus Universitários

represent the same education level.

Likewise

Teamwork
Trabalho em equipa
Kerja sama
Servisu hamutuk

represent the same soft skill.

Extract information based on meaning rather than exact wording.
"""


DEFAULT_PROFILE = {
    "education": "",
    "skills": [],
    "languages": [],
    "certifications": [],
    "years_experience": 0,
    "professional_summary": ""
}


def analyze_cv(cv_text):

    prompt = f"""
You are an expert AI Recruitment Analyst.

{MULTILINGUAL_INSTRUCTION}

Analyze the following CV.

Extract the candidate profile.

Return ONLY valid JSON.

Schema

{json.dumps(DEFAULT_PROFILE, indent=4)}

Rules

- Return JSON only.
- No markdown.
- No explanation.
- skills must always be an array.
- languages must always be an array.
- certifications must always be an array.
- years_experience must be integer.
- Missing information should be empty.

CV

{cv_text}
"""

    try:

        result = generate_json(
            prompt=prompt
        )

        print("\n===== PROFILE RESPONSE =====\n")
        print(json.dumps(result, indent=4))
        print("\n============================\n")

        return result

    except Exception as e:

        print(f"Candidate Profile Error: {e}")

        profile = DEFAULT_PROFILE.copy()
        profile["error"] = str(e)

        return profile


def analyze_cv_to_dict(cv_text):
    return analyze_cv(cv_text)