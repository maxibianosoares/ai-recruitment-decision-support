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

Recruitment/civil-service terms also vary by language but mean the same
role or concept, for example: civil service / função pública / servisu
públiku / aparatur sipil -- or: vacancy / vaga / pozisaun / lowongan -- or:
professional experience / experiência profissional / esperiénsia
profisionál / pengalaman kerja. Apply the same principle to any other
recruitment term you encounter, even if not listed here.

Extract information based on meaning rather than exact wording. Do not
translate the source text yourself and do not lose legal/recruitment
meaning by paraphrasing loosely -- read in the original language, extract
the meaning, and write the structured output in the field's expected
format.

Extract only information that is actually stated or clearly implied in the
source document. Do not infer, guess, or fill in missing qualifications,
years of experience, certifications, employment history, or skills that
are not supported by the text. If information for a field is not present,
leave it empty rather than inventing a plausible-sounding value.
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