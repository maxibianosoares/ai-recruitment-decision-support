def profile_to_text(profile):

    return f"""
Education:
{profile.get("education","")}

Experience:
{profile.get("years_experience","")}

Skills:
{", ".join(profile.get("skills",[]))}

Languages:
{", ".join(profile.get("languages",[]))}

Certifications:
{", ".join(profile.get("certifications",[]))}
"""