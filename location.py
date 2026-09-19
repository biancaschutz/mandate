import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process, utils

from helpers import WHITESPACE

# Scraping errors / spelling, last updated September 2026
LITERAL_FIXES = [
    ("Nairobi, Nairobi, Kenya", "Nairobi, Kenya"),
    ("Multiple duty stations, Multiple duty stations", "Multiple duty stations"),
    ("Yangoon,  Myanmar", "Yangon, Myanmar"),
    ("Yangoon, Myanmar", "Yangon, Myanmar"),
    ("Phnom-Penh, Cambodia", "Phnom Penh, Cambodia"),
    ("Ha Noi, Viet Nam", "Hanoi, Viet Nam"),
    ("Geneva, Slovakia", "Geneva, Switzerland"),  # data error
    ("Suva, Fiji/Pacific Island Countries", "Suva, Fiji"),
    ("Vienna CO, Austria", "Vienna, Austria"),
    ("Caracas, Bolivarian Republic of Venezuela", "Caracas, Venezuela"),
]

# Homogenise country names, with options listed from longest to shortest to prevent shorter matches from matching inside longer 
COUNTRY_FIXES = [
    (r"Philippines \(the\)", "Philippines"),
    (r"Sudan \(the\)", "Sudan"),
    (r"Netherlands \(the Kingdom of the\)", "Netherlands"),
    (r"\b(?:United States of America|United States|USA)\b", "United States of America"),
    (
        r"Lao People['\u2019]?s Democratic Republic|\bLaos\b",
        "Lao People's Democratic Republic",
    ),
    (r"Republic of Moldova", "Moldova"),
    (r"State of Palestine \(SoP\)|Palestine, State of", "State of Palestine"),
    (r"\b(?:Turkiye|Turkey)\b", "Türkiye"),
    (
        (
            r"\b(?:United Kingdom of Great Britain and Northern Ireland|United Kingdom"
            r"|Great Britain|Northern Ireland|England|UK|GB)\b"
        ),
        "United Kingdom of Great Britain and Northern Ireland",
    ),
]

# dealing with repeated city/country options such as UNHQs in different formats and languages (ex. Geneva), and ensuring they have country names with them
RULES = [
    (r"Bruxelles|Brussel", "Brussels, Belgium"),
    (r"Cotabato City", "Cotabato City, Philippines"),
    (r"^Amsterdam$", "Amsterdam, Netherlands"),
    (r"Florence", "Florence, Italy"),
    (r"Geneva|Gen[eè]ve|Suisse", "Geneva, Switzerland"),
    (r"Home Based|Remote", "Remote"),
    (r"^Manila", "Manila, Philippines"),
    (r"^Nairobi", "Nairobi, Kenya"),
    (r"Multiple", "Multiple locations considered"),
]

COUNTRY_CLEANUP = [(re.compile(p), r) for p, r in COUNTRY_FIXES]
SPECIAL_CASES = [(re.compile(p, re.IGNORECASE), r) for p, r in RULES]

def clean_location(raw: str | None) -> str:
    """Clean one scraped location string (cached: locations repeat heavily)."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    s = raw.strip()
    for old, new in LITERAL_FIXES:
        s = s.replace(old, new)
    for pattern, repl in COUNTRY_CLEANUP:
        s = pattern.sub(repl, s)
    for pattern, repl in SPECIAL_CASES:
        if pattern.search(s):
            s = repl
            break
    return WHITESPACE.sub(" ", s).strip()


# Getting M49 codes and homogenizing country names

REMOTE = ("Remote", -1)
MULTIPLE = ("Multiple locations considered", -2)
UNIDENTIFIED = ("Unidentified", None)

countries = pd.read_csv(Path(__file__).with_name("uncountries.csv")) # mapping from UNSD
COUNTRY_CODES = countries.set_index("M49 Code")["Country or Area"].to_dict()
COUNTRY_CODES[412] = "Kosovo"  # per UNSD guidance

COUNTRY_CODES_REV_LC = {name.casefold(): code for code, name in COUNTRY_CODES.items()} # lowercase, reversed so country names are keys instead of m49

def normalize_country(text: str | None) -> tuple[str, int | None]:
    """Return (country name, M49 code) for a cleaned location string.

    Exact match first, fuzzy fallback second. Remote / multiple-location
    listings get the sentinel codes -1 / -2.
    """
    if not text:
        return UNIDENTIFIED
    country = text.rsplit(",", 1)[-1].strip()

    if re.match(r"Remote", country, re.IGNORECASE):
        return REMOTE
    if re.match(r"Multiple", country, re.IGNORECASE):
        return MULTIPLE

    code = COUNTRY_CODES_REV_LC.get(country.casefold())
    if code is not None:
        return COUNTRY_CODES[code], code

    # high cutoff to ensure a match is truly a match (should be between high cutoff and the pre-processing of country names)
    try_match = process.extractOne(
        country,
        COUNTRY_CODES,
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=90,
    )
    if try_match is None:
        print(f"Unidentified country: {country} (from {text})")
        return UNIDENTIFIED
    name, _, code = try_match
    return name, code
