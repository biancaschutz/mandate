"""UNESCO scraper

Has no API
"""
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from location import clean_location, normalize_country
from combiner import upsert_listings

ORGANIZATION = "UNESCO"

URL = "https://careers.unesco.org/go/All-jobs-openings/784002/"

def build_unesco_df():

    page = urlopen(URL).read().decode("utf-8")

    soup = BeautifulSoup(page, "html.parser")

    numPages = int(list(soup.find("span", class_="paginationLabel").children)[-1].getText(strip=True))

    results = []


    for pg in range(numPages // 25 + 1):
        if pg > 0:

            startingNum = 25 * pg
            pg_url = f"https://careers.unesco.org/go/All-jobs-openings/784002/{startingNum}/?q=&sortColumn=referencedate&sortDirection=desc"
        else: 
            pg_url = "https://careers.unesco.org/go/All-jobs-openings/784002/?q=&sortColumn=referencedate&sortDirection=desc"


        page_results = urlopen(pg_url).read().decode("utf-8")

        page_soup = BeautifulSoup(page_results, "html.parser")

        rows = page_soup.find_all("tr", class_="data-row")

        for r in rows:

            title_span = r.find("a", class_="jobTitle-link")

            job_url = f"https://careers.unesco.org{title_span['href']}"

            id = title_span['href'].split("/")[-2]

            title = title_span.getText(strip=True)

            location = clean_location(r.find("span", class_="jobLocation").getText(strip=True))

            country, m49 = normalize_country(location)

            type = r.find("span", class_="jobFacility").getText(strip=True)

            level = r.find("span", class_="jobDepartment").getText(strip=True).replace("-", "").replace("  ", " ")

            quals = str(BeautifulSoup(urlopen(job_url).read().decode("utf-8"), "html.parser").find("span", class_="jobdescription"))

            results.append({"_id": ORGANIZATION + id, "organization": ORGANIZATION, "title": title, "url": job_url, 
                            "requisition_id": id, "location": location, "country": country, "m49": m49, "job_level": level,
                            "job_type": type, "qualifications": quals})


    return pd.DataFrame(results)

def main(): 
    df = build_unesco_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()