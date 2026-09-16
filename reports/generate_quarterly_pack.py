import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from enrichment import parse_band, parse_salary  # noqa: E402
from scraper import _load_supabase_credentials  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parent
MISSING = "(none)"

LENGTH_BIAS_PARAGRAPH = (
    "This dataset is built from periodic snapshots of NHS Jobs search results, "
    "not a continuous feed. An advert that is posted and closes entirely between "
    "two scrape runs is never observed at all. Because of this, the probability "
    "of an advert being captured rises with how long it stays open — a role "
    "advertised for six weeks is far more likely to be caught by at least one "
    "scrape than one advertised for four days. This is length-biased sampling: "
    "it does not affect the classification of captured adverts, but it means "
    "total counts and pillar shares in this pack systematically understate "
    "short-lived postings relative to long-running ones. A pillar or role type "
    "where postings tend to be brief will therefore appear smaller here than "
    "its true share of the market, and vice versa for pillars where postings "
    "typically run long. See the bias diagnostics section for how much of this "
    "quarter's captured data looks like it was only caught by luck."
)

PROVISIONAL_PREFIX = "Provisional - monthly collection"

PROVISIONAL_STANDING_NOTE = (
    "**This quarter's figures are provisional.** Some or all of the scrape runs "
    "behind this pack used monthly (or unknown) collection, not weekly. Monthly "
    "collection misses far more short-lived adverts than weekly collection does "
    "(see methodology.md), so these numbers describe *direction of travel* only "
    "— they are not a reliable measure of actual vacancy volume, and should not "
    "be compared against headline (fully-weekly) quarters."
)


def quarter_containing(d: date) -> tuple[int, int]:
    if d.month in (4, 5, 6):
        return d.year, 1
    if d.month in (7, 8, 9):
        return d.year, 2
    if d.month in (10, 11, 12):
        return d.year, 3
    return d.year - 1, 4


def quarter_bounds(fy_year: int, q: int) -> tuple[date, date]:
    starts = {1: date(fy_year, 4, 1), 2: date(fy_year, 7, 1),
              3: date(fy_year, 10, 1), 4: date(fy_year + 1, 1, 1)}
    ends = {1: date(fy_year, 6, 30), 2: date(fy_year, 9, 30),
            3: date(fy_year, 12, 31), 4: date(fy_year + 1, 3, 31)}
    return starts[q], ends[q]


def previous_quarter(fy_year: int, q: int) -> tuple[int, int]:
    return (fy_year - 1, 4) if q == 1 else (fy_year, q - 1)


def most_recently_completed_quarter(today: date) -> tuple[int, int, date, date]:
    fy_year, q = previous_quarter(*quarter_containing(today))
    start, end = quarter_bounds(fy_year, q)
    return fy_year, q, start, end


def quarter_label(fy_year: int, q: int) -> str:
    return f"{fy_year}-Q{q}"


def parse_quarter_label(label: str) -> tuple[int, int]:
    year_str, q_str = label.split("-Q")
    return int(year_str), int(q_str)


def human_quarter_title(q: int, quarter_start: date) -> str:
    return f"Q{q} {quarter_start.year}"


