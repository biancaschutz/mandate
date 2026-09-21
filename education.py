import re

from helpers import INTERN, build_pattern, strip_html

EDU = {  # checked in this order: highest level first
    "M": [
        "advanced university degree",
        "Diplôme universitaire supérieur",
        "Master's degree",
        "Masters degree",
        "advanced degree",
        "Advanced postgraduate degree",
        "Título universitario superior",
        "master['’]?s?",
        "Postgraduate",
        "Grau universitário avançado",
        "mestrado",
        "maîtrise",
        "posgrado",
        "Maestría",
        "cuarto nivel",
    ],
    "B": [
        "first-level university degree",
        "university degree",
        "bachelor['’]?s?",
        "Licenciatura",
        "Academic BA",
        "Graduação",
    ],
    "S": [
        "High school diploma",
        "undergraduate",
        "university student",
        "Estudiante",
        "Student",
        "secondary school",
    ],
    "O": ["qualified lawyer", "medical degree", "PhD"],
}

EDU_PATTERNS = {
    key: re.compile(build_pattern(phrases), re.IGNORECASE)
    for key, phrases in EDU.items()
}


def get_education(text: str, is_internship: bool | None = None) -> str:
    """Highest education level mentioned: M, B, S (student), O (other) or U.

    Internships are assumed open to current students, so they return "S" when
    any degree keyword matches. Pass is_internship explicitly (from job type)
    whenever you know it. If left as None it falls back to searching the text
    for "intern", which misfires on regular jobs that mention supervising interns.
    """
    cleaned = strip_html(text)
    for key, pattern in EDU_PATTERNS.items():
        if pattern.search(cleaned):
            if is_internship is None:
                is_internship = bool(INTERN.search(cleaned))
            return "S" if is_internship else key
    return "U"
