import csv
import uuid
from datetime import datetime, timezone

from scraper import SAVE_OK, VacancyListing, save_supabase

FIELDS = [
    "reference", "title", "employer", "location", "salary_text",
    "date_posted", "closing_date", "contract_type", "working_pattern",
    "url", "found_by_keywords", "pillar", "pillar_secondary",
    "pillar_confidence", "taxonomy_version",
    "posted_date", "closing_date_parsed",
    "band", "salary_min", "salary_max", "salary_period",
    "working_pattern_normalised", "employer_normalised", "org_type",
    "region", "status", "keyword_version", "scrape_run_id",
]
NUMERIC_FIELDS = {"salary_min", "salary_max"}

listings = []
with open("vacancies.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        kwargs = {field: (row.get(field) or None) for field in FIELDS}
        kwargs["found_by_keywords"] = kwargs["found_by_keywords"] or ""
        for field in NUMERIC_FIELDS:
            if kwargs[field] is not None:
                kwargs[field] = float(kwargs[field])
        listings.append(VacancyListing(**kwargs))

print(f"Loaded {len(listings)} listings from vacancies.csv")

save_result = save_supabase(listings, run_id=uuid.uuid4().hex, run_started_at=datetime.now(timezone.utc))
if save_result == SAVE_OK:
    print("Uploaded to Supabase successfully.")
else:
    print(f"Upload did not fully succeed ({save_result}) — see the log line above for the reason.")