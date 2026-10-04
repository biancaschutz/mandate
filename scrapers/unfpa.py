"""UNFPA scraper

Has no API, also no x of Y results, so will need to build something that can iterate until page no longer valid
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

ORGANIZATION = "UNFPA"

def build_unfpa_df():

    is_empty = False
    page = 0

    results = []

    DATE = re.compile(r"\d+ [a-zA-Z]+ \d{4}")

    fg_labels = {"Closing date": "closing_date", 
                "Contract type": "job_type", 
                "Staff grade/level": "job_level", 
                "Location": "location"}
    while not is_empty:
        res = urlopen(f"https://www.unfpa.org/jobs?page={page}").read().decode("utf-8")
        soup = BeautifulSoup(res, "html.parser")
        if soup.find("div", class_="view-empty"):
            is_empty = True
            break
        else: 
            content = soup.find("div", class_="view-content")
            jobs = content.find_all("div", class_="jbs-rows")
            for job in jobs:
                title_url = job.find("h5").find("a")
                title = title_url.getText(strip=True)
                url = title_url['href']
                job_res = {"title": title, "url": url}

                form_groups = job.find_all("div", class_="form-group")
                fg_skeleton = {"closing_date": None, "job_type": None, "job_level": None, "location": None, "m49": None, "country": None}
                for fg in form_groups:
                    has_label = fg.find("label")
                    if not has_label:
                        continue
                    label = fg_labels[has_label.getText(strip=True)]
                    value = fg.find("p").getText(strip=True)
                    if label == "location":
                        cloc = clean_location(value)
                        fg_skeleton[label] = cloc
                        fg_skeleton["country"], fg_skeleton["m49"] = normalize_country(cloc)
                    elif label == "closing_date":
                        fg_skeleton[label] = datetime.strptime(DATE.search(value).group(), "%d %B %Y")
                    else:
                        fg_skeleton[label] = value
                job_details = urlopen(url).read().decode("utf-8")
                job_soup = BeautifulSoup(job_details, "html.parser")


                desc = job_soup.find_all("div", class_="form-group")
                id = None
                for f in desc: 
                    has_label = f.find("label")
                    if not has_label:
                        continue
                    if has_label.getText(strip=True) == "Job ID":
                        id = f.find("p").getText(strip=True)
                if not id:
                    firsts = [w[0] for w in title.replace(r"-", "").split()]
                    id = "".join(firsts[:min(len(firsts), 5)]).upper()

                job_res["qualifications"] = str(job_soup.find("article", class_= lambda i: i and "jobs-content" in i)) or "See listing."
                job_res["_id"], job_res["organization"], job_res["requisition_id"] = ORGANIZATION + id, ORGANIZATION, id
                job_res.update(fg_skeleton)
                results.append(job_res)
        page += 1

    return pd.DataFrame(results)

def main(): 
    df = build_unfpa_df()
    upsert_listings(df, organization=ORGANIZATION)


if __name__ == "__main__":
    main()