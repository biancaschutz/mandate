# undp scraper
import time
from datetime import datetime, timezone
from urllib.request import urlopen

import pandas as pd
import requests
from bs4 import BeautifulSoup

from combiner import upsert_listings
from location import clean_location, normalize_country

URL = "https://jobs.undp.org/cj_view_jobs.cfm"

ORGANIZATION = "UNDP"

def build_undp_df():
    print("Fetching UNDP list of listings...")
    page = urlopen(URL).read().decode("utf-8")

    soup = BeautifulSoup(page, "html.parser")

    def parse_undp_dates(string):
        if string:

            return datetime.fromisoformat(string)
        else: 
            return datetime.now(tz=timezone.utc)

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

    vacancies = []
    session = requests.Session()

    for s in soup.find_all("div", class_="vacanciesTable"):
        rows = s.find_all("a", class_=lambda x: x and "vacanciesTableLink" in x)
        print(f"In this table, {len(rows)} found. Parsing individual listing information with UNDP API...")
        for r in rows:
            s = r.find_all("div", class_="vacanciesTable__cell")

            row = {"url": r["href"]}
            id = r["href"].rpartition('/')[2]
            JOB_URL = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
            params = f'expand=all&onlyData=true&finder=ById;Id="{id}",siteNumber=CX_1'

            try:
                job_page = session.get(JOB_URL, params = params, headers=HEADERS)


                response = job_page.json().get("items")

                if response:
                    
                    results = response[0]


                    location = clean_location(results.get("PrimaryLocation"))
                    country, m49 = normalize_country(location)


                    flex = results.get("requisitionFlexFields")

                    level = None
                    for f in flex:
                        if f.get("Prompt") == "Grade":
                            level = f.get("Value")


                    row =  {
                                                        "_id": ORGANIZATION + id,
                                                        "requisition_id": id,
                                                        "title": results.get("Title"),
                                                        "job_level": level,
                                                        "location": location,
                                                        "country": country,
                                                        "m49": m49,
                                                        "posted_date": parse_undp_dates(results.get("ExternalPostedStartDate")),
                                                        "closing_date": parse_undp_dates(results.get("ExternalPostedEndDate")),
                                                        "qualifications": results.get("ExternalDescriptionStr") or None,
                                                        "url": r["href"],
                                                    }
                    print(f"Appended {row.get("title")}")
                    vacancies.append(row)
                    time.sleep(1)
            except requests.exceptions.RequestException as e:
                print(f"Error fetching detail for Id={id}: {e}")

    return pd.DataFrame(vacancies)

def main(): 
    df = build_undp_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()