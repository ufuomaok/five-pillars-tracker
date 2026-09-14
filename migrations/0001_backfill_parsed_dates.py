import json
import logging
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper import _load_supabase_credentials, _parse_uk_date  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PAGE_SIZE = 1000
BATCH_SIZE = 200


def fetch_all_rows(url: str, key: str) -> list[dict]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    rows = []
    offset = 0
    while True:
        headers["Range"] = f"{offset}-{offset + PAGE_SIZE - 1}"
        resp = requests.get(
            f"{url}/rest/v1/vacancies?select=*&order=reference",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def main() -> None:
    creds = _load_supabase_credentials()
    if creds is None:
        logger.error("No Supabase credentials found — aborting.")
        sys.exit(1)
    url, key = creds
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    rows = fetch_all_rows(url, key)
    logger.info(f"Fetched {len(rows)} rows")

    updates = []
    for row in rows:
        date_posted_parsed = _parse_uk_date(row.get("date_posted"))
        closing_date_parsed = _parse_uk_date(row.get("closing_date"))
        if (date_posted_parsed == row.get("date_posted_parsed")
                and closing_date_parsed == row.get("closing_date_parsed")):
            continue
        row["date_posted_parsed"] = date_posted_parsed
        row["closing_date_parsed"] = closing_date_parsed
        updates.append(row)

    logger.info(f"{len(updates)} rows need a parsed-date update")
    if not updates:
        return

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    endpoint = f"{url}/rest/v1/vacancies"
    total = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i:i + BATCH_SIZE]
        resp = requests.post(endpoint, headers=headers, data=json.dumps(batch), timeout=30)
        if resp.status_code >= 300:
            logger.error(f"Batch update failed (status {resp.status_code}): {resp.text[:500]}")
            sys.exit(1)
        total += len(batch)
        logger.info(f"Backfilled {total}/{len(updates)} rows")

    logger.info("Backfill complete.")


if __name__ == "__main__":
    main()
