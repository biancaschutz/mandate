"""Scrape UN Women listings

UN Women uses an API with pagination required
"""

import time

import pandas as pd
import requests

from combiner import upsert_listings
from location import clean_location, normalize_country

DELAY = 0.3
ORGANIZATION = "UNWOMEN"

UNW_LIST_URL = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_URL = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id=%22"
DETAIL_URL2 = "%22,siteNumber=CX_1001"
BASE_URL = "https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/"

INTERESTED_IN = [
    "Title",
    "ExternalPostedStartDate",
    "ExternalPostedEndDate",
    "PrimaryLocation",
    "RequisitionType",
    "ExternalDescriptionStr",
]

COLUMN_MAP = {
    "Title": "title",
    "RequisitionType": "job_type",
    "PrimaryLocation": "location",
    "ExternalPostedStartDate": "posted_date",
    "ExternalPostedEndDate": "closing_date",
    "ExternalDescriptionStr": "qualifications",
}


def fetch_unwomen_list(limit=50):
    """Fetch all requisition summaries from the UNWomen list API, paginating as needed."""
    all_reqs = []
    offset = 0
    total = None
    session = requests.Session()

    while total is None or offset < total:
        params = {
            "onlyData": "true",
            "expand": "requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields",
            "finder": (
                f"findReqs;siteNumber=CX_1001,"
                "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS"
                "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,"
                f"limit={limit},offset={offset},"
                "sortBy=POSTING_DATES_DESC"
            ),
        }

        try:
            response = session.get(UNW_LIST_URL, params=params, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to list API: {e}")
            break

        data = response.json()
        items = data.get("items")
        if not items:
            break
        item_block = items[0]

        total = item_block.get("TotalJobsCount", 0)  # get total number of jobs
        reqs = item_block.get("requisitionList", [])
        all_reqs.extend(reqs)

        if not reqs:
            break
        offset += limit
        time.sleep(DELAY)

    if len(all_reqs) > 0:
        print(f"Fetched list of {total} jobs. Getting details...")
    return all_reqs


def fetch_unwomen_details(req_id, session=None):
    """Fetch the full detail record for a single requisition Id."""
    session = session or requests
    params = {
        "expand": "all",
        "onlyData": "true",
        "finder": f'ById;Id="{req_id}",siteNumber=CX_1001',
    }
    try:
        response = session.get(
            DETAIL_URL + req_id + DETAIL_URL2, params=params, timeout=30
        )
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


def build_unwomen_df():
    print("Fetching UNWOMEN listings...")

    results = fetch_unwomen_list()

    session = requests.Session()
    res = {}
    for lstng in results:
        req_id = lstng["Id"]
        unique_id = "UNWOMEN" + req_id
        details = fetch_unwomen_details(req_id, session=session)
        if details is None:
            continue
        df_fields = {k: details.get(k) for k in INTERESTED_IN}
        df_fields["url"] = BASE_URL + req_id
        df_fields["PrimaryLocation"] = clean_location(df_fields["PrimaryLocation"])
        country = normalize_country(df_fields["PrimaryLocation"])
        df_fields["country"] = country[0]
        df_fields["m49"] = country[1]

        res[unique_id] = df_fields
        time.sleep(DELAY)

    print("Got details. Formatting as dataframe to upsert.")

    df = pd.DataFrame.from_dict(res, orient="index")

    if df.empty:
        return df

    df = df.rename(columns=COLUMN_MAP)

    print("Fetched UNWOMEN listings.")
    return df


def main():
    df = build_unwomen_df()
    if df.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()
