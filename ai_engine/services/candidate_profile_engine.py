import re


def extract_languages(text):

    known_languages = [
        "English",
        "Portuguese",
        "Tetum",
        "Indonesian",
        "Korean"
    ]

    found = []

    text_lower = text.lower()

    for language in known_languages:

        if language.lower() in text_lower:
            found.append(language)

    return found


def extract_certifications(text):

    known_certifications = [

        "AWS",

        "Google Data Analytics",

        "Cisco",

        "CCNA",

        "Microsoft",

        "Oracle",

        "CompTIA"

    ]

    found = []

    text_lower = text.lower()

    for cert in known_certifications:

        if cert.lower() in text_lower:

            found.append(cert)

    return found


import re


def extract_years_experience(text):

    patterns = [

        r'(\d+)\s+years',

        r'(\d+)\s+year',

        r'(\d+)\s+anos',

        r'(\d+)\s+ano',

        r'tinan\s+(\d+)',

    ]

    text_lower = text.lower()

    max_years = 0

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text_lower
        )

        for match in matches:

            years = int(match)

            if years > max_years:

                max_years = years

    return max_years    