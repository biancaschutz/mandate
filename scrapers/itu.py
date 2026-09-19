"""ITU scraper

Uses a table format, so needs parsing of HTML right off the bat
"""

import math
import re
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from combiner import upsert_listings
from location import clean_location, normalize_country

ORGANIZATION="ITU"

base = "https://jobs.itu.int"
url = f"{base}/search/?q=&sortColumn=referencedate&sortDirection=desc"

def parse_jobs_table(html_code: str):
    soup = BeautifulSoup(html_code, "html.parser")
    table = soup.find("table")

    rows = table.find_all("tr")
    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]

    records = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        title_cell = cells[0]
        anchors = title_cell.find_all("a", href=True)
        if not anchors:
            continue

        a = anchors[0]
        record = {
            "Title": a.get_text(strip=True),
            "Link": urljoin(base, a["href"]),
        }

        for col_name, cell in zip(header[1:], cells[1:]):
            record[col_name] = cell.get_text(strip=True)

        records.append(record)

    return pd.DataFrame(records)

VACANCY_PATTERN = re.compile(
    r"(?:Vacancy notice no\.?|Num[ée]ro de l'avis de vacance)\s*:?\s*([0-9]+)",
    re.IGNORECASE,
)

# used claude for this
# match "Application deadline (Midnight Geneva Time):" (EN) or "Date limite de candidature (Minuit heure de Genève)" (FR, sometimes no colon)
# Date itself may be in English ("17 September 2026") or French ("28 septembre 2026")
DEADLINE_PATTERN = re.compile(
    r"(?:Application deadline|Date limite de candidature)"
    r"(?:\s*\([^)]*\))?"      # optional "(Midnight Geneva Time)" / "(Minuit heure de Genève)"
    r"\s*:?\s*"
    r"(\d{1,2}\s+[A-Za-zéûîôâàèù]+\s+\d{4})",   # allow accented French month names
    re.IGNORECASE,
)
 
# French to english
FR_MONTHS = {
    "janvier": "January", "février": "February", "fevrier": "February",
    "mars": "March", "avril": "April", "mai": "May", "juin": "June",
    "juillet": "July", "août": "August", "aout": "August",
    "septembre": "September", "octobre": "October",
    "novembre": "November", "décembre": "December", "decembre": "December",
}
 
 
def parse_date_multilang(date_str: str):
    """Parse a date string that may contain an English or French month name."""
    parts = date_str.split()
    if len(parts) == 3:
        day, month, year = parts
        month_en = FR_MONTHS.get(month.lower(), month)  # translate if French
        date_str = f"{day} {month_en} {year}"
    return dateparser.parse(date_str, dayfirst=True)


QUALIFICATIONS_HEADERS = {"qualifications required", "qualifications requises"}

def get_qualifications_text(html_code: str) -> str | None:
    """
    Find the <h2>QUALIFICATIONS REQUIRED</h2> (or French "QUALIFICATIONS REQUISES")
    heading, then return the text of the content div that follows its wrapper div.
 
    Structure on the page:
        <div>                              <- outer wrapper
          <div>                            <- h2's own parent div
            <h2>QUALIFICATIONS REQUIRED</h2>
          </div>
          <div>...actual content...</div>  <- sibling of h2's PARENT, not of h2 itself
        </div>
    """
    soup = BeautifulSoup(html_code, "html.parser")
 
    target_h2 = None
    for h2 in soup.find_all("h2"):
        heading_text = h2.get_text(strip=True).lower()
        if heading_text in QUALIFICATIONS_HEADERS:
            target_h2 = h2
            break
 
    if target_h2 is None:
        return "See listing for qualifications."
 
    heading_wrapper = target_h2.parent
    content_div = heading_wrapper.find_next_sibling("div")
 
    if content_div is None:
        return "See listing for qualifications."
 
    text = content_div.get_text(separator="\n", strip=True)

    lines = [line for line in text.split("\n") if line and line != "\xa0"]
    return "\n".join(lines).strip() or "See listing for qualifications."

def build_itu_df():
    print("Fetching ITU listings...")
    response = httpx.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    n_jobs = int(soup.select("span.paginationLabel b")[1].text)
    n_pages = math.floor(n_jobs / 25)

    urls = [url]
    urls.extend([url + "&startrow=" + str(i * 25 + 25) for i in range(n_pages)])

    dfs = []
    for u in urls:
        resp = httpx.get(u)
        resp.raise_for_status()
        df = parse_jobs_table(resp.text)
        if not df.empty:
        
            dfs.append(df[['Title', 'Link', 'Location', 'Job family', 'Date']])

    result = pd.concat(dfs, ignore_index=True)
 
    deadlines = []
    vac_nums = []
    qualifications = []
    
    for link in result['Link']:
        response = httpx.get(link, timeout=20)
        response.raise_for_status()
    
        text = BeautifulSoup(response.text, "html.parser").get_text(separator="\n")

        qual_text = get_qualifications_text(response.text)
        qualifications.append(qual_text)
    
        vac_match = VACANCY_PATTERN.search(text)
        deadline_match = DEADLINE_PATTERN.search(text)
    
        vac_nums.append(vac_match.group(1) if vac_match else None)
    
        if deadline_match:
            try:
                deadlines.append(parse_date_multilang(deadline_match.group(1)))
            except (ValueError, OverflowError):
                deadlines.append(deadline_match.group(1))  # fall back to raw string
        else:
            deadlines.append(None)

    result['requisition_id'] = vac_nums
    result['_id'] = ["ITU" + vac for vac in vac_nums]
    result['closing_date'] = deadlines
    result['qualifications'] = qualifications
    cleaned_locs = [clean_location(loc) for loc in result["Location"]]
    results = [normalize_country(loc) for loc in cleaned_locs]
    names = [r[0] for r in results]
    codes = [r[1] for r in results]
    result["location"] = cleaned_locs
    result["country"] = names
    result["m49"] = codes

    COLUMN_MAP = {
        "Title": "title",
        "Job family": "job_type",
        "Date": "posted_date",
        "Link": "url"
    }

    result = result.rename(columns=COLUMN_MAP)

    result = result.set_index("_id")

    print("Fetched ITU listings.")
    return result

def main():
    df = build_itu_df()
    if df.empty:
        print("No listings fetched; skipping DB write.")
        return
    upsert_listings(df, organization=ORGANIZATION)

if __name__ == "__main__":
    main()