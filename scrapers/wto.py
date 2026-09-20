"""WTO Scraping

Has API
"""

from datetime import datetime

import pandas as pd
import requests

from combiner import upsert_listings
from location import clean_location, normalize_country

BASE = "https://wto.wd103.myworkdayjobs.com"

ORGANIZATION = "WTO"

DETAIL_BASE = "https://wto.wd103.myworkdayjobs.com/wday/cxs/wto/External"
SITE = "External"

def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%d-%m")
    except (TypeError, ValueError):
        return None

def build_wto_df(session):
    # cookies first
    session.get(f"{BASE}/en-US/{SITE}/jobs")

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

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Referer": f"{BASE}/en-US/{SITE}/jobs",
        "Origin": BASE,
    })
    df = build_wto_df(session)
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()