def _fetch_all(url: str, key: str, path: str, order: str, page_size: int = 1000,
                params: dict | None = None) -> list[dict]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    request_params = dict(params or {})
    request_params["order"] = order
    rows: list[dict] = []
    offset = 0
    while True:
        headers["Range"] = f"{offset}-{offset + page_size - 1}"
        response = requests.get(f"{url}/rest/v1/{path}", headers=headers,
                                params=request_params, timeout=30)
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def build_point_in_time_cut(vacancies: list[dict], snapshots: list[dict], quarter_end: date) -> list[dict]:
    latest_snapshot: dict[str, dict] = {}
    for snap in snapshots:
        seen_at = datetime.fromisoformat(snap["seen_at"]).date()
        if seen_at > quarter_end:
            continue
        ref = snap["job_reference"]
        existing = latest_snapshot.get(ref)
        if existing is None or datetime.fromisoformat(snap["seen_at"]) > datetime.fromisoformat(existing["seen_at"]):
            latest_snapshot[ref] = snap

    vacancies_by_ref = {v["reference"]: v for v in vacancies}

    rows = []
    for ref, snap in latest_snapshot.items():
        current = vacancies_by_ref.get(ref)
        if current is None:
            continue
        band = parse_band(snap.get("title"))
        salary_min, salary_max, salary_period = parse_salary(snap.get("salary"))
        rows.append({
            "reference": ref,
            "title": snap.get("title"),
            "salary_text": snap.get("salary"),
            "closing_date": snap.get("closing_date"),
            "status": snap.get("status"),
            "band": band,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_period": salary_period,
            "employer_normalised": current.get("employer_normalised"),
            "org_type": current.get("org_type"),
            "region": current.get("region"),
            "working_pattern_normalised": current.get("working_pattern_normalised"),
            "contract_type": current.get("contract_type"),
            "pillar": current.get("pillar") or "unclassified",
            "pillar_secondary": current.get("pillar_secondary"),
            "taxonomy_version": current.get("taxonomy_version"),
            "keyword_version": current.get("keyword_version"),
            "collection_method": current.get("collection_method") or MISSING,
            "posted_date": current.get("posted_date"),
            "advertised_duration_days": current.get("advertised_duration_days"),
            "shorter_than_interval": current.get("shorter_than_interval"),
            "as_at_run_id": snap.get("run_id"),
            "as_at_seen_at": snap.get("seen_at"),
        })
    return rows


DATA_CSV_FIELDS = [
    "reference", "title", "pillar", "pillar_secondary", "band",
    "salary_min", "salary_max", "salary_period", "salary_text",
    "employer_normalised", "org_type", "region", "contract_type",
    "working_pattern_normalised", "status", "closing_date", "posted_date",
    "advertised_duration_days", "shorter_than_interval",
    "collection_method", "keyword_version", "taxonomy_version",
    "as_at_run_id", "as_at_seen_at",
]


def determine_status(runs_in_quarter: list[dict]) -> tuple[str, list[str]]:
    methods = sorted({r.get("collection_method") or MISSING for r in runs_in_quarter})
    if methods == ["weekly"]:
        return "headline", methods
    return "provisional", methods


def quarter_comparability_key(runs_in_quarter: list[dict]) -> str | None:
    keys = {r.get("comparability_key") for r in runs_in_quarter}
    return keys.pop() if len(keys) == 1 else None


def _chart_title(base: str, status: str) -> str:
    return f"{PROVISIONAL_PREFIX} — {base}" if status == "provisional" else base


def save_chart(fig, out_dir: Path, name: str) -> None:
    fig.savefig(out_dir / f"{name}.png", dpi=150, bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def chart_pillar_counts(rows: list[dict], out_dir: Path, status: str) -> None:
    counts = Counter(r["pillar"] for r in rows)
    labels = sorted(counts)
    values = [counts[l] for l in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, values, color="#1f6f63")
    ax.set_title(_chart_title("Vacancies by pillar", status))
    ax.set_ylabel("Count")
    plt.xticks(rotation=30, ha="right")
    save_chart(fig, out_dir, "pillar_counts")


def chart_band_distribution(rows: list[dict], out_dir: Path, status: str) -> None:
    counts = Counter(r["band"] or MISSING for r in rows)
    labels = sorted(counts)
    values = [counts[l] for l in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, values, color="#4a6fa5")
    ax.set_title(_chart_title("Band distribution", status))
    ax.set_ylabel("Count")
    plt.xticks(rotation=45, ha="right")
    save_chart(fig, out_dir, "band_distribution")


def chart_duration_by_pillar(rows: list[dict], out_dir: Path, status: str) -> None:
    by_pillar = defaultdict(list)
    for r in rows:
        if r["advertised_duration_days"] is not None:
            by_pillar[r["pillar"]].append(r["advertised_duration_days"])
    labels = sorted(by_pillar)
    fig, ax = plt.subplots(figsize=(7, 4))
    if labels:
        ax.boxplot([by_pillar[l] for l in labels])
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels)
    ax.set_title(_chart_title("Advertised duration by pillar (bias diagnostic)", status))
    ax.set_ylabel("Advertised duration (days)")
    plt.xticks(rotation=30, ha="right")
    save_chart(fig, out_dir, "advertised_duration_by_pillar")


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


