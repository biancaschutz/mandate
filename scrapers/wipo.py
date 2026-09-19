"""Scrape WIPO listings

There is an API, but some setup required 
"""

import datetime
import re
import time
import urllib

import pandas as pd
import requests
from bs4 import BeautifulSoup

from combiner import upsert_listings
from location import clean_location, normalize_country

INTERNSHIP_URL = "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=10105120713"
FELLOWSHIP_URL = "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=42305027338"
P_URL = "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=42105027338"

mapping = {"https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=42305027338": "wp_2_fel", "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=42105027338": "wp_2_pd", "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=10105120713": "wp_internship"}
mapping_type = {"Fellowship": "https://wipo.taleo.net/careersection/wp_2_fel/jobdetail.ftl?job=", "Internship": "https://wipo.taleo.net/careersection/wp_internship/jobdetail.ftl?job="}


DETAIL_URL = "https://wipo.taleo.net/careersection/wp_2_pd/jobdetail.ftl?job="


ORGANIZATION = "WIPO"

locationKey = {"Switzerland-CH-Geneva": "Geneva, Switzerland",
               "Japan-JP-Tokyo": "Tokyo, Japan"}

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "tz": "GMT+02:00",
    "tzname": "Europe/Zurich",
}


def get_heading_number(div):
    """Return the leading number in a heading div's text, or None."""
    m = re.match(r"^(\d+)\.", div.get_text(strip=True))
    return int(m.group(1)) if m else None


def extract_posting_date(job_soup: BeautifulSoup, raw_text: str):
    """
    WIPO's taleo website uses id in HTML typically in the jobdetail page to identify the posting date 
    For example, 
    <span id="requisitionDescriptionInterface.reqPostingDate.row1" class="text" title="">18-Jul-2026, 10:08:47 AM</span>
    """
    span = job_soup.find(
        "span", id=lambda x: x and "requisitionDescriptionInterface.reqPostingDate" in x
    )
    # if it's found, then deal with it
    if span is not None and span.get_text(strip=True):
        return span.get_text(strip=True)

    # if not, fallback to date of scraping (today)
    return datetime.datetime.now().date()


def params(page_no: int) -> dict:
    return {
        "multilineEnabled": True,
        "sortingSelection": {
            "sortBySelectionParam": "2",
            "ascendingSortingOrder": "true"
        },
        "fieldData": {
            "fields": {"KEYWORD": "", "JOB_TITLE": ""},
            "valid": True
        },
        "filterSelectionParam": {
            "searchFilterSelections": [
                {"id": "POSTING_DATE", "selectedValues": []},
                {"id": "LOCATION", "selectedValues": []},
                {"id": "JOB_FIELD", "selectedValues": []}
            ]
        },
        "advancedSearchFiltersSelectionParam": {
            "searchFilterSelections": [
                {"id": "ORGANIZATION", "selectedValues": []},
                {"id": "LOCATION", "selectedValues": []},
                {"id": "JOB_FIELD", "selectedValues": []},
                {"id": "JOB_NUMBER", "selectedValues": []},
                {"id": "URGENT_JOB", "selectedValues": []},
                {"id": "STUDY_LEVEL", "selectedValues": []}
            ]
        },
        "pageNo": page_no
    }

def fetch_wipo_results(url=P_URL, page_size=25, delay=0.3, session=None) -> tuple[list, requests.Session]:
    all_reqs = []
    page_no = 1
    total = None
    if session is None:
        session = requests.Session()

    base = url.split("/rest/")[0]
    portal = url.split("portal=")[-1]
    try:
        session.get(
            f"{base}/wp_2_pd/jobsearch.ftl",
            params={"lang": "en", "portal": portal},
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"Warning: could not pre-load session page: {e}")

    while total is None or len(all_reqs) < total:
        payload = params(page_no)
        request_headers = {
            **HEADERS,
            "Origin": base,
            "Referer": f"{base}/{mapping[url]}/jobsearch.ftl?lang=en&portal={portal}",
        }
        try:
            response = session.post(url, headers=request_headers, json=payload, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to list API: {e}")
            break

        data = response.json()
        reqs = data.get("requisitionList", [])
        if not reqs:
            break

        all_reqs.extend(reqs)

        if total is None:
            total = data.get("totalRecordCount") or data.get("totalCount") or len(reqs)
            print(f"Total records reported: {total}")

        page_no += 1
        time.sleep(delay)

    return all_reqs, session


def build_wipo_df(results=None, session=None, type = None) -> pd.DataFrame:
    print("Fetching IOM listings...")
    if results is None:
        results, session = fetch_wipo_results()
    elif session is None:
        # results were passed in but no session — bootstrap one now
        _, session = fetch_wipo_results()
 
    df = pd.json_normalize(results)
 
    if df.empty:
        return df
 
    # diff Taleo portals return a different number of fields, ex. internships don't have job_type
    SCHEMAS = {
        9: ['title', 'job_level', 'unit', 'requisition_id', 'appt',
            'job_type', 'location', 'intnl', 'closing_date'],
        8: ['title', 'job_level', 'unit', 'requisition_id', 'appt',
            'location', 'intnl', 'closing_date'],
    }
 
    col_lists = df['column'].tolist()
    lengths = {len(c) for c in col_lists}
    unknown_lengths = lengths - SCHEMAS.keys()
    if unknown_lengths:
        raise ValueError(
            f"Unrecognized 'column' width(s) {unknown_lengths} — Taleo returned a "
            f"row shape we don't have a schema for. Inspect a sample row before "
            f"adding a new entry to SCHEMAS."
        )
 
    frames = []
    for length, schema in SCHEMAS.items():
        subset = df[df['column'].apply(len) == length].copy()
        if subset.empty:
            continue
        sub_df = pd.DataFrame(subset['column'].tolist(), columns=schema, index=subset.index)
        if 'job_type' not in sub_df.columns:
            # Internship/fellowship portals don't have this field so fill it
            sub_df['job_type'] = None
        frames.append(sub_df)
 
    df = pd.concat(frames).sort_index()
 
    df = df[df['job_type'] != "Senior Management"]
    df = df[["title", "job_type", "job_level", "location", "closing_date", "requisition_id"]]
    if type:
        df['url'] = mapping_type[type] + df['requisition_id']
    else:
        df['url'] = "https://wipo.taleo.net/careersection/wp_2_pd/jobdetail.ftl?job=" + df['requisition_id']
    df['_id'] = "WIPO" + df['requisition_id']
    df['location'] = [clean_location(loc) for loc in df["location"]]
 
    qualifications = []
    posting_dates = []
    countries = []
    m49 = []
 
    for i in range(0, df.shape[0]):
        r = df['url'].iloc[i]    
        country = normalize_country(df["location"].iloc[i])
        countries.append(country[0])
        m49.append(country[1])
 
        appended_quals = False
        appended_date = False
        appended_edu = False
 
        try:
            response = session.get(r, timeout=30)
            response.raise_for_status()
 
            if 'name="descRequisition.hasElements" id="descRequisition.hasElements" value="false"' in response.text:
                print(f"Empty result for {r} — session likely not bootstrapped correctly")
                qualifications.append(None)
                posting_dates.append(None)
                appended_quals = appended_date = appended_edu = True
                continue
 
            job_soup = BeautifulSoup(response.text, "html.parser")
 
            posting_dates.append(extract_posting_date(job_soup, response.text))
            appended_date = True
 
            hidden = job_soup.find("input", {"id": "initialHistory"})
            if hidden is None or not hidden.get("value"):
                print(f"No initialHistory field for {r}")
                qualifications.append("See listing.")
                appended_quals = appended_edu = True
                continue
 
            raw_value = hidden["value"]
            decoded = urllib.parse.unquote(raw_value)
            fields = decoded.split("!|!")
 
            desc_field = None
            for f in fields:
                if f.startswith("!*!"):
                    desc_field = f.lstrip("!*!")
                    break
            if desc_field is None:
                
                desc_field = max(fields, key=len).lstrip("!*!")
 
            desc_soup = BeautifulSoup(desc_field, "html.parser")
 
            req_div = None
            start_num = None
            for div in desc_soup.find_all("div"):
                if (div.find("strong") and "Requirements" in div.get_text()) or "Main duties:" in div.get_text():
                    req_div = div
                    start_num = get_heading_number(div)
                    break

            if req_div is None:
                quals = []
                for span in desc_soup.find_all("span"):
                    terms = re.compile('|'.join(map(re.escape, ["education", "skills", "languages", "experience"])))
                    if terms.search(span.get_text().lower()):
                        quals.append(str(span))
                        quals.append(str(span.parent.next_sibling))
                        
                if quals:
                    qualifications.append("".join(quals))

                else: 
                    print(f"No Requirements section found for {r}")

                    qualifications.append("See listing.")
                appended_quals = True
                continue
 
            collected = []
            for sibling in req_div.find_next_siblings():
                n = get_heading_number(sibling) if sibling.name == "div" else None
                if n is not None and start_num is not None and n > start_num:
                    break
                collected.append(sibling)
 
            q = "\n".join(
                tag.get_text(separator=" ", strip=True)
                for tag in collected
                if tag.get_text(strip=True)
            )
            qualifications.append(q)
            appended_quals = appended_edu = True
 
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to {r}: {e}")
        except Exception as e:
            print(f"Unexpected error parsing {r}: {e}")
        finally:

            if not appended_quals:
                qualifications.append("See listing.")
            if not appended_date:
                posting_dates.append(None)
 
        time.sleep(0.3)
 
    df['qualifications'] = qualifications
    df["country"] = countries
    df["m49"] = m49
    df["posted_date"] = posting_dates
    if type:
        df["job_type"] = type
        df["job_level"] = type
 
    return df

def main():
    results, session = fetch_wipo_results(P_URL)
    p = build_wipo_df(results, session)
    results, session = fetch_wipo_results(INTERNSHIP_URL)
    i = build_wipo_df(results, session, type = "Internship")
    results, session = fetch_wipo_results(FELLOWSHIP_URL)
    f = build_wipo_df(results, session, type = "Fellowship")
    dfs = [p, i, f]

    res = pd.concat(dfs)
    if res.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(res, organization=ORGANIZATION)

if __name__ == "__main__":
    main()