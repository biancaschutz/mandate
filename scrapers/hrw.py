"""Scrape Human Rights Watch

Human Rights Watch uses an API, which makes parsing pretty simple (outside of post-processing done in parse_qualifications)
"""

import re

import pandas as pd
import requests
from dateutil import parser

from combiner import upsert_listings
from helpers import strip_html
from location import clean_location, normalize_country

DEADLINE = re.compile(
    r"Application\s+(?:Deadline|Date)\s*:?\s*"
    r"((?:\d{1,2}(?:st|nd|rd|th)?\s+\w+|\w+\s+\d{1,2}(?:st|nd|rd|th)?),?\s+\d{4})",
    re.IGNORECASE,
)

DELAY = 0.3
ORGANIZATION = "HRW"

HRW_URL = (
    "https://boards-api.greenhouse.io/v1/boards/humanrightswatch/jobs?content=true"
)

session = requests.Session()


def parse_deadline(content: str | None):
    match = DEADLINE.search(strip_html(content))
    if not match:
        return None
    try:
        return parser.parse(match.group(1))
    except (ValueError, OverflowError):
        return None


def get_job_level(job: dict):
    for field in job.get("metadata") or []:
        if field.get("name") == "Job Level":
            return field.get("value")
    return None


def fetch_hrw_listings():
    print("Fetching HRW listings...")
    try:
        response = session.get(HRW_URL, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to list API: {e}")

    return response.json()["jobs"]


def build_hrw_df():
    print("Fetching HRW listings...")

    jobs = fetch_hrw_listings()

    if jobs is None:
        return pd.DataFrame()

    res = {}
    for job in jobs:
        unique_id = "HRW" + job["requisition_id"]
        content = job["content"]

        app_closes = parse_deadline(content)

        loc = clean_location(job["location"]["name"])

        name, code = normalize_country(loc)

        job_res = {
            "title": job["title"],
            "job_type": get_job_level(job),
            "location": loc,
            "country": name,
            "m49": code,
            "posted_date": job["first_published"],
            "closing_date": app_closes,
            "qualifications": content,
            "requisition_id": job["requisition_id"],
            "url": job["absolute_url"],
            "organization": ORGANIZATION,
        }

        res[unique_id] = job_res

    df = pd.DataFrame.from_dict(res, orient="index")

    if df.empty:
        return df

    for col in ("posted_date", "closing_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    df = df.where(pd.notnull(df), None)
    print("Fetched HRW listings.")
    return df


def main():
    df = build_hrw_df()
    if df.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()
