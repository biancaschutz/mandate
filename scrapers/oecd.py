"""OECD scraper

Has no API
"""
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo
import re

import pandas as pd
from bs4 import BeautifulSoup

from location import clean_location, normalize_country
from combiner import upsert_listings

ORGANIZATION = "OECD"

URL = "https://careers.smartrecruiters.com/OECD/oecd---en"

DATE = re.compile(r'(\d{1}|[12]{1}\d|30|31) [a-zA-Z]* \d{4}')

def build_oecd_df():

    page = urlopen(URL).read().decode("utf-8")

    soup = BeautifulSoup(page, "html.parser")

    jobs = soup.find_all("li", class_ = lambda c: c and "opening-job job column" in c)

    results = []

    for j in jobs:
        job_url = j.find("a", class_ = "link--block details js-job-ad-link")['href']

        title = j.find("h4", class_ = lambda c: c and "details-title job-title link--block-target" in c).getText(strip=True)

        id = job_url.split("/")[4].split("-")[0]

        job_desc = j.find("p", class_ = "details-desc job-desc")

        if job_desc:
            location = clean_location(job_desc.find("span").getText(strip=True))
            country, m49 = normalize_country(location)

        else: 
            location = None

        job_details = urlopen(job_url).read().decode("utf-8")

        job_soup = BeautifulSoup(job_details, "html.parser")

        quals = None


        if job_soup.find("section", id="st-qualifications"):
            quals = str(job_soup.find("section", id="st-qualifications"))
        else: 
            meta_desc = job_soup.find("meta", property="og:description")

            if meta_desc:
                
                quals = meta_desc["content"]

        if not quals:
            quals = "See listing."

        meta_posted = job_soup.find("meta", itemprop ="datePosted")

        if meta_posted:
            posted_date = meta_posted['content']
        else: 
            posted_date = None

        meta_closing = job_soup.find("meta", itemprop="validThrough")

        if meta_closing:
            closing_date = meta_closing['content']
        else: 
            closing_date = None
            for strong in job_soup.find_all("strong"):
                if "closing date" in strong.getText(strip=True).lower():
                    sibling = strong.parent.next_sibling
                    date = DATE.search(sibling.getText(strip=True))
                    if date:
                        closing_date = datetime.strptime(date.group(), "%d %B %Y").astimezone()


        detail_header = job_soup.find("ul", class_ = "job-details spl-list-none")
        if detail_header:
            for c in detail_header.children:
                if "grade" in c.getText(strip=True).lower():
                    level = c.getText(strip=True).replace("Grade: ", "")
                else:
                    level = None
                if not location and c["itemprop"] == "jobLocation":
                    location = clean_location(c.getText(strip=True))
                    country, m49 = normalize_country(location)

        results.append({"_id": ORGANIZATION + id, "title": title, "url": job_url, "location":location, "country":country or None, "m49":m49 or None, 
                        "job_level": level, "organization": ORGANIZATION, "requisition_id": id, "qualifications": quals, "closing_date": closing_date or None, "posted_date": posted_date or None})
            
    return pd.DataFrame(results)

def main(): 
    df = build_oecd_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()