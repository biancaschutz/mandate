"""WTO Scraping

Has API
"""

import time
from datetime import datetime

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from combiner import upsert_listings
from location import clean_location, normalize_country

BASE = "https://wto.wd103.myworkdayjobs.com"

ORGANIZATION = "WTO"

DETAIL_BASE = "https://wto.wd103.myworkdayjobs.com/wday/cxs/wto/External"
SITE = "External"

# Workday rate-limits aggressively (esp. shared CI IPs); pause between requests
REQUEST_DELAY = 1.0

def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None

def build_wto_df(session):
    # no cookie warm-up needed: the CXS API answers a bare POST, and hitting the
    # HTML front end first just adds another request for bot protection to see

    url = f"{BASE}/wday/cxs/wto/{SITE}/jobs"
    # handle pagination
    jobs, offset = [], 0

    while True:
        res = session.post(url, json={
            "appliedFacets": {},
            "limit": 20,      
            "offset": offset,
            "searchText": "",
        })
        res.raise_for_status()
        data = res.json()
        time.sleep(REQUEST_DELAY)

        postings = data.get("jobPostings", [])
        if not postings:
            break
        jobs.extend(postings)
        offset += 20
        if offset >= data.get("total", 0):
            break

    rows = []
    for job in jobs:
        title = job['title']
        extension = job.get('externalPath')
        if extension:
            path = DETAIL_BASE + job.get('externalPath')
            res = session.get(path)
            res.raise_for_status()
            time.sleep(REQUEST_DELAY)
            job_details = res.json()['jobPostingInfo']
            id = job_details['jobReqId']

            posting_date = job_details['startDate'] # this is an assumption - need to go back and verify
            closing_date = job_details['endDate']

            location = clean_location(job_details.get('jobRequisitionLocation').get('country').get('descriptor'))
            country, m49 = normalize_country(location)

            qualifications = job_details.get('jobDescription')

            apply_url = job_details.get('externalUrl')

            rows.append(
                            {
                                "_id": ORGANIZATION + id,
                                "requisition_id": id,
                                "title": title or None,
                                "job_type": None,
                                "location": location or None,
                                "country": country,
                                "m49": m49,
                                "posted_date": parse_date(posting_date),
                                "closing_date": parse_date(closing_date),
                                "qualifications": qualifications,
                                "url": apply_url or url,
                            }
                        )
        else:
            print(f"Details not available for {title}")
            # Workday listings usually carry the req ID as the first bullet field
            bullets = job.get('bulletFields') or []
            id = bullets[0] if bullets else title
            rows.append(
                                        {
                                            "_id": ORGANIZATION + id,
                                            "requisition_id": id,
                                            "title": title or None,
                                            "job_type": None,
                                            "location": None,
                                            "country": None,
                                            "m49": None,
                                            "posted_date": None,
                                            "closing_date": None,
                                            "qualifications": "See listing.",
                                            "url": url,
                                        }
                                    )
    return pd.DataFrame(rows)

def make_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,  # 2, 4, 8s -- a persistent 429 is an IP block, fail fast
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=None,  # retry POST too (the jobs search is a POST)
        respect_retry_after_header=True,
        raise_on_status=False,  # let raise_for_status() report the final status
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

def main():
    session = make_session()
    session.headers.update({
        # same UA as wfp.py, which Workday accepts from GitHub runners
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Referer": f"{BASE}/en-US/{SITE}/jobs",
        "Origin": BASE,
    })
    df = build_wto_df(session)
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()