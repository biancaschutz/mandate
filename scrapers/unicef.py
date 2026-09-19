"""UNICEF

This is a messy one, with major parsing for qualifications
"""

import math
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

from combiner import upsert_listings
from location import clean_location, normalize_country

ORGANIZATION = "UNICEF"

HEADER_RE = re.compile(
    r"\b(minimum\s+)?(requirement|qualification)s?\b"
    r"|specialized knowledge"
    r"|connaissances\s+(spécialisées|requises)"
    r"|exigences",
    re.IGNORECASE,
)

STOP_MARKERS = [
    "for every child, you demonstrate",
    "for every child you demonstrate",
    "pour chaque enfant, vous devez démontrer",
    "qualified candidates are invited",
    "les candidat(e)s qualifié(e)s",
]

STOP_HEADINGS = {
    "responsibilities",
    "duties and responsibilities",
    "how to apply",
    "application process",
    "terms of reference",
    "background",
    "purpose of the assignment",
    "administrative issues",
    "payment",
    "deliverables",
    "reporting",
    "selection process",
    "competencies",
    "skills",
}

SKIP_LABELS = {
    "minimum requirements",
    "minimum requirement",
    "minimum qualification",
    "minimum qualifications",
    "minimum qualification required",
    "desirables",
    "desirable",
}


def normalize_text(text):
    return re.sub(
        r"\s+",
        " ",
        text.replace("\xa0", " ")
    ).strip()


def is_qualification_header(text):
    norm = normalize_text(text)
    if len(norm) > 250:
        return False
    if norm.count(".") > 1:
        return False
    return bool(HEADER_RE.search(norm))

def is_stop_heading(text):
    low = normalize_text(text).casefold().rstrip(":")

    return (
        len(low) < 100
        and low in STOP_HEADINGS
    )

DEBUG_MISSES = []


def find_header_split(text):
    """If a qualification header appears inside this block (even mixed
    with other content), return the text starting from the header.
    Otherwise return None."""
    match = HEADER_RE.search(text)
    if not match:
        return None
    tail = text[match.start():]
    if len(tail) < 300 or "/" in text[max(0, match.start()-5):match.start()+80]:
        return tail
    return None


def get_qualifications(job_soup, job_url=None):
    container = job_soup.find("div", id="job-details") or job_soup
    blocks = [child for child in container.children if isinstance(child, Tag)]

    in_section = False
    result = []

    for block in blocks:
        text = normalize_text(block.get_text(" ", strip=True))
        if not text:
            continue
        low = text.casefold()

        if not in_section:
            split = find_header_split(text)
            if split:
                in_section = True
                after_header_idx = text.casefold().find(
                    HEADER_RE.search(text).group(0).casefold()
                ) + len(HEADER_RE.search(text).group(0))
                rest = text[after_header_idx:].strip(" /:-")
                if rest and len(rest) > 20:
                    result.append(f"<p>{rest}</p>")
            continue

        if any(marker in low for marker in STOP_MARKERS):
            break
        if is_stop_heading(text):
            break
        if low.rstrip(":").strip() in SKIP_LABELS:
            continue

        result.append(str(block))

    if not result:
        if job_url:
            DEBUG_MISSES.append({
                "url": job_url,
                "raw_text": normalize_text(container.get_text(" ", strip=True)),
            })
        return None

    fragment = "\n".join(result)
    clean_soup = BeautifulSoup(fragment, "html.parser")
    return clean_soup.decode_contents().strip()

DELAY = 0.3

def build_unicef_df():

    response = requests.post("https://jobs.unicef.org/en-us/filter/?search-keyword=&pay-scale=consultancy&pay-scale=internship&pay-scale=p-2" + "&ts=" + str(int(time.time() * 1000)))

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    num_jobs = int(soup.find("span", {"class": "count"}).text) + 20

    results = soup.find("div", {"id": "search-results-content"})

    n_pages = math.ceil(num_jobs/20)

    jobs = {}
    for pg in range(1, n_pages + 1):
        pg_url = f"&page={pg}&page-items=20"
        url = "https://jobs.unicef.org/en-us/filter/?search-keyword=&pay-scale=consultancy&pay-scale=internship&pay-scale=p-2" + pg_url + "&ts=" + str(int(time.time() * 1000))
        response = requests.post(url)
        soup = BeautifulSoup(response.text, "html.parser")
        results = soup.find("div", {"id": "search-results-content"})
        for item in results.find_all("div", {"class": "list-view--item"}):
            link = item.find("a", {"class": "job-link"})
            name = link.text
            closing_span = item.find("span", {"class": "close-date"})
            closing_date = closing_span.find("time")['datetime']
            try:
                job_url = "https://jobs.unicef.org/" + link['href']
                job_soup = BeautifulSoup(requests.post(job_url).text, "html.parser")
                req_id = job_soup.find("span", {"class": "job-externalJobNo"}).text
                span = job_soup.find("span", class_="work-type")
                job_type = span.text if span else None
                duty_station = job_soup.find("b", string=lambda s: s and "Duty Station" in s)
                location = job_soup.find("span", class_="location")

                qualifications = get_qualifications(job_soup, job_url=job_url)

                if duty_station and location:
                    loc = f"{duty_station.next_sibling.strip()}, {location.text.strip()}"
                elif duty_station and not location:
                    loc = duty_station.next_sibling.strip()
                elif location and not duty_station:
                    loc = location.text.strip()
                else:
                    loc = None

                opening_span = job_soup.find("span", class_="open-date")

                opening_date= opening_span.find("time")['datetime']

                loc_cleaned = clean_location(loc)

                country = normalize_country(loc_cleaned)
                country_name = country[0]
                country_code = country[1]

                job = {"title": name, "url": job_url, "job_type": job_type, 
                    "location": loc_cleaned, "country": country_name, "m49": country_code, "closing_date": closing_date, "posted_date": opening_date, 
                    "qualifications": qualifications if qualifications else "See listing.", "requisition_id": req_id}
                jobs[ORGANIZATION + req_id] = job
            except Exception as e:
                print(f"Failed on {job_url}: {e}")
            time.sleep(DELAY)
    df = pd.DataFrame.from_dict(jobs, orient="index")
    
    if df.empty:
            return df

    for col in ("posted_date", "closing_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                
    df = df.where(pd.notnull(df), None)
    print("Fetched UNICEF listings.")
    return df

def main():
    df = build_unicef_df()
    if df.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(df, organization=ORGANIZATION)

if __name__ == "__main__":
    main()