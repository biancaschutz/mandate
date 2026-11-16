"""UNICEF

This is a messy one, with major parsing for qualifications
"""

import math
import re
import time

import pandas as pd
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

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
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def is_qualification_header(text):
    norm = normalize_text(text)
    if len(norm) > 250:
        return False
    if norm.count(".") > 1:
        return False
    return bool(HEADER_RE.search(norm))


def is_stop_heading(text):
    low = normalize_text(text).casefold().rstrip(":")

    return len(low) < 100 and low in STOP_HEADINGS


DEBUG_MISSES = []


def find_header_split(text):
    """If a qualification header appears inside this block (even mixed
    with other content), return the text starting from the header.
    Otherwise return None."""
    match = HEADER_RE.search(text)
    if not match:
        return None
    tail = text[match.start() :]
    if len(tail) < 300 or "/" in text[max(0, match.start() - 5) : match.start() + 80]:
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
            DEBUG_MISSES.append(
                {
                    "url": job_url,
                    "raw_text": normalize_text(container.get_text(" ", strip=True)),
                }
            )
        return None

    fragment = "\n".join(result)
    clean_soup = BeautifulSoup(fragment, "html.parser")
    return clean_soup.decode_contents().strip()


SEARCH_URL = "https://jobs.unicef.org/jobs/search"

# Titles carry requisition numbers inconsistently ("#596996", "# 596990",
# "#00138514", several per title, or none), so they're best-effort only.
REQ_ID_RE = re.compile(r"#\s*(\d+)")
TOTAL_RE = re.compile(r"of\s+(\d+)\s+in total", re.IGNORECASE)

# Closing dates render like "23 Nov 2026 - 09:55 EAT", in the duty
# station's local zone. Ambiguous abbreviations: CST is taken as US/Central
# America (-06:00), AST as Arabia (+03:00), IST as India (+05:30).
TZ_OFFSETS = {
    "UTC": "+00:00",
    "GMT": "+00:00",
    "WET": "+00:00",
    "BST": "+01:00",
    "WEST": "+01:00",
    "CET": "+01:00",
    "WAT": "+01:00",
    "CEST": "+02:00",
    "EET": "+02:00",
    "CAT": "+02:00",
    "SAST": "+02:00",
    "EEST": "+03:00",
    "EAT": "+03:00",
    "AST": "+03:00",
    "MSK": "+03:00",
    "TRT": "+03:00",
    "GST": "+04:00",
    "AFT": "+04:30",
    "PKT": "+05:00",
    "UZT": "+05:00",
    "IST": "+05:30",
    "NPT": "+05:45",
    "BDT": "+06:00",
    "MMT": "+06:30",
    "ICT": "+07:00",
    "WIB": "+07:00",
    "SGT": "+08:00",
    "HKT": "+08:00",
    "PHT": "+08:00",
    "PHST": "+08:00",
    "AWST": "+08:00",
    "JST": "+09:00",
    "KST": "+09:00",
    "TLT": "+09:00",
    "AEST": "+10:00",
    "AEDT": "+11:00",
    "NZST": "+12:00",
    "NZDT": "+13:00",
    "EST": "-05:00",
    "EDT": "-04:00",
    "CST": "-06:00",
    "CDT": "-05:00",
    "MST": "-07:00",
    "MDT": "-06:00",
    "PST": "-08:00",
    "PDT": "-07:00",
}


def card_text(card, selector):
    el = card.select_one(selector)
    return normalize_text(el.get_text(" ", strip=True)) if el else None


def parse_closing_date(text):
    """'Closing at: 23 Nov 2026 - 09:55 AEDT' -> ISO string with offset."""
    if not text:
        return None
    text = re.sub(r"^closing at:\s*", "", text, flags=re.IGNORECASE)
    match = re.match(r"(\d{1,2} \w{3} \d{4}) - (\d{1,2}:\d{2})\s*([A-Z]+)?", text)
    if not match:
        return None
    date_part, time_part, tz = match.groups()
    ts = pd.to_datetime(f"{date_part} {time_part}", format="%d %b %Y %H:%M")
    offset = TZ_OFFSETS.get(tz or "UTC")
    if offset is None:
        print(f"Unknown timezone {tz!r} in closing date; treating as UTC")
        offset = "+00:00"
    return ts.strftime("%Y-%m-%dT%H:%M:00") + offset


def parse_search_page(html):
    """Return (jobs, total_count) from one /jobs/search results page."""
    soup = BeautifulSoup(html, "html.parser")
    total_match = TOTAL_RE.search(soup.get_text(" ", strip=True))
    total = int(total_match.group(1)) if total_match else None

    jobs = {}
    for card in soup.select("article.job-search-results-card-col"):
        link = card.select_one(".job-search-results-card-title a")
        if not link:
            continue
        title = normalize_text(link.get_text(" ", strip=True))
        job_url = link["href"]
        try:
            slug = job_url.rstrip("/").rsplit("/", 1)[-1]
            req_match = REQ_ID_RE.search(title)
            req_id = req_match.group(1) if req_match else None

            loc = card_text(card, ".job-component-location span")
            loc_cleaned = clean_location(loc)
            country_name, country_code = normalize_country(loc_cleaned)[:2]

            jobs[ORGANIZATION + slug] = {
                "title": title,
                "url": job_url,
                "job_type": card_text(card, ".job-component-employment-type span"),
                "location": loc_cleaned,
                "country": country_name,
                "m49": country_code,
                "closing_date": parse_closing_date(
                    card_text(card, ".job-component-closing-at span")
                ),
                # Job detail pages are behind bot protection, so the posted
                # date and full qualifications aren't available.
                "posted_date": None,
                "qualifications": "See listing.",
                "requisition_id": req_id,
            }
        except Exception as e:
            print(f"Failed on {job_url}: {e}")
    return jobs, total


CARD_SELECTOR = "article.job-search-results-card-col"
# robots.txt asks for Crawl-delay: 5
PAGE_DELAY = 5


def fetch_search_page(browser_page, page):
    """Load one results page in a real browser and return its HTML.

    jobs.unicef.org answers plain HTTP clients with an empty 202 (a JS
    challenge), so pages are rendered with Playwright instead of requests.
    """
    url = f"{SEARCH_URL}?page={page}"
    browser_page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        browser_page.wait_for_selector(CARD_SELECTOR, timeout=30_000)
    except PlaywrightTimeout:
        raise RuntimeError(
            f"No job cards on {url} after 30s (blocked, or the page layout changed)"
        ) from None
    return browser_page.content()


def build_unicef_df():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            browser_page = browser.new_page()
            jobs, total = parse_search_page(fetch_search_page(browser_page, 1))
            per_page = len(jobs) or 1
            n_pages = math.ceil(total / per_page) if total else 1

            for pg in range(2, n_pages + 1):
                time.sleep(PAGE_DELAY)
                page_jobs, _ = parse_search_page(fetch_search_page(browser_page, pg))
                if not page_jobs:
                    break
                jobs.update(page_jobs)
        finally:
            browser.close()

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
