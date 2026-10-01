# Methodology — 2026-Q2

- **Date range:** 2026-07-01 to 2026-09-30 (NHS financial quarter)
- **Status:** headline
- **Collection method(s) used:** weekly
- **Keyword version(s):** v1
- **Taxonomy version(s):** 0.6.0
- **Scrape runs in this quarter:** 6
- **Mean days between runs:** 2.8
- **Max days between runs:** 7
- **Failed or skipped runs:** 0
- **Total listings in this cut:** 878
- **Unclassified share:** 65.4%

## Length-biased sampling

This dataset is built from periodic snapshots of NHS Jobs search results, not a continuous feed. An advert that is posted and closes entirely between two scrape runs is never observed at all. Because of this, the probability of an advert being captured rises with how long it stays open — a role advertised for six weeks is far more likely to be caught by at least one scrape than one advertised for four days. This is length-biased sampling: it does not affect the classification of captured adverts, but it means total counts and pillar shares in this pack systematically understate short-lived postings relative to long-running ones. A pillar or role type where postings tend to be brief will therefore appear smaller here than its true share of the market, and vice versa for pillars where postings typically run long. See the bias diagnostics section for how much of this quarter's captured data looks like it was only caught by luck.

## Bias diagnostics this quarter

- Adverts flagged `shorter_than_interval` (only caught by luck): 453 observed, 3.75% flagged (see bias_diagnostics.csv and shorter_than_interval_share.csv for the full breakdown by pillar/band/org type).

## Fields reconstructed for this cut

title, salary_text, closing_date and status are as-at the quarter end (from vacancy_snapshots). band and salary_min/max/period are re-derived from that as-at text. employer_normalised, org_type, region, working_pattern_normalised, contract_type, pillar and taxonomy_version are taken from the current vacancies row.
