"""World Bank Group Scraping

Has API
"""

import re
from datetime import datetime

import pandas as pd
import requests

from combiner import upsert_listings
from location import clean_location, normalize_country

SITE = "https://worldbankgroup.csod.com"
CAREER_PAGE = f"{SITE}/ux/ats/careersite/1/home?c=worldbankgroup"
API = "https://us.api.csod.com/rec-job-search/external/jobs"
ORGANIZATION = "WBG"
PAGE_SIZE = 25

APPLY_URL = "https://worldbankgroup.csod.com/ux/ats/careersite/1/home/requisition/"
APPLY_URL_END = "?c=worldbankgroup"

countries = pd.read_csv("uncountries.csv")

COUNTRYA2 = countries.set_index('ISO-alpha2 Code')["Country or Area"].to_dict()

def alpha2_to_country(a2):
    country_name = COUNTRYA2.get(a2)
    if country_name:
        return country_name
    return ""


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_token(session):
    html = session.get(CAREER_PAGE, timeout=30).text
    m = re.search(r'"token"\s*:\s*"([^"]+)"', html)
    if not m:
        raise RuntimeError("CSOD token not found in career site HTML")
    return m.group(1)


def fetch_wbg_list():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Referer": SITE + "/",
        "Origin": SITE,
    })
    session.headers["Authorization"] = f"Bearer {get_token(session)}"

    # handle pagination
    jobs, page = [], 1

    while True:
        res = session.post(API, timeout=30, json={
            "careerSiteId": 1, "careerSitePageId": 1,
            "pageNumber": page, "pageSize": PAGE_SIZE,
            "cultureId": 1, "cultureName": "en-US", "searchText": "",
            "states": [], "countryCodes": [], "cities": [], "placeID": "",
            "radius": None, "postingsWithinDays": None,
            "customFieldCheckboxKeys": [], "customFieldDropdowns": [],
            "customFieldRadios": [],
        })
        res.raise_for_status()
        page_res = res.json()["data"]
        page_jobs = page_res.get("requisitions", [])
        jobs.extend(page_jobs)
        if not page_jobs or len(jobs) >= page_res.get("totalCount", 0):
            break
        page += 1
    return jobs

def build_wbg_df():
    jobs = fetch_wbg_list()

    jobs_prepared = []
    for job in jobs:
        id = str(job.get('requisitionId'))
        opening_date = job.get('postingEffectiveDate')
        closing_date = job.get('postingExpirationDate')
        quals = job.get('externalDescription')
        location_dict = job.get("locations")[0]
        micro = location_dict.get("city") or location_dict.get("state")
        if micro:
            location = clean_location(micro + ", " + alpha2_to_country(location_dict.get("country")))
        else: 
            location = clean_location(alpha2_to_country(location_dict.get("country")))
        job_url = APPLY_URL + id + APPLY_URL_END
        country, m49 = normalize_country(location)
        jobs_prepared.append(
                                {
                                    "_id": ORGANIZATION + id,
                                    "requisition_id": id,
                                    "title": job.get("displayJobTitle"),
                                    "job_type": None,
                                    "location": location,
                                    "country": country,
                                    "m49": m49,
                                    "posted_date": opening_date,
                                    "closing_date": closing_date,
                                    "qualifications": quals or None,
                                    "url": job_url,
                                }
                                            )
    return pd.DataFrame(jobs_prepared)

def main(): 
    df = build_wbg_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()