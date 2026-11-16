"""WHO scraper

Has API route (Taleo, same platform as WIPO)
"""

import json
import math
import re
import time
import urllib.parse
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from combiner import upsert_listings
from location import clean_location, normalize_country

ORGANIZATION = "WHO"

BASE = "https://careers.who.int/careersection"
URL = f"{BASE}/rest/jobboard/searchjobs?lang=en&portal=101430233"
DETAIL_URL = f"{BASE}/ex/jobdetail.ftl?job="

# pause between requests
REQUEST_DELAY = 1.0

TALEO_DATE_FORMAT = "%b %d, %Y, %I:%M:%S %p"  # e.g. "Nov 28, 2026, 4:59:00 PM"
TALEO_DATE_RE = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2} [AP]M$")

PAYLOAD = json.loads(
    '{"multilineEnabled":true,"sortingSelection":{"sortBySelectionParam":"3","ascendingSortingOrder":"false"},"fieldData":{"fields":{"KEYWORD":"","LOCATION":""},"valid":true},"filterSelectionParam":{"searchFilterSelections":[{"id":"POSTING_DATE","selectedValues":[]},{"id":"LOCATION","selectedValues":[]},{"id":"JOB_FIELD","selectedValues":[]},{"id":"JOB_TYPE","selectedValues":[]},{"id":"JOB_SCHEDULE","selectedValues":[]},{"id":"JOB_LEVEL","selectedValues":[]},{"id":"EMPLOYEE_STATUS","selectedValues":[]}]},"advancedSearchFiltersSelectionParam":{"searchFilterSelections":[{"id":"ORGANIZATION","selectedValues":[]},{"id":"LOCATION","selectedValues":[]},{"id":"JOB_FIELD","selectedValues":[]},{"id":"JOB_NUMBER","selectedValues":[]},{"id":"URGENT_JOB","selectedValues":[]},{"id":"EMPLOYEE_STATUS","selectedValues":[]},{"id":"JOB_SCHEDULE","selectedValues":[]},{"id":"JOB_TYPE","selectedValues":[]},{"id":"JOB_LEVEL","selectedValues":[]}]},"pageNo":1}'
)


def parse_date(value):
    try:
        return datetime.strptime(value, TALEO_DATE_FORMAT)
    except (TypeError, ValueError):
        return None


def uninvert_country(name):
    """Turn ISO-style inverted names into natural order, since clean_location
    splits on commas ("Korea, Republic of" would otherwise become "Korea"
    and match North Korea).

    "Korea, Republic of" -> "Republic of Korea"
    "Congo, The Democratic Republic of the" -> "Democratic Republic of the Congo"
    """
    head, sep, tail = name.partition(", ")
    if not sep:
        return name
    tail = re.sub(r"^the\s+", "", tail, flags=re.IGNORECASE)
    return f"{tail} {head}"


def canonical_country(raw):
    """Resolve a WHO country name to the UN name normalize_country returns.

    clean_location strips trailing qualifiers like ", Islamic Republic of Iran",
    so we hand it the canonical name (e.g. "Iran (Islamic Republic of)"),
    which it leaves intact. Falls back to the raw name if nothing matches.
    """
    for candidate in (uninvert_country(raw), raw.partition(", ")[0]):
        name, m49 = normalize_country(candidate)
        if m49 is not None and m49 > 0:
            return name
    return raw


def who_location(locs):
    """WHO sends ["Country-City", ...]; clean_location expects 'City, Country; ...'."""
    out = []
    for loc in locs:
        # rpartition so "Congo, The Democratic Republic of the-Goma" splits correctly
        # (hyphenated countries like Guinea-Bissau with no city will split wrongly)
        country, sep, city = loc.rpartition("-")
        if not sep:
            country, city = loc, ""
        country = canonical_country(country)
        out.append(f"{city}, {country}" if city else country)
    return clean_location("; ".join(out))


def fetch_details(session, url):
    """Return (posted_date, qualifications) from a job detail page.

    The description div is rendered client-side; the content lives in the
    hidden initialHistory input as '!|!'-separated fields, the description
    being the longest one prefixed with '!*!'. Colons are escaped as '\\:'.
    """
    res = session.get(url, timeout=30)
    res.raise_for_status()

    if (
        'name="descRequisition.hasElements" id="descRequisition.hasElements" value="false"'
        in res.text
    ):
        print(f"Empty result for {url} — session likely not bootstrapped correctly")
        return None, "See listing."

    hidden = BeautifulSoup(res.text, "html.parser").find(
        "input", {"id": "initialHistory"}
    )
    if hidden is None or not hidden.get("value"):
        print(f"No initialHistory field for {url}")
        return None, "See listing."

    fields = [
        f.replace("\\:", ":")
        for f in urllib.parse.unquote(hidden["value"]).split("!|!")
    ]

    # first Taleo-formatted date on the page is the posting date
    posted_date = next((parse_date(f) for f in fields if TALEO_DATE_RE.match(f)), None)

    desc_fields = [f for f in fields if f.startswith("!*!")]
    if not desc_fields:
        return posted_date, "See listing."
    desc_html = max(desc_fields, key=len)[len("!*!") :]
    qualifications = BeautifulSoup(desc_html, "html.parser").get_text("\n", strip=True)

    return posted_date, qualifications or "See listing."


def parse_who_rows(session, jobs):
    rows = []
    for job in jobs:
        c = job["column"]
        req_id = job["contestNo"]
        url = DETAIL_URL + req_id

        location = who_location(json.loads(c[2]) if c[2] else [])
        country, m49 = normalize_country(location)

        try:
            posted_date, qualifications = fetch_details(session, url)
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to {url}: {e}")
            posted_date, qualifications = None, "See listing."
        time.sleep(REQUEST_DELAY)

        rows.append(
            {
                "_id": ORGANIZATION + req_id,
                "requisition_id": req_id,
                "title": c[0].strip() or None,
                "job_type": c[4] or None,
                "job_level": c[3] if c[3] and c[3] != "No grade" else None,
                "location": location or None,
                "country": country,
                "m49": m49,
                "posted_date": posted_date,
                "closing_date": parse_date(c[5]),
                "qualifications": qualifications,
                "url": url,
            }
        )
    return rows


def fetch_page(session, page_no):
    payload = {**PAYLOAD, "pageNo": page_no}
    res = session.post(URL, json=payload, timeout=30)
    res.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return res.json()


def build_who_df(session):
    # session cookies on the search page
    session.get(f"{BASE}/ex/jobsearch.ftl", timeout=30).raise_for_status()

    data = fetch_page(session, 1)
    paging = data.get("pagingData", {})
    pages = math.ceil(paging.get("totalCount", 0) / max(paging.get("pageSize", 1), 1))
    print(f"WHO: {paging.get('totalCount')} listings across {pages} pages")

    jobs = list(data.get("requisitionList", []))
    for pg in range(2, pages + 1):
        jobs.extend(fetch_page(session, pg).get("requisitionList", []))

    return pd.DataFrame(parse_who_rows(session, jobs))


def make_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=None,  # retry POST too (the job search is a POST)
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "tz": "GMT-06:00",
            "tzname": "America/Chicago",
            "Origin": "https://careers.who.int",
            "Referer": f"{BASE}/ex/jobsearch.ftl",
        }
    )
    return session


def main():
    session = make_session()
    df = build_who_df(session)
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()
