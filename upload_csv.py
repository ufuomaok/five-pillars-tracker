"""
One-off: upload an existing vacancies.csv to Supabase without re-scraping.

Reads vacancies.csv (produced by scraper.py) from the current folder and
upserts every row via scraper.save_supabase — same code path the scraper
uses, so a success here proves the whole upload pipeline.
"""

import csv

from scraper import VacancyListing, save_supabase

FIELDS = [
    "reference", "title", "employer", "location", "salary_text",
    "date_posted", "closing_date", "contract_type", "working_pattern",
    "url", "found_by_keywords", "pillar", "pillar_secondary",
    "pillar_confidence", "taxonomy_version",
]

listings = []
with open("vacancies.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        kwargs = {field: (row.get(field) or None) for field in FIELDS}
        kwargs["found_by_keywords"] = kwargs["found_by_keywords"] or ""
        listings.append(VacancyListing(**kwargs))

print(f"Loaded {len(listings)} listings from vacancies.csv")

if save_supabase(listings):
    print("Uploaded to Supabase successfully.")
else:
    print("Upload failed — see the log line above for the reason.")