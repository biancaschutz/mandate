import re
from bisect import bisect_right

from helpers import INTERN

MAX_YRS = 40

NUM_WORDS = {
    # English
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    # French
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "dix-sept": 17,
    "dix-huit": 18,
    "dix-neuf": 19,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    # Spanish
    "cero": 0,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
}

NUM_WORDS_RE = "|".join(
    re.escape(w) for w in sorted(NUM_WORDS, key=len, reverse=True)
)

YEARS_MULTILANG = r"(?:years?|ann[ée]es?|ans?|a[ñn]os?)"

YEARS_REGEX = re.compile(
    rf"""
    (?:
        (?P<range_start>\d+)\s*-\s*(?P<range_end>\d+)          # "3-5"
      |
        \b(?P<word>{NUM_WORDS_RE})\b                          # "five" / "cinq" / "cinco"
        (?:\s*\(\s*(?P<paren>\d+)\s*\))?                       # optional "(5)"
      |
        (?P<digit>\d+)                                         # "5" / "10"
        (?:\s*\(\s*(?P<rev_word>[a-zA-Zà-ÿÀ-ß-]+)\s*\))?      # optional "(five)"
    )
    \s*[-]?\s*\+?\s*
    {YEARS_MULTILANG}\b
    """,
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)


def extract_years(text: str) -> list[int]:
    if not text:
        return []
    results = []
    for m in YEARS_REGEX.finditer(text):
        if m.group("range_start"):
            results.append(int(m.group("range_start")))  # lower bound of ranges, ex 3-5 years as 3 years
        elif m.group("word"):
            paren = m.group("paren")
            results.append(
                int(paren) if paren else NUM_WORDS[m.group("word").lower()]
            )
        elif m.group("digit"):
            results.append(int(m.group("digit")))
    return results


UNKNOWN_STAGE = "U"
JOB_LEVELS = {
    "P1": "EL",
    "P2": "EC",
    "P3": "MC",
    "P4": "MC",
    "P5": "SL",
    "D1": "SL",
    "D2": "SL",
}

JOB_LEVEL_RE = re.compile(r"\b(P[1-5]|D[12])\b")

# specific to sources
LEVEL_LABELS = {
    "internship": "EL",
    "internship/volunteer": "EL",  # HRW
    "fellowship": "EL",            # WIPO, HRW
    "early career": "EC",          # HRW
}

STAGE_LABELS = ["EL", "EC", "MC", "MS", "SL"]
YEAR_CUTOFFS = [2, 5, 8, 10]  # <2 EL, 2-4 EC, 5-7 MC, 8-9 MS, 10+ SL


def match_level_label(*values):
    for value in values:
        if value and (stage := LEVEL_LABELS.get(value.strip().casefold())):
            return stage
    return None


def looks_like_internship(job_type, title=None) -> bool:
    """Matches "Internship" and "Internship/Volunteer", but not "internal"."""
    return bool(INTERN.search(job_type or "") or INTERN.search(title or ""))

def career_stage(job_level, job_type, qualifications, years, title=None) -> str:
    # first see if it has a UN job grade
    if job_level and (m := JOB_LEVEL_RE.search(job_level)):
        return JOB_LEVELS[m.group(1)]

    # then see if it has a job_level or type match
    if stage := match_level_label(job_level, job_type):
        return stage

    # if it says it's an internship, try that, unless it has a lot of years
    internship = looks_like_internship(job_type, title) or bool(
        qualifications and INTERN.search(qualifications)
    )
    if internship and (not years or years <= 2):
        return "EL"

    # check years of experience
    if years is not None:
        return STAGE_LABELS[bisect_right(YEAR_CUTOFFS, years)]

    return UNKNOWN_STAGE