def write_bias_diagnostics(rows: list[dict], out_dir: Path) -> dict:
    with_duration = [r for r in rows if r["advertised_duration_days"] is not None]
    with_flag = [r for r in rows if r["shorter_than_interval"] is not None]
    flagged = [r for r in with_flag if r["shorter_than_interval"]]

    duration_rows = []
    overall_median, q1, q3 = _median_iqr([r["advertised_duration_days"] for r in with_duration])
    duration_rows.append({"group": "overall", "n": len(with_duration),
                           "median_days": overall_median, "iqr_low": q1, "iqr_high": q3})
    by_pillar = defaultdict(list)
    for r in with_duration:
        by_pillar[r["pillar"]].append(r["advertised_duration_days"])
    for pillar, values in sorted(by_pillar.items()):
        median, q1, q3 = _median_iqr(values)
        duration_rows.append({"group": f"pillar={pillar}", "n": len(values),
                               "median_days": median, "iqr_low": q1, "iqr_high": q3})
    by_band = defaultdict(list)
    for r in with_duration:
        by_band[r["band"] or MISSING].append(r["advertised_duration_days"])
    for band, values in sorted(by_band.items()):
        median, q1, q3 = _median_iqr(values)
        duration_rows.append({"group": f"band={band}", "n": len(values),
                               "median_days": median, "iqr_low": q1, "iqr_high": q3})
    by_org = defaultdict(list)
    for r in with_duration:
        by_org[r["org_type"] or MISSING].append(r["advertised_duration_days"])
    for org, values in sorted(by_org.items()):
        median, q1, q3 = _median_iqr(values)
        duration_rows.append({"group": f"org_type={org}", "n": len(values),
                               "median_days": median, "iqr_low": q1, "iqr_high": q3})

    with open(out_dir / "bias_diagnostics.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["group", "n", "median_days", "iqr_low", "iqr_high"])
        writer.writeheader()
        writer.writerows(duration_rows)

    shorter_by_pillar = defaultdict(lambda: [0, 0])
    for r in with_flag:
        bucket = shorter_by_pillar[r["pillar"]]
        bucket[1] += 1
        if r["shorter_than_interval"]:
            bucket[0] += 1
    shorter_rows = [{"pillar": "overall", "flagged": len(flagged), "n": len(with_flag),
                      "share_pct": round(100 * len(flagged) / len(with_flag), 2) if with_flag else None}]
    for pillar, (n_flagged, n_total) in sorted(shorter_by_pillar.items()):
        shorter_rows.append({"pillar": pillar, "flagged": n_flagged, "n": n_total,
                              "share_pct": round(100 * n_flagged / n_total, 2) if n_total else None})
    with open(out_dir / "shorter_than_interval_share.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pillar", "flagged", "n", "share_pct"])
        writer.writeheader()
        writer.writerows(shorter_rows)

    return {
        "overall_shorter_than_interval_share_pct": shorter_rows[0]["share_pct"],
        "overall_shorter_than_interval_n": shorter_rows[0]["n"],
        "overall_median_advertised_duration_days": overall_median,
    }


def write_duration_weighted_estimate(rows: list[dict], mean_run_gap_days: float | None, out_dir: Path) -> None:
    path = out_dir / "duration_weighted_estimate.md"
    if not mean_run_gap_days or mean_run_gap_days <= 0:
        path.write_text(
            "# Duration-weighted volume estimate (sensitivity analysis)\n\n"
            "Not computed this quarter — no scrape interval could be determined "
            "(fewer than two runs recorded), which this estimator needs as its "
            "reference interval.\n",
            encoding="utf-8",
        )
        return

    with_duration = [r for r in rows if r["advertised_duration_days"] is not None]
    by_pillar = defaultdict(float)
    overall_weight = 0.0
    for r in with_duration:
        d = max(r["advertised_duration_days"], 1)
        weight = mean_run_gap_days / min(d, mean_run_gap_days)
        by_pillar[r["pillar"]] += weight
        overall_weight += weight

    lines = [
        "# Duration-weighted volume estimate (sensitivity analysis)",
        "",
        "**This is an estimate, not a headline figure.** It applies an inverse-"
        "probability (Horvitz-Thompson style) correction for length-biased "
        "sampling: each captured advert is weighted by "
        f"`mean_run_gap_days / min(advertised_duration_days, mean_run_gap_days)`, "
        f"using this quarter's mean scrape interval of {mean_run_gap_days:.1f} days "
        "as the reference. Short-lived adverts get a bigger weight, since they "
        "were less likely to be caught at all. This corrects for the *direction* "
        "of the bias described in methodology.md, not its exact magnitude — "
        "treat it as a plausible range indicator, not a precise count.",
        "",
        f"- Raw captured count: {len(with_duration)}",
        f"- Duration-weighted estimate: {overall_weight:.0f}",
        "",
        "| Pillar | Raw count | Weighted estimate |",
        "|---|---|---|",
    ]
    raw_by_pillar = Counter(r["pillar"] for r in with_duration)
    for pillar in sorted(by_pillar):
        lines.append(f"| {pillar} | {raw_by_pillar[pillar]} | {by_pillar[pillar]:.0f} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pillar_counts(rows: list[dict], out_dir: Path) -> dict:
    by_method_pillar = Counter((r["collection_method"], r["pillar"]) for r in rows)
    pillar_totals = Counter(r["pillar"] for r in rows)

    out_rows = [
        {"pillar": pillar, "collection_method": method, "count": count}
        for (method, pillar), count in sorted(by_method_pillar.items())
    ]
    out_rows += [
        {"pillar": pillar, "collection_method": "ALL", "count": count}
        for pillar, count in sorted(pillar_totals.items())
    ]
    with open(out_dir / "pillar_counts.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pillar", "collection_method", "count"])
        writer.writeheader()
        writer.writerows(out_rows)
    return dict(pillar_totals)


def band_distribution(rows: list[dict]) -> list[tuple[str, int]]:
    counts = Counter(r["band"] or MISSING for r in rows)
    return sorted(counts.items(), key=lambda kv: -kv[1])


REAL_PILLARS = ["foundation", "lifeblood", "compass", "bedside", "future"]


