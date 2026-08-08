from .skill_dictionary import SKILLS


def extract_skills(text):

    found_skills = []

    text_lower = text.lower()

    for skill in SKILLS:

        if skill.lower() in text_lower:

            found_skills.append(skill)

    return list(set(found_skills))