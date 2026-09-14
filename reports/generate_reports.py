import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper import _load_supabase_credentials  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
MISSING = "(none)"


def _fetch_all(url: str, key: str, path: str, order: str, page_size: int = 1000) -> list[dict]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows: list[dict] = []
    offset = 0
    while True:
        headers["Range"] = f"{offset}-{offset + page_size - 1}"
        response = requests.get(f"{url}/rest/v1/{path}&order={order}", headers=headers, timeout=30)
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _write_csv(filename: str, fieldnames: list[str], rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows):>5} rows -> {path.name}")


def _median_iqr(values: list[float]) -> tuple:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None, None, None
    median = statistics.median(values)
    if len(values) >= 4:
        q1, _, q3 = statistics.quantiles(values, n=4)
    else:
        q1 = q3 = median
    return median, q1, q3


def report_postings_per_pillar_per_month(vacancies: list[dict]) -> None:
    counts: Counter = Counter()
    skipped = 0
    for v in vacancies:
        posted = v.get("posted_date")
        if not posted:
            skipped += 1
            continue
        counts[(posted[:7], v.get("pillar") or "unclassified")] += 1
    rows = [
        {"month": month, "pillar": pillar, "count": count}
        for (month, pillar), count in sorted(counts.items())
    ]
    _write_csv("postings_per_pillar_per_month.csv", ["month", "pillar", "count"], rows)
    if skipped:
        print(f"  ({skipped} rows skipped — no posted_date)")


def report_band_distribution(vacancies: list[dict]) -> None:
    overall = Counter(v.get("band") or MISSING for v in vacancies)
    rows = [{"band": band, "count": count}
            for band, count in sorted(overall.items(), key=lambda kv: -kv[1])]
    _write_csv("band_distribution_overall.csv", ["band", "count"], rows)

    by_pillar = Counter((v.get("pillar") or "unclassified", v.get("band") or MISSING) for v in vacancies)
    rows = [{"pillar": pillar, "band": band, "count": count}
            for (pillar, band), count in sorted(by_pillar.items())]
    _write_csv("band_distribution_by_pillar.csv", ["pillar", "band", "count"], rows)


def report_days_open(vacancies: list[dict]) -> None:
    closed = [v for v in vacancies
              if v.get("status") == "closed" and v.get("current_duration_days") is not None]
    print(f"  ({len(closed)}/{len(vacancies)} rows used — status='closed' with a known duration)")

    def grouped(key_fn, dimension: str, missing_label: str) -> list[dict]:
        groups = defaultdict(list)
        for v in closed:
            groups[key_fn(v) or missing_label].append(v["current_duration_days"])
        rows = []
        for key, values in sorted(groups.items()):
            median, q1, q3 = _median_iqr(values)
            rows.append({dimension: key, "n": len(values),
                         "median_days_open": median, "iqr_low": q1, "iqr_high": q3})
        return rows

    cols = lambda dim: [dim, "n", "median_days_open", "iqr_low", "iqr_high"]  # noqa: E731
    _write_csv("days_open_by_pillar.csv", cols("pillar"),
               grouped(lambda v: v.get("pillar"), "pillar", "unclassified"))
    _write_csv("days_open_by_band.csv", cols("band"),
               grouped(lambda v: v.get("band"), "band", MISSING))
    _write_csv("days_open_by_org_type.csv", cols("org_type"),
               grouped(lambda v: v.get("org_type"), "org_type", MISSING))


