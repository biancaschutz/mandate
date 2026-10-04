"""UNITAR scraper

Has no API
does not list posted_date - leave blank and posted_date will be marked as date it was picked up by scraper. 
"""
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from combiner import upsert_listings
from location import clean_location, normalize_country

URL = "https://unitar.org/vacancy-announcements"

ORGANIZATION = "UNITAR"

BASE = "https://unitar.org"

YEAR = datetime.now(ZoneInfo("Europe/London")).year

def get_location(title):
    tl = title.lower()
    if "(remote)" in tl:
        return "Remote"
    if "new york" in tl or "ny" in tl:
        return "New York City, United States of America"
    if "hiroshima" in tl or "japan" in tl:
        return "Hiroshima, Japan"
    if "bonn" in tl or "germany" in tl:
        return "Bonn, Germany"
    return "Geneva, Switzerland"

def parse_unitar_date(date):
    return datetime.strptime(date, "%d %B %Y")

def generate_id(title, job_url):
    title_part = "".join([word[0] for word in title.split()[0:2] if word[0] != "-"])

    url_ending = int(job_url.rpartition('/')[2])
    return title_part + "/" + str(YEAR) + "/" + format(url_ending, '03d')


def build_unitar_df():
    vacancies = []

    try:
        page = urlopen(URL).read().decode("utf-8")
        soup = BeautifulSoup(page, "html.parser")

        for v in soup.find_all("li", class_="item-vacancy"):
            job_url = BASE + v.find("a")["href"]
            html = urlopen(job_url).read().decode("utf-8")
            job_soup = BeautifulSoup(html, "html.parser")

            job_id = None

            # some listings have a main section for the name and id
            main = job_soup.find("div", class_="content-data content-data-main")

            if main:
                title = main.find("h2").get_text(strip=True)
                code = job_soup.find("div", class_="content-data--code")
                if code:
                    job_id = code.get_text(strip=True)
            else:
                title_tag = job_soup.find("h2", class_="page-header")
                if not title_tag:
                    crumb = job_soup.find("ol", class_="breadcrumb")
                    title_tag = crumb.find("li", class_="active") if crumb else None
                title = title_tag.get_text(strip=True) if title_tag else "See organization website"

            closing_date = job_soup.find("div", class_="field field--name-deadline field--label-inline")


            if closing_date:
                value = closing_date.find("div", class_="field--item")
                if value:
                    closing_date_value = parse_unitar_date(value.get_text(strip=True))

            else: 
                closing_date_value = date(2027, 1, 1)

            check_for_reqs = job_soup.find("div", class_="field field--name-minimun-requirements field--label-above") or job_soup.find("div", class_="field field--name-field-paragraphs")

            if not check_for_reqs:
                quals = "See listing for qualifications."
            else: 
                quals = str(check_for_reqs)

            location = clean_location(get_location(title))

            country, m49 = normalize_country(location)

            row = {
                "_id": ORGANIZATION + (job_id or generate_id(title, job_url)),
                "requisition_id": job_id or generate_id(title, job_url),
                "title": title,
                "url": job_url,
                "location": location,
                "m49": m49, 
                "country": country,
                "qualifications": quals,
                "closing_date": closing_date_value,
                "posted_date": None
            }

            vacancies.append(row)

            time.sleep(1)

    except HTTPError as e:
        print(f'Server error code: {e.code}')

    except URLError as e:
        print(f'Failed to reach server. Reason: {e.reason}')

    return pd.DataFrame(vacancies)


def main(): 
    df = build_unitar_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()