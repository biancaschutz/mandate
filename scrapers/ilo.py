"""Scrape ILO listings

ILO has an API
"""

import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

from combiner import existing_ids, upsert_listings
from location import clean_location, normalize_country

ORGANIZATION = "ILO"
DELAY = 0.3

ILO_LIST_URL = "https://jobs.ilo.org/services/recruiting/v1/jobs"
ILO_JOBS_PAGE = "https://jobs.ilo.org/go/All-Jobs/2842101/"

SECTIONS = {"Education", "Experience", "Languages", "Competencies"}

PAYLOAD = {
    "locale": "en_GB",
    "pageNumber": 0,
    "sortBy": "",
    "keywords": "",
    "location": "",
    "brand": "",
    "skills": [],
    "alertId": "",
    "categoryId": 2842101,
    "rcmCandidateId": "",
}


def create_session() -> requests.Session:
    """Session with the cookies the jobs API expects (visit the jobs page first)."""
    session = requests.Session()
    resp = session.get(ILO_JOBS_PAGE, timeout=30)
    resp.raise_for_status()
    return session


def first(values):
    return (values or [None])[0] or None


def parse_date(value):
    try:
        return datetime.strptime(value, "%d/%m/%Y")
    except (TypeError, ValueError):
        return None


def fetch_qualifications(session: requests.Session, url: str) -> str | None:
    """HTML of the Education / Experience / Languages / Competencies sections.

    Returns None if the page loads but has no such sections. Raises if the
    request fails or the page doesn't look like a job page.
    """
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    content = BeautifulSoup(resp.text, "html.parser").find("div", class_="job")
    if content is None:
        raise ValueError("no div.job on page")

    parts = []
    for h2 in content.find_all("h2"):
        heading = h2.get_text(strip=True)
        if heading in SECTIONS or "competencies" in heading.lower():
            parts.append(str(h2))
            if sibling := h2.parent.find_next_sibling():
                parts.append(str(sibling))
    return "".join(parts) or None


def build_ilo_df() -> pd.DataFrame:
    print("Fetching ILO listings...")
    session = create_session()
    have = existing_ids(ORGANIZATION)

    response = session.post(ILO_LIST_URL, json=PAYLOAD, timeout=30)
    response.raise_for_status()
    results = response.json()["jobSearchResult"]
    print(f"List returned {len(results)} jobs")

    rows = []
    for job in results:
        basics = job["response"]
        job_id = basics["id"]
        _id = ORGANIZATION + job_id
        url = f"https://jobs.ilo.org/job/{basics['urlTitle']}/{job_id}-en_GB"

        # parse only ids that we don't already have
        qualifications = None
        if _id not in have:
            try:
                qualifications = fetch_qualifications(session, url)
            except (requests.RequestException, ValueError) as e:
                print(f"Skipping new listing {job_id}: {e}")
                continue  # retry next run, don't store it
            time.sleep(DELAY)

        loc = clean_location(first(basics.get("jobLocationShort")))
        country, m49 = normalize_country(loc)

        rows.append(
            {
                "_id": _id,
                "requisition_id": job_id,
                "title": basics.get("unifiedStandardTitle") or None,
                "job_type": first(basics.get("filter4")),
                "location": loc or None,
                "country": country,
                "m49": m49,
                "posted_date": parse_date(basics.get("unifiedStandardStart")),
                "closing_date": parse_date(basics.get("unifiedStandardEnd")),
                "qualifications": qualifications,
                "url": url,
            }
        )

    return pd.DataFrame(rows)


def main():
    df = build_ilo_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()