def report_readvertisement(vacancies: list[dict]) -> None:
    groups = defaultdict(list)
    for v in vacancies:
        key = v.get("readvert_key")
        if key:
            groups[key].append(v)

    rows = []
    for key, items in groups.items():
        references = {item["reference"] for item in items}
        rows.append({
            "readvert_key": key,
            "title_example": items[0].get("title"),
            "employer_normalised": items[0].get("employer_normalised"),
            "band": items[0].get("band") or MISSING,
            "times_advertised": len(references),
        })
    rows.sort(key=lambda r: -r["times_advertised"])
    _write_csv("readvertisement_by_role.csv",
               ["readvert_key", "title_example", "employer_normalised", "band", "times_advertised"], rows)

    total = len(rows)
    readvertised = sum(1 for r in rows if r["times_advertised"] > 1)
    rate = readvertised / total if total else 0
    print(f"  re-advertisement rate: {readvertised}/{total} role groups ({rate:.1%}) advertised more than once")


def report_concentration(vacancies: list[dict]) -> None:
    total = len(vacancies)
    if total == 0:
        return

    def breakdown(field: str) -> list[dict]:
        counts = Counter(v.get(field) or MISSING for v in vacancies)
        return [{field: value, "count": count, "share_pct": round(100 * count / total, 2)}
                for value, count in counts.most_common()]

    _write_csv("employer_concentration.csv", ["employer_normalised", "count", "share_pct"],
               breakdown("employer_normalised"))
    _write_csv("region_concentration.csv", ["region", "count", "share_pct"],
               breakdown("region"))


def report_contract_and_working_pattern(vacancies: list[dict]) -> None:
    total = len(vacancies)
    if total == 0:
        return

    def breakdown(field: str, out_field: str) -> list[dict]:
        counts = Counter(v.get(field) or MISSING for v in vacancies)
        return [{out_field: value, "count": count, "share_pct": round(100 * count / total, 2)}
                for value, count in counts.most_common()]

    _write_csv("contract_type_split.csv", ["contract_type", "count", "share_pct"],
               breakdown("contract_type", "contract_type"))
    _write_csv("working_pattern_split.csv", ["working_pattern", "count", "share_pct"],
               breakdown("working_pattern_normalised", "working_pattern"))


def report_unclassified_share_per_run(scrape_runs: list[dict]) -> None:
    rows = []
    for run in sorted(scrape_runs, key=lambda r: r["started_at"]):
        found = run.get("listings_found") or 0
        unclassified = run.get("rows_unclassified") or 0
        share = round(100 * unclassified / found, 2) if found else None
        rows.append({
            "run_id": run["run_id"], "started_at": run["started_at"],
            "collection_method": run.get("collection_method"),
            "comparability_key": run.get("comparability_key"),
            "listings_found": found, "rows_unclassified": unclassified,
            "unclassified_share_pct": share,
        })
    _write_csv("unclassified_share_per_run.csv",
               ["run_id", "started_at", "collection_method", "comparability_key",
                "listings_found", "rows_unclassified", "unclassified_share_pct"], rows)


def main() -> None:
    creds = _load_supabase_credentials()
    if creds is None:
        print("No Supabase credentials found (env vars or supabase_config.json).")
        sys.exit(1)
    url, key = creds
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    print("Fetching data...")
    vacancies = _fetch_all(url, key, "vacancies?select=*", order="reference")
    print(f"  {len(vacancies)} vacancies")
    scrape_runs = _fetch_all(url, key, "scrape_runs?select=*", order="run_id")
    print(f"  {len(scrape_runs)} scrape_runs")

    print("\nPostings per pillar per month:")
    report_postings_per_pillar_per_month(vacancies)
    print("Band distribution:")
    report_band_distribution(vacancies)
    print("Days open (median/IQR) by pillar, band, org_type:")
    report_days_open(vacancies)
    print("Re-advertisement by role:")
    report_readvertisement(vacancies)
    print("Employer/region concentration:")
    report_concentration(vacancies)
    print("Contract type / working pattern split:")
    report_contract_and_working_pattern(vacancies)
    print("Unclassified share per run:")
    report_unclassified_share_per_run(scrape_runs)

    print(f"\nAll reports written to {OUTPUT_DIR}")
    print("Check unclassified_share_per_run.csv's comparability_key column before "
          "combining figures across runs that used a different methodology.")


if __name__ == "__main__":
    main()
