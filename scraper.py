import csv
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from five_pillars_taxonomy import PillarClassifier

from enrichment import (
    build_readvert_key,
    classify_org_type,
    derive_region,
    normalise_employer,
    normalise_working_pattern,
    parse_band,
    parse_salary,
)

COLLECTION_METHOD = "weekly"

DEFAULT_KEYWORDS_FILE = "keywords.v1.json"


def load_keyword_vocabulary(filename: str = DEFAULT_KEYWORDS_FILE) -> tuple[list[str], str]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["keywords"], data["version"]


BASE_URL = "https://www.jobs.nhs.uk"
SEARCH_URL = f"{BASE_URL}/candidate/search/results"

USER_AGENT = (
    "five-pillars-tracker/0.1 (independent portfolio project; "
    "contact via ufuomao.com) Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

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
    posted_date: Optional[str] = None
    closing_date_parsed: Optional[str] = None
    band: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_period: Optional[str] = None
    working_pattern_normalised: Optional[str] = None
    employer_normalised: Optional[str] = None
    org_type: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = None
    keyword_version: Optional[str] = None
    scrape_run_id: Optional[str] = None
    collection_method: Optional[str] = None
    advertised_duration_days: Optional[int] = None
    shorter_than_interval: Optional[bool] = None
    current_closing_date: Optional[str] = None
    current_duration_days: Optional[int] = None
    extension_count: Optional[int] = None
    was_extended: Optional[bool] = None
    observed_duration_days: Optional[int] = None
    times_observed: Optional[int] = None
    readvert_key: Optional[str] = None
    backfilled: Optional[bool] = None


def _clean_text(el) -> Optional[str]:
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _direct_text(el) -> Optional[str]:
    if el is None:
        return None
    parts = [c for c in el.contents if isinstance(c, str)]
    text = " ".join(p.strip() for p in parts if p.strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _reference_from_url(url: str) -> str:
    match = re.search(r"/candidate/jobadvert/([^/?]+)", url)
    return match.group(1) if match else url


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _parse_uk_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = re.match(r"^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", text)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None


def _find_next_page_url(soup: BeautifulSoup) -> Optional[str]:
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
) -> tuple[list[VacancyListing], list[str]]:
    by_reference: dict[str, VacancyListing] = {}
    failed_keywords: list[str] = []
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
            failed_keywords.append(keyword)
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

    return list(by_reference.values()), failed_keywords


def enrich_dates(listings: list[VacancyListing]) -> None:
    for listing in listings:
        listing.posted_date = _parse_uk_date(listing.date_posted)
        listing.closing_date_parsed = _parse_uk_date(listing.closing_date)


def _derive_status(closing_date_parsed: Optional[str], today: date) -> str:
    if closing_date_parsed is None:
        return "open"
    return "open" if date.fromisoformat(closing_date_parsed) >= today else "closed"


def _parse_date_str(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    start_d, end_d = _parse_date_str(start), _parse_date_str(end)
    if start_d is None or end_d is None:
        return None
    return (end_d - start_d).days


def enrich_report_fields(listings: list[VacancyListing], keyword_version: str) -> None:
    today = datetime.now(timezone.utc).date()
    for listing in listings:
        listing.band = parse_band(listing.title)
        listing.salary_min, listing.salary_max, listing.salary_period = parse_salary(listing.salary_text)
        listing.working_pattern_normalised = normalise_working_pattern(listing.working_pattern)
        listing.employer_normalised = normalise_employer(listing.employer)
        listing.org_type = classify_org_type(listing.employer)
        listing.region = derive_region(listing.location, listing.employer)
        listing.status = _derive_status(listing.closing_date_parsed, today)
        listing.keyword_version = keyword_version
        listing.readvert_key = build_readvert_key(
            listing.title, listing.employer_normalised, listing.band
        )
        listing.backfilled = False


def classify_listings(listings: list[VacancyListing]) -> None:
    classifier = PillarClassifier()
    for listing in listings:
        result = classifier.classify(listing.title)
        listing.pillar = result.primary_pillar
        listing.pillar_secondary = result.secondary_pillar
        listing.pillar_confidence = result.confidence
        listing.taxonomy_version = classifier.version


def _load_supabase_credentials() -> Optional[tuple[str, str]]:
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


def _fetch_existing_vacancy_state(url: str, key: str, page_size: int = 1000) -> dict[str, dict]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    state: dict[str, dict] = {}
    offset = 0
    while True:
        headers["Range"] = f"{offset}-{offset + page_size - 1}"
        response = requests.get(
            f"{url}/rest/v1/vacancies"
            "?select=reference,first_seen,current_closing_date,extension_count,times_observed"
            "&order=reference",
            headers=headers, timeout=30,
        )
        response.raise_for_status()
        page = response.json()
        for row in page:
            state[row["reference"]] = row
        if len(page) < page_size:
            break
        offset += page_size
    return state


def _fetch_previous_run_started_at(url: str, key: str) -> Optional[datetime]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    response = requests.get(
        f"{url}/rest/v1/scrape_runs?select=started_at&order=started_at.desc&limit=1",
        headers=headers, timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    return datetime.fromisoformat(rows[0]["started_at"]) if rows else None


def _insert_scrape_run(url: str, key: str, run_id: str, started_at_iso: str,
                        finished_at_iso: str, keyword_version: str,
                        taxonomy_version: Optional[str],
                        days_since_previous_run: Optional[int], listings_found: int,
                        rows_new: int, rows_updated: int, rows_unclassified: int,
                        errors: Optional[str]) -> bool:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    row = {
        "run_id": run_id,
        "started_at": started_at_iso,
        "finished_at": finished_at_iso,
        "keyword_version": keyword_version,
        "taxonomy_version": taxonomy_version,
        "collection_method": COLLECTION_METHOD,
        "days_since_previous_run": days_since_previous_run,
        "listings_found": listings_found,
        "rows_new": rows_new,
        "rows_updated": rows_updated,
        "rows_unclassified": rows_unclassified,
        "errors": errors,
    }
    response = requests.post(f"{url}/rest/v1/scrape_runs", headers=headers,
                             data=json.dumps(row), timeout=30)
    if response.status_code >= 300:
        logger.error(
            f"Failed to record scrape_runs row (status {response.status_code}): "
            f"{response.text[:500]}"
        )
        return False
    logger.info(f"Recorded scrape_runs row for run {run_id}")
    return True


def _insert_snapshots(url: str, key: str, listings: list[VacancyListing],
                       run_id: str, seen_at_iso: str, batch_size: int = 200) -> bool:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    rows = [
        {
            "job_reference": listing.reference,
            "run_id": run_id,
            "seen_at": seen_at_iso,
            "status": listing.status,
            "closing_date": listing.closing_date_parsed,
            "salary": listing.salary_text,
            "title": listing.title,
        }
        for listing in listings
    ]
    endpoint = f"{url}/rest/v1/vacancy_snapshots"
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        response = requests.post(endpoint, headers=headers,
                                 data=json.dumps(batch), timeout=30)
        if response.status_code >= 300:
            logger.error(
                f"Failed to insert vacancy_snapshots batch (status {response.status_code}): "
                f"{response.text[:500]}"
            )
            return False
    logger.info(f"Recorded {len(rows)} vacancy_snapshots rows for run {run_id}")
    return True


def _close_stale_open_rows(url: str, key: str, run_start_iso: str) -> bool:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    response = requests.patch(
        f"{url}/rest/v1/vacancies?status=eq.open&last_seen=lt.{run_start_iso}",
        headers=headers,
        data=json.dumps({"status": "closed"}),
        timeout=30,
    )
    if response.status_code >= 300:
        logger.error(
            f"Failed to close stale rows (status {response.status_code}): "
            f"{response.text[:500]}"
        )
        return False
    logger.info("Marked rows not seen in this run as closed.")
    return True


def save_supabase(listings: list[VacancyListing], run_id: str, run_started_at: datetime,
                   errors: Optional[str] = None, batch_size: int = 200) -> bool:
    if not listings:
        logger.warning("No listings to save — skipping database upload.")
        return False

    creds = _load_supabase_credentials()
    if creds is None:
        logger.warning(
            "No Supabase credentials found (env vars or supabase_config.json) "
            "— skipping database upload."
        )
        return False
    url, key = creds

    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    db_write_time = datetime.now(timezone.utc)
    db_write_time_iso = db_write_time.isoformat()

    try:
        previous_started_at = _fetch_previous_run_started_at(url, key)
        existing_state = _fetch_existing_vacancy_state(url, key)
    except requests.exceptions.RequestException:
        logger.exception("Failed to fetch existing state — aborting upload")
        return False

    days_since_previous_run = (
        (run_started_at.date() - previous_started_at.date()).days
        if previous_started_at is not None else None
    )

    rows_new = sum(1 for listing in listings if listing.reference not in existing_state)
    rows_updated = len(listings) - rows_new
    rows_unclassified = sum(1 for listing in listings if listing.pillar == "unclassified")
    keyword_version = listings[0].keyword_version
    taxonomy_version = listings[0].taxonomy_version

    if not _insert_scrape_run(
        url, key, run_id, run_started_at.isoformat(), db_write_time_iso,
        keyword_version, taxonomy_version, days_since_previous_run, len(listings),
        rows_new, rows_updated, rows_unclassified, errors,
    ):
        return False

    new_rows, existing_rows = [], []
    for listing in listings:
        row = asdict(listing)
        row["last_seen"] = db_write_time_iso
        row["current_closing_date"] = listing.closing_date_parsed
        row["current_duration_days"] = _days_between(listing.posted_date, listing.closing_date_parsed)

        existing = existing_state.get(listing.reference)
        if existing is None:
            row["scrape_run_id"] = run_id
            row["collection_method"] = COLLECTION_METHOD
            row["advertised_duration_days"] = row["current_duration_days"]
            if days_since_previous_run is None or row["advertised_duration_days"] is None:
                row["shorter_than_interval"] = None
            else:
                row["shorter_than_interval"] = row["advertised_duration_days"] < days_since_previous_run
            row["extension_count"] = 0
            row["was_extended"] = False
            row["observed_duration_days"] = 0
            row["times_observed"] = 1
            new_rows.append(row)
        else:
            del row["scrape_run_id"]
            del row["collection_method"]
            del row["advertised_duration_days"]
            del row["shorter_than_interval"]

            old_closing = existing.get("current_closing_date")
            new_closing = listing.closing_date_parsed
            changed = old_closing is not None and new_closing is not None and old_closing != new_closing
            extension_count = (existing.get("extension_count") or 0) + (1 if changed else 0)
            row["extension_count"] = extension_count
            row["was_extended"] = extension_count > 0
            row["observed_duration_days"] = _days_between(existing.get("first_seen"), db_write_time_iso)
            row["times_observed"] = (existing.get("times_observed") or 0) + 1
            existing_rows.append(row)

    endpoint = f"{url}/rest/v1/vacancies"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    total = 0
    grand_total = len(new_rows) + len(existing_rows)
    for label, rows in (("new", new_rows), ("existing", existing_rows)):
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            response = requests.post(endpoint, headers=headers,
                                     data=json.dumps(batch), timeout=30)
            if response.status_code >= 300:
                logger.error(
                    f"Supabase upsert failed on {label} rows (status {response.status_code}): "
                    f"{response.text[:500]}"
                )
                return False
            total += len(batch)
            logger.info(f"Upserted {total}/{grand_total} rows to Supabase")

    if not _close_stale_open_rows(url, key, db_write_time_iso):
        return False

    return _insert_snapshots(url, key, listings, run_id, db_write_time_iso)


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
    KEYWORDS, keyword_version = load_keyword_vocabulary()

    run_id = uuid.uuid4().hex
    run_started_at = datetime.now(timezone.utc)
    results, failed_keywords = scrape_keywords(KEYWORDS, max_pages_per_keyword=3)
    enrich_dates(results)
    enrich_report_fields(results, keyword_version=keyword_version)
    classify_listings(results)
    save_csv(results)

    errors = "; ".join(failed_keywords) if failed_keywords else None
    if save_supabase(results, run_id=run_id, run_started_at=run_started_at, errors=errors):
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
