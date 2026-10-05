"""WFP scraper

Has workday API
"""
import re
import time
from datetime import datetime

import pandas as pd
import requests

from combiner import upsert_listings
from location import clean_location, normalize_country

ORGANIZATION = "WFP"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US",
    "Referer": "https://wd3.myworkdaysite.com/recruiting/wfp/job_openings",
    "Origin": "https://wd3.myworkdaysite.com",
})

URL = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings/jobs"
EXTERNAL_BASE = "https://wd3.myworkdaysite.com/en-US/recruiting/wfp/job_openings"

DETAIL_BASE = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings"
payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

MULTIPLE_LOCS = re.compile(r"\d+ Locations")

def build_wfp_df():

    resp = session.post(URL, json=payload)

    if resp:

        total = resp.json()['total']

        offset = 0

        pages = total // 20

        results = []
        for _ in range(pages + 1):
            page_payload = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}
            offset += 20
            page_resp  = session.post(URL, json=page_payload)
            jobs = page_resp.json()['jobPostings']

            for job in jobs:
                job_res = {"_id": None, "title": job.get('title'), "url": EXTERNAL_BASE + job.get('externalPath'), "location": None, "country": None, "m49": None, 
                            "job_level": None, "organization": ORGANIZATION, "requisition_id": None, "qualifications": None, "closing_date": None, "posted_date": None}

                location = job["locationsText"]
                if MULTIPLE_LOCS.search(location):
                    location = "Multiple"

                c_loc = clean_location(location)
                
                job_res['location'] = c_loc

                job_res["country"], job_res["m49"] = normalize_country(c_loc)

                api_url = DETAIL_BASE + job.get('externalPath')

                try: 
                    details = session.get(api_url).json().get('jobPostingInfo')

                    job_res['posted_date'] = datetime.strptime(details.get('startDate'), "%Y-%m-%d")
                    job_res['closing_date'] = datetime.strptime(details.get('endDate'), "%Y-%m-%d")

                    job_res["_id"] = ORGANIZATION + details.get("jobReqId")
                    job_res["requisition_id"] = details.get("jobReqId")

                    job_res["qualifications"] = details.get("jobDescription") or "See listing."
                except requests.exceptions.RequestException as e:
                    print(f"Error connecting to API: {e}")
                    break
                results.append(job_res)

                time.sleep(.5)

    return pd.DataFrame(results)


def main(): 
    df = build_wfp_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()