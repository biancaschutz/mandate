"""Derived listing fields: cleaned qualifications, years of experience, career stage, education.

Either is run with combiner automatically to ensure listings put into DB are cleaned, OR
can be run with GH workflow
"""

import html

from bs4 import BeautifulSoup
from pymongo import UpdateOne

from db import get_client, get_collection
from education import get_education
from experience import MAX_YRS, career_stage, extract_years
from helpers import INTERN, pick_value

CLEANING_VERSION = 5 
BATCH_SIZE = 500
PROJECTION = {"qualifications": 1, "job_level": 1, "job_type": 1, "title": 1}

def decode_html(text: str) -> str:
    """Unescape repeatedly to undo double-encoding, one html.unescape per pass."""
    while "&" in text:
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def remove_style(text: str) -> str:
    """Remove styling

    Qualifications are sometimes formatted HTML with in-line CSS styling
    Resulting in non-Mandate styling when shown on the website, this fixes that
    """
    if "style" not in text.lower():
        return text
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup("style"):
        tag.decompose()
    for el in soup.find_all(style=True):
        del el["style"]
    return str(soup)


def clean_qualifications(text: str) -> str:
    return remove_style(decode_html(text))


def looks_like_internship(job_type, title=None) -> bool:
    """Matches "Internship" and "Internship/Volunteer", but not "internal"."""
    return bool(INTERN.search(job_type or "") or INTERN.search(title or ""))


def parse_qualifications(doc: dict) -> dict:
    """Parsing qualifications, job_level and other fields for more detailed analysis

    """
    out = {}
    raw = doc.get("qualifications") or ""
    cleaned = clean_qualifications(raw) if raw else ""
    if cleaned != raw:
        out["qualifications"] = cleaned

    years = pick_value([n for n in extract_years(cleaned) if n <= MAX_YRS], "max")
    job_type, title = doc.get("job_type"), doc.get("title")

    out["years_experience"] = years
    out["career_stage"] = career_stage(
        doc.get("job_level"), job_type, cleaned, years, title=title
    )
    out["education"] = get_education(
        cleaned, is_internship=looks_like_internship(job_type, title)
    )
    return out

def process_pending(collection) -> int:
    """Process non-cleaned listings

    Apply parse_qualifications to every listing that hasn't been cleaned yet with current CLEANING_VERSION.
    """
    query = {"cleaning_version": {"$ne": CLEANING_VERSION}}
    ops, processed = [], 0
    for doc in collection.find(query, PROJECTION, batch_size=BATCH_SIZE):
        updates = parse_qualifications(doc)
        updates["cleaning_version"] = CLEANING_VERSION
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": updates}))
        if len(ops) >= BATCH_SIZE:
            collection.bulk_write(ops, ordered=False)
            processed += len(ops)
            ops.clear()
    if ops:
        collection.bulk_write(ops, ordered=False)
        processed += len(ops)
    print(f"Processed {processed} listings")
    return processed


def main():
    try:
        collection = get_collection()
        process_pending(collection)
    finally:
        get_client().close()


if __name__ == "__main__":
    main()