# iom.py — IOM SCRAPER
import time

import pandas as pd
import requests

from combiner import upsert_listings
from location import clean_location, normalize_country

DELAY = 0.3
ORGANIZATION = "IOM"  # International Organization for Migration

IOM_LIST_URL = "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
IOM_DETAIL_URL = "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
BASE_URL = "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/"

INTERESTED_IN = [
    "Title",
    "RequisitionType",
    "PrimaryLocation",
    "ExternalPostedStartDate",
    "ExternalPostedEndDate",
    "ExternalQualificationsStr",
]

COLUMN_MAP = {
    "Title": "title",
    "RequisitionType": "job_type",
    "PrimaryLocation": "location",
    "ExternalPostedStartDate": "posted_date",
    "ExternalPostedEndDate": "closing_date",
    "ExternalQualificationsStr": "qualifications",
    "local_id": "requisition_id",
}


def fetch_iom_list(limit=50):
    """Fetch all job summaries from the IOM list API, paginating as needed."""
    all_reqs = []
    offset = 0
    total = None
    session = requests.Session()

    while total is None or offset < total:
        params = {
            "onlyData": "true",
            "expand": "requisitionList.workLocation,requisitionList.otherWorkLocations,"
            "requisitionList.secondaryLocations,flexFieldsFacet.values,"
            "requisitionList.requisitionFlexFields",
            "finder": (
                f"findReqs;siteNumber=CX_1001,"
                "facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
                "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,"
                f"limit={limit},offset={offset},"
                "sortBy=POSTING_DATES_DESC"
            ),
        }

        try:
            response = session.get(IOM_LIST_URL, params=params, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to list API: {e}")
            break

        data = response.json()
        items = data.get("items")
        if not items:
            break
        item_block = items[0]

        total = item_block.get("TotalJobsCount", 0)
        reqs = item_block.get("requisitionList", [])
        all_reqs.extend(reqs)

        if not reqs:
            break
        offset += limit
        time.sleep(DELAY)

    print(f"Fetched list of {total} listings. Getting details...")
    return all_reqs


def fetch_iom_details(req_id, session=None):
    """Fetch the full detail record for a single job Id."""
    session = session or requests
    params = {
        "expand": "all",
        "onlyData": "true",
        "finder": f'ById;Id="{req_id}",siteNumber=CX_1001',
    }
    try:
        response = session.get(IOM_DETAIL_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if items:
            return items[0]
        print(f"No detail returned for Id={req_id}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching detail for Id={req_id}: {e}")
        return None


def build_iom_df():
    """Build a DataFrame of IOM listings"""
    print("Fetching IOM listings...")

    results = fetch_iom_list()

    session = requests.Session()
    res = {}
    for lstng in results:
        req_id = lstng["Id"]
        unique_id = "IOM" + req_id
        details = fetch_iom_details(req_id, session=session)
        if details is None:
            continue
        df_fields = {k: details.get(k) for k in INTERESTED_IN}
        df_fields["url"] = BASE_URL + req_id
        df_fields["local_id"] = req_id
        df_fields["ExternalQualificationsStr"] = df_fields["ExternalQualificationsStr"]
        df_fields["PrimaryLocation"] = clean_location(df_fields["PrimaryLocation"])
        country = normalize_country(df_fields["PrimaryLocation"])
        df_fields["country"] = country[0]
        df_fields["m49"] = country[1]
        res[unique_id] = df_fields

        time.sleep(DELAY)

    df = pd.DataFrame.from_dict(res, orient="index")

    if df.empty:
        return df

    df = df.rename(columns=COLUMN_MAP)

    print("Fetched IOM listings.")
    return df


def main():
    df = build_iom_df()
    if df.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()