def compute_bounds_check(label: str, quarter_start: date, quarter_end: date,
                          total_listings: int, pillar_totals: dict,
                          runs_in_quarter: list[dict]) -> dict:
    reasons = []

    zero_pillars = [p for p in REAL_PILLARS if pillar_totals.get(p, 0) == 0]
    if zero_pillars:
        reasons.append(f"Zero vacancies in pillar(s): {', '.join(zero_pillars)}")

    fy_year, q = parse_quarter_label(label)
    prev_fy_year, prev_q = previous_quarter(fy_year, q)
    prev_label = quarter_label(prev_fy_year, prev_q)
    prev_metrics_path = REPORTS_DIR / prev_label / "metrics.json"
    pct_change = None
    if prev_metrics_path.exists():
        prev_metrics = json.loads(prev_metrics_path.read_text(encoding="utf-8"))
        prev_total = prev_metrics.get("figures", {}).get("total_listings", {}).get("value")
        if prev_total:
            pct_change = round(100 * (total_listings - prev_total) / prev_total, 1)
            if abs(pct_change) > 50:
                reasons.append(
                    f"Total listings changed {pct_change:+.1f}% vs {prev_label} "
                    f"({prev_total} -> {total_listings})"
                )

    quarter_days = (quarter_end - quarter_start).days + 1
    expected_min_runs = int((quarter_days // 7) * 0.8)
    runs_below_expected = len(runs_in_quarter) < expected_min_runs
    if runs_below_expected:
        reasons.append(
            f"Only {len(runs_in_quarter)} scrape run(s) this quarter, expected at least {expected_min_runs}"
        )

    return {
        "zero_pillars": zero_pillars,
        "total_listings_pct_change_vs_previous": pct_change,
        "scrape_runs_expected_min": expected_min_runs,
        "scrape_runs_below_expected": runs_below_expected,
        "out_of_bounds": bool(reasons),
        "reasons": reasons,
    }


def write_pr_summary(path: Path, label: str, human_title: str, status: str,
                      total_listings: int, pillar_totals: dict, band_dist: list[tuple[str, int]],
                      median_advertised_duration: float | None, unclassified_share_pct: float | None,
                      run_count: int, bounds_check: dict) -> None:
    lines = [
        f"# {human_title} data pack ({label})",
        "",
        f"**Status: {status.upper()}**",
        "",
        "| Figure | Value |",
        "|---|---|",
        f"| Total vacancies posted | {total_listings} |",
        f"| Unclassified share | {unclassified_share_pct:.1f}% |" if unclassified_share_pct is not None else "| Unclassified share | n/a |",
        f"| Median advertised duration | {median_advertised_duration:.0f} days |" if median_advertised_duration is not None else "| Median advertised duration | n/a |",
        f"| Scrape runs this quarter | {run_count} |",
        "",
        "**Count per pillar**",
        "",
        "| Pillar | Count |",
        "|---|---|",
    ]
    for pillar, count in sorted(pillar_totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {pillar} | {count} |")
    lines += ["", "**Band distribution**", "", "| Band | Count |", "|---|---|"]
    for band, count in band_dist:
        lines.append(f"| {band} | {count} |")
    if bounds_check["out_of_bounds"]:
        lines += ["", "**⚠ Figures outside expected bounds:**", ""]
        for reason in bounds_check["reasons"]:
            lines.append(f"- {reason}")
    lines += ["", f"Full pack: `reports/{label}/`"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compute_qoq_delta(this_label: str, this_comparability_key: str | None,
                       this_figures: dict) -> dict:
    fy_year, q = parse_quarter_label(this_label)
    prev_fy_year, prev_q = previous_quarter(fy_year, q)
    prev_label = quarter_label(prev_fy_year, prev_q)
    prev_metrics_path = REPORTS_DIR / prev_label / "metrics.json"

    if not prev_metrics_path.exists():
        return {"previous_quarter": prev_label, "comparable": False,
                "reason_if_suppressed": f"No previous quarter pack found at reports/{prev_label}/ — nothing to compare against.",
                "deltas": None}

    prev_metrics = json.loads(prev_metrics_path.read_text(encoding="utf-8"))
    prev_key = prev_metrics.get("comparability_key")

    if this_comparability_key is None or prev_key is None:
        return {"previous_quarter": prev_label, "comparable": False,
                "reason_if_suppressed": "One or both quarters used a mixed methodology (no single comparability_key) — not comparable.",
                "deltas": None}

    if this_comparability_key != prev_key:
        return {"previous_quarter": prev_label, "comparable": False,
                "reason_if_suppressed": f"comparability_key changed between quarters ({prev_key} -> {this_comparability_key}) — methodology not comparable.",
                "deltas": None}

    prev_figures = prev_metrics.get("figures", {})
    deltas = {}
    for name in ("total_listings", "unclassified_share_pct"):
        prev_val = prev_figures.get(name, {}).get("value")
        this_val = this_figures.get(name, {}).get("value")
        if prev_val is not None and this_val is not None:
            deltas[name] = this_val - prev_val
    return {"previous_quarter": prev_label, "comparable": True,
            "reason_if_suppressed": None, "deltas": deltas}


def write_methodology(out_dir: Path, label: str, quarter_start: date, quarter_end: date,
                       runs_in_quarter: list[dict], status: str, methods_used: list[str],
                       total_listings: int, unclassified_share_pct: float | None,
                       bias_summary: dict) -> None:
    keyword_versions = sorted({r.get("keyword_version") or MISSING for r in runs_in_quarter})
    taxonomy_versions = sorted({r.get("taxonomy_version") or MISSING for r in runs_in_quarter})
    gaps = [r["days_since_previous_run"] for r in runs_in_quarter if r.get("days_since_previous_run") is not None]
    failed = [r for r in runs_in_quarter if r.get("errors")]

    lines = [
        f"# Methodology — {label}",
        "",
        f"- **Date range:** {quarter_start.isoformat()} to {quarter_end.isoformat()} (NHS financial quarter)",
        f"- **Status:** {status}",
        f"- **Collection method(s) used:** {', '.join(methods_used)}",
        f"- **Keyword version(s):** {', '.join(keyword_versions)}",
        f"- **Taxonomy version(s):** {', '.join(taxonomy_versions)}",
        f"- **Scrape runs in this quarter:** {len(runs_in_quarter)}",
        f"- **Mean days between runs:** {statistics.mean(gaps):.1f}" if gaps else "- **Mean days between runs:** n/a (fewer than 2 runs)",
        f"- **Max days between runs:** {max(gaps)}" if gaps else "- **Max days between runs:** n/a",
        f"- **Failed or skipped runs:** {len(failed)}",
    ]
    for r in failed:
        lines.append(f"  - `{r['run_id']}` ({r['started_at']}): {r['errors']}")
    lines += [
        f"- **Total listings in this cut:** {total_listings}",
        f"- **Unclassified share:** {unclassified_share_pct:.1f}%" if unclassified_share_pct is not None else "- **Unclassified share:** n/a",
        "",
    ]
    if status == "provisional":
        lines += [PROVISIONAL_STANDING_NOTE, ""]
    lines += [
        "## Length-biased sampling",
        "",
        LENGTH_BIAS_PARAGRAPH,
        "",
        "## Bias diagnostics this quarter",
        "",
        f"- Adverts flagged `shorter_than_interval` (only caught by luck): "
        f"{bias_summary['overall_shorter_than_interval_n']} observed, "
        f"{bias_summary['overall_shorter_than_interval_share_pct']}% flagged "
        f"(see bias_diagnostics.csv and shorter_than_interval_share.csv for the full breakdown by pillar/band/org type).",
        "",
        "## Fields reconstructed for this cut",
        "",
        "title, salary_text, closing_date and status are as-at the quarter end "
        "(from vacancy_snapshots). band and salary_min/max/period are re-derived "
        "from that as-at text. employer_normalised, org_type, region, "
        "working_pattern_normalised, contract_type, pillar and taxonomy_version "
        "are taken from the current vacancies row.",
    ]
    (out_dir / "methodology.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_findings(out_dir: Path, label: str, status: str, total_listings: int,
                    pillar_totals: dict, unclassified_share_pct: float | None,
                    qoq: dict) -> None:
    lines = [f"# Findings — {label}", ""]
    if status == "provisional":
        lines += [PROVISIONAL_STANDING_NOTE, ""]
    lines += [
        "## Headline numbers",
        "",
        f"- Total listings in this cut: **{total_listings}**",
        f"- Unclassified share: **{unclassified_share_pct:.1f}%**" if unclassified_share_pct is not None else "- Unclassified share: n/a",
        "",
        "| Pillar | Count |",
        "|---|---|",
    ]
    for pillar, count in sorted(pillar_totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {pillar} | {count} |")
    lines += ["", "## Quarter-on-quarter", ""]
    if qoq["comparable"]:
        lines.append(f"Compared against {qoq['previous_quarter']}:")
        for name, delta in qoq["deltas"].items():
            lines.append(f"- {name}: {delta:+.1f}")
    else:
        lines.append(f"Not shown — {qoq['reason_if_suppressed']}")
    lines += [
        "",
        "## Commentary",
        "",
        "TODO",
        "",
        "## What stands out",
        "",
        "TODO",
        "",
        "## Caveats for this quarter specifically",
        "",
        "TODO",
    ]
    (out_dir / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate(label: str) -> None:
    fy_year, q = parse_quarter_label(label)
    quarter_start, quarter_end = quarter_bounds(fy_year, q)

    out_dir = REPORTS_DIR / label
    if out_dir.exists():
        print(f"reports/{label}/ already exists — published quarter folders are never "
              f"regenerated. If this is a correction, create a new folder "
              f"(e.g. reports/{label}-erratum-1/) with its own erratum note instead.")
        sys.exit(1)

    creds = _load_supabase_credentials()
    if creds is None:
        print("No Supabase credentials found (env vars or supabase_config.json).")
        sys.exit(1)
    url, key = creds
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    print(f"Building quarterly pack for {label} ({quarter_start} to {quarter_end})...")
    print("Fetching data...")
    vacancies = _fetch_all(url, key, "vacancies?select=*", order="reference")
    snapshots = _fetch_all(
        url, key,
        "vacancy_snapshots?select=job_reference,run_id,seen_at,status,closing_date,salary,title",
        order="seen_at",
        params={"seen_at": f"lte.{quarter_end.isoformat()}T23:59:59"},
    )
    all_runs = _fetch_all(url, key, "scrape_runs?select=*", order="started_at")
    runs_in_quarter = [
        r for r in all_runs
        if quarter_start <= datetime.fromisoformat(r["started_at"]).date() <= quarter_end
    ]
    print(f"  {len(vacancies)} vacancies, {len(snapshots)} qualifying snapshots, "
          f"{len(runs_in_quarter)} scrape runs in quarter")

    rows = build_point_in_time_cut(vacancies, snapshots, quarter_end)
    if not rows:
        print("No vacancies had a qualifying snapshot as at this quarter end — "
              "nothing to pack.")
        sys.exit(1)

    status, methods_used = determine_status(runs_in_quarter)
    comparability_key = quarter_comparability_key(runs_in_quarter)
    comparable = status == "headline"

    out_dir.mkdir(parents=True)

    with open(out_dir / "data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DATA_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote data.csv ({len(rows)} rows)")

    pillar_totals = write_pillar_counts(rows, out_dir)
    print("  wrote pillar_counts.csv")

    total_listings = len(rows)
    unclassified = pillar_totals.get("unclassified", 0)
    unclassified_share_pct = round(100 * unclassified / total_listings, 2) if total_listings else None

    bias_summary = write_bias_diagnostics(rows, out_dir)
    print("  wrote bias_diagnostics.csv, shorter_than_interval_share.csv")

    gaps = [r["days_since_previous_run"] for r in runs_in_quarter if r.get("days_since_previous_run") is not None]
    mean_gap = statistics.mean(gaps) if gaps else None
    write_duration_weighted_estimate(rows, mean_gap, out_dir)
    print("  wrote duration_weighted_estimate.md")

    chart_pillar_counts(rows, out_dir, status)
    chart_band_distribution(rows, out_dir, status)
    chart_duration_by_pillar(rows, out_dir, status)
    print("  wrote charts (PNG + SVG)")

    figures = {
        "total_listings": {"value": total_listings, "comparable": comparable},
        "unclassified_share_pct": {"value": unclassified_share_pct, "comparable": comparable},
        **{
            f"pillar_count_{pillar}": {"value": count, "comparable": comparable}
            for pillar, count in pillar_totals.items()
        },
    }
    qoq = compute_qoq_delta(label, comparability_key, figures)
    bounds_check = compute_bounds_check(label, quarter_start, quarter_end,
                                         total_listings, pillar_totals, runs_in_quarter)

    metrics = {
        "quarter": label,
        "quarter_start": quarter_start.isoformat(),
        "quarter_end": quarter_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "collection_methods_used": methods_used,
        "comparability_key": comparability_key,
        "figures": figures,
        "bias_diagnostics": bias_summary,
        "scrape_run_summary": {
            "count": len(runs_in_quarter),
            "mean_days_between_runs": round(mean_gap, 1) if mean_gap is not None else None,
            "max_days_between_runs": max(gaps) if gaps else None,
            "failed_or_skipped_runs": [
                {"run_id": r["run_id"], "started_at": r["started_at"], "errors": r["errors"]}
                for r in runs_in_quarter if r.get("errors")
            ],
        },
        "qoq_delta": qoq,
        "bounds_check": bounds_check,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("  wrote metrics.json")

    write_methodology(out_dir, label, quarter_start, quarter_end, runs_in_quarter,
                       status, methods_used, total_listings, unclassified_share_pct, bias_summary)
    write_findings(out_dir, label, status, total_listings, pillar_totals, unclassified_share_pct, qoq)
    print("  wrote methodology.md, findings.md")

    human_title = human_quarter_title(q, quarter_start)
    write_pr_summary(REPORTS_DIR.parent / "pr_summary.md", label, human_title, status,
                      total_listings, pillar_totals, band_distribution(rows),
                      bias_summary["overall_median_advertised_duration_days"],
                      unclassified_share_pct, len(runs_in_quarter), bounds_check)
    print("  wrote pr_summary.md")

    if bounds_check["out_of_bounds"]:
        print("\nFigures outside expected bounds:")
        for reason in bounds_check["reasons"]:
            print(f"  - {reason}")

    print(f"\nDone. Pack for {label} ({status}) written to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one immutable quarterly data pack.")
    parser.add_argument("--quarter", help="FY quarter label, e.g. 2025-Q4. Defaults to the "
                                          "most recently completed quarter as of today.")
    args = parser.parse_args()

    if args.quarter:
        label = args.quarter
    else:
        fy_year, q, _, _ = most_recently_completed_quarter(datetime.now(timezone.utc).date())
        label = quarter_label(fy_year, q)

    generate(label)


if __name__ == "__main__":
    main()
