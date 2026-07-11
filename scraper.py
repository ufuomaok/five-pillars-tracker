"""
scraper.py — fetches structured vacancy metadata from jobs.nhs.uk search
results and classifies each one by pillar.

Deliberately scrapes only search-result listing pages, not individual job
advert detail pages. This keeps the request footprint small (one request
per page of ~20 results, rather than one per posting) and keeps us to
metadata-only extraction — consistent with the metadata-only, link-out
design decision (see project notes on NHS Jobs' terms of use).

This is a standalone test script for now, run from inside the
five-pillars-taxonomy folder so it can import the installed taxonomy
package directly. Once it's solid, it belongs in its own separate repo
(the tracker project) — not committed into the taxonomy package's repo.
"""

import csv
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from five_pillars_taxonomy import PillarClassifier

BASE_URL = "https://www.jobs.nhs.uk"
SEARCH_URL = f"{BASE_URL}/candidate/search/results"

USER_AGENT = (
    "five-pillars-tracker/0.1 (independent portfolio project; "
    "contact via ufuomao.com) Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Conservative by default — we don't have confirmed access to jobs.nhs.uk's
# own robots.txt crawl-delay, so this errs high. Adjust down only if you've
# checked jobs.nhs.uk/robots.txt yourself and it specifies something lower.
REQUEST_DELAY_SECONDS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class VacancyListing:
    reference: str
    title: str
    employer: str
    location: str
    salary_text: Optional[str]
    date_posted: Optional[str]
    closing_date: Optional[str]
    contract_type: Optional[str]
    working_pattern: Optional[str]
    url: str
    found_by_keywords: str = ""
    pillar: Optional[str] = None
    pillar_secondary: Optional[str] = None
    pillar_confidence: Optional[str] = None
    taxonomy_version: Optional[str] = None


def _clean_text(el) -> Optional[str]:
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _direct_text(el) -> Optional[str]:
    """Text belonging directly to this element, excluding nested children —
    needed because employer name and location share one parent <h3>."""
    if el is None:
        return None
    parts = [c for c in el.contents if isinstance(c, str)]
    text = " ".join(p.strip() for p in parts if p.strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _reference_from_url(url: str) -> str:
    match = re.search(r"/candidate/jobadvert/([^/?]+)", url)
    return match.group(1) if match else url


def _find_next_page_url(soup: BeautifulSoup) -> Optional[str]:
    """Look for a pagination 'next' link. NHS.UK design-system pagination
    typically uses an <a> with 'next' in its accessible text or aria-label."""
    for a in soup.find_all("a", href=True):
        label = (a.get("aria-label") or "") + " " + a.get_text(strip=True)
        if "next" in label.lower():
            return urljoin(BASE_URL, a["href"])
    return None


def parse_result_card(card) -> VacancyListing:
    title_link = card.find(attrs={"data-test": "search-result-job-title"})
    title = _clean_text(title_link) or ""
    relative_url = title_link["href"] if title_link else ""
    full_url = urljoin(BASE_URL, relative_url)
    reference = _reference_from_url(relative_url)

    location_block = card.find(attrs={"data-test": "search-result-location"})
    employer_el = location_block.find("h3") if location_block else None
    employer = _direct_text(employer_el) or ""
    location_el = location_block.find(class_="location-font-size") if location_block else None
    location = _clean_text(location_el) or ""

    def field(data_test: str) -> Optional[str]:
        el = card.find(attrs={"data-test": data_test})
        if el is None:
            return None
        strong = el.find("strong")
        return _clean_text(strong) if strong else _clean_text(el)

    return VacancyListing(
        reference=reference,
        title=title,
        employer=employer,
        location=location,
        salary_text=field("search-result-salary"),
        date_posted=field("search-result-publicationDate"),
        closing_date=field("search-result-closingDate"),
        contract_type=field("search-result-jobType"),
        working_pattern=field("search-result-workingPattern"),
        url=full_url,
    )


def fetch_soup(
    session: requests.Session,
    url: str,
    max_attempts: int = 3,
    backoff_seconds: int = 30,
) -> BeautifulSoup:
    """Fetch a page with retries.

    Transient network failures (timeouts, connection resets, 5xx) are
    retried up to max_attempts with a pause between tries — a monthly
    pipeline must survive the odd flaky response. Only if every attempt
    fails does the exception propagate (and scrape_keywords contains the
    blast radius to that one keyword).
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for {url} "
                    f"({type(e).__name__}) — retrying in {backoff_seconds}s"
                )
                time.sleep(backoff_seconds)
    raise last_error


def scrape_keyword(
    session: requests.Session,
    keyword: str,
    max_pages: int = 3,
) -> list[VacancyListing]:
    """Scrape up to max_pages of search results for one keyword."""
    listings: list[VacancyListing] = []
    seen_references: set[str] = set()

    url = f"{SEARCH_URL}?searchFormType=main&keyword={keyword}"
    page_num = 1

    while url and page_num <= max_pages:
        logger.info(f"[{keyword}] Fetching page {page_num}: {url}")
        soup = fetch_soup(session, url)
        cards = soup.find_all(attrs={"data-test": "search-result"})
        logger.info(f"[{keyword}] Found {len(cards)} result cards on this page")

        for card in cards:
            try:
                listing = parse_result_card(card)
                if listing.reference not in seen_references:
                    seen_references.add(listing.reference)
                    listings.append(listing)
            except Exception:
                logger.exception("Failed to parse a result card, skipping it")

        url = _find_next_page_url(soup)
        page_num += 1
        if url and page_num <= max_pages:
            time.sleep(REQUEST_DELAY_SECONDS)

    return listings


def scrape_keywords(
    keywords: list[str],
    max_pages_per_keyword: int = 3,
) -> list[VacancyListing]:
    """Scrape several keywords and merge into one deduplicated dataset.

    Deduplication is by job reference (e.g. C9413-26-0512), which is
    stable across searches. When the same job is found by multiple
    keywords, we keep one copy and record all the keywords that found it
    in found_by_keywords — useful later for understanding which search
    terms are actually pulling their weight.
    """
    by_reference: dict[str, VacancyListing] = {}
    session = requests.Session()

    for i, keyword in enumerate(keywords):
        try:
            results = scrape_keyword(session, keyword, max_pages=max_pages_per_keyword)
        except Exception:
            logger.exception(
                f"[{keyword}] scrape failed even after retries — "
                f"skipping this keyword, keeping everything scraped so far"
            )
            results = []
        new_count = 0
        for listing in results:
            if listing.reference in by_reference:
                existing = by_reference[listing.reference]
                existing.found_by_keywords += f"|{keyword}"
            else:
                listing.found_by_keywords = keyword
                by_reference[listing.reference] = listing
                new_count += 1
        logger.info(
            f"[{keyword}] {len(results)} results, {new_count} new after dedup "
            f"(running total: {len(by_reference)})"
        )
        if i < len(keywords) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    return list(by_reference.values())


def classify_listings(listings: list[VacancyListing]) -> None:
    classifier = PillarClassifier()
    for listing in listings:
        result = classifier.classify(listing.title)
        listing.pillar = result.primary_pillar
        listing.pillar_secondary = result.secondary_pillar
        listing.pillar_confidence = result.confidence
        listing.taxonomy_version = classifier.version


def _load_supabase_credentials() -> Optional[tuple[str, str]]:
    """Credentials come from env vars (SUPABASE_URL / SUPABASE_SERVICE_KEY)
    if set — that's what GitHub Actions will use — otherwise from a local
    supabase_config.json next to this script:
        {"url": "https://xxxx.supabase.co", "service_key": "sb_secret_..."}
    That file must NEVER be committed to git.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return url, key

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "supabase_config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        return config["url"], config["service_key"]
    return None


def save_supabase(listings: list[VacancyListing], batch_size: int = 200) -> bool:
    """Upsert listings into the Supabase `vacancies` table.

    Upsert semantics (on the `reference` primary key): new jobs are
    inserted; already-seen jobs have their provided columns updated.
    `first_seen` is never sent, so the database default preserves the
    original sighting date; `last_seen` is sent as now, so it refreshes
    on every run. Jobs that disappear from NHS Jobs simply stop getting
    their last_seen refreshed — which is how staleness is detected later.
    """
    creds = _load_supabase_credentials()
    if creds is None:
        logger.warning(
            "No Supabase credentials found (env vars or supabase_config.json) "
            "— skipping database upload."
        )
        return False
    url, key = creds

    # Tolerate common URL paste variants: trailing slashes, or the full
    # REST URL from the Data API settings page (".../rest/v1").
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for listing in listings:
        row = asdict(listing)
        row["last_seen"] = now
        rows.append(row)

    endpoint = f"{url}/rest/v1/vacancies"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        response = requests.post(endpoint, headers=headers,
                                 data=json.dumps(batch), timeout=30)
        if response.status_code >= 300:
            logger.error(
                f"Supabase upsert failed (status {response.status_code}): "
                f"{response.text[:500]}"
            )
            return False
        total += len(batch)
        logger.info(f"Upserted {total}/{len(rows)} rows to Supabase")

    return True


def save_csv(listings: list[VacancyListing], path: str = "vacancies.csv") -> None:
    if not listings:
        logger.warning("No listings to save.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(listings[0]).keys()))
        writer.writeheader()
        for listing in listings:
            writer.writerow(asdict(listing))
    logger.info(f"Saved {len(listings)} listings to {path}")


if __name__ == "__main__":
    # Keywords chosen to cover all five pillars' vocabulary, not just
    # roles with "digital" in the title. Kept modest for a test run —
    # extend once confirmed working (candidates: "cyber security",
    # "business intelligence", "data engineer", "CCIO", "PACS").
    KEYWORDS = [
        "digital",
        "informatics",
        "clinical systems",
        "EPR",
        "information governance",
        "data analyst",
        "cyber security",
        "data engineer",
        "business intelligence",
        "IT support",
        "network engineer",
        "software developer",
        "clinical coding",
        "health records",
        "PACS",
        "user researcher",
        "product owner",
        "digital trainer",
    ]

    # 3 pages/keyword, polite 20s delays: expect roughly 18-20 minutes
    # for a full run. Transient timeouts are retried automatically; a
    # keyword that fails all retries is skipped without losing the rest.
    results = scrape_keywords(KEYWORDS, max_pages_per_keyword=3)
    classify_listings(results)
    save_csv(results)

   if save_supabase(results):
        print("\nUploaded to Supabase successfully.")
    else:
        print("\nSupabase upload skipped or failed — data is still in vacancies.csv.")
        import sys
        sys.exit(1)
    print(f"\n{len(results)} unique listings scraped across {len(KEYWORDS)} keywords.\n")
    pillar_counts: dict[str, int] = {}
    for r in results:
        pillar_counts[r.pillar] = pillar_counts.get(r.pillar, 0) + 1
    for pillar, count in sorted(pillar_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {pillar:15s} {count}")

    print("\nFirst 5 results:")
    for r in results[:5]:
        secondary = f" (+{r.pillar_secondary})" if r.pillar_secondary else ""
        print(f"  [{r.pillar}{secondary}] {r.title} — {r.employer} — {r.salary_text}")