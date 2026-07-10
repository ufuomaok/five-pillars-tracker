# Five Pillars Digital Health Vacancy Tracker

**Live at [fivepillarsvacancytracker.ufuomao.com](https://fivepillarsvacancytracker.ufuomao.com)**

The first tool to turn scattered, inconsistently-titled NHS digital health
job postings into one organised view of the market. Open vacancies from
public NHS listings are classified against the
[Five Pillars of Digital Health](https://www.ufuomao.com/five-pillars-in-digital-health)
framework — **Foundation** (infrastructure), **Lifeblood** (data),
**Compass** (leadership & strategy), **Bedside** (clinical practice &
informatics), **Future** (education & training) — and presented as a
searchable, filterable public dashboard, refreshed monthly.

Built and maintained by [Ufuoma Okpeahior](https://ufuomao.com), creator
of the Five Pillars framework.

## How it works

```
jobs.nhs.uk public search
        │  scraper.py — respectful scraping: metadata only,
        │  low frequency, retries, ~20s between requests
        ▼
five-pillars-taxonomy          ◄── separate open-source package:
        │  keyword-to-pillar        github.com/ufuomaok/five-pillars-taxonomy
        │  classification
        ▼
Supabase (Postgres)
        │  public read-only REST API
        │  (row-level security: anonymous users can only read)
        ▼
index.html — static dashboard
        Three.js hero (pillar heights = live vacancy counts)
        + searchable/filterable vacancy table
```

- **`scraper.py`** — fetches structured vacancy metadata (title, employer,
  location, salary, dates, contract type) from jobs.nhs.uk search results
  across a fixed set of digital health search terms, deduplicates by job
  reference, classifies each title by pillar, and upserts into Supabase.
  Jobs are never duplicated across runs: re-scraping refreshes a
  vacancy's `last_seen` while preserving its original `first_seen`.
- **`upload_csv.py`** — utility to upload a previously scraped
  `vacancies.csv` without re-scraping.
- **`index.html`** — the whole frontend in one static file: an
  interactive Three.js visualisation of the five pillars (column heights
  driven by live vacancy counts, click to filter) above a standard,
  accessible HTML dashboard. Queries Supabase directly with a public
  read-only key; no backend server.

## Design decisions

**Metadata only, link out for everything else.** The tracker stores and
displays only structured listing metadata and links every role to its
original advert on the official NHS Jobs service, where applications are
made. Full advert text is never copied or republished.

**Respectful scraping.** Monthly refresh frequency, ~20 seconds between
requests, retry-with-backoff rather than hammering on failure, and an
honest user agent identifying the project.

**Unclassified means unclassified.** Roles that can't be confidently
assigned to a pillar are excluded from the dashboard rather than
force-fitted. NHS Jobs' search is deliberately fuzzy (a search for
"clinical systems" returns systemic psychotherapy roles), so the
classifier doubles as the quality filter — around half of raw scraped
results are correctly rejected this way.

**The taxonomy is a separate, reusable package.** All classification
logic and the keyword-to-pillar mapping live in
[`five-pillars-taxonomy`](https://github.com/ufuomaok/five-pillars-taxonomy)
— versioned, tested (90+ regression cases), and usable by anyone working
with digital health workforce data, independently of this tracker. Every
stored vacancy records the taxonomy version that classified it.

## Coverage & known limitations

- Source is the public NHS Jobs search (jobs.nhs.uk) only. Roles
  advertised solely on other platforms, or posted and closed between
  monthly refreshes, will be missed.
- Discovery uses a fixed set of search keywords; unusual role titles
  outside that vocabulary may not be found.
- Classification is keyword-based and imperfect by design; genuinely
  ambiguous titles are excluded rather than guessed.

These limitations are also stated on the site itself.

## Running it yourself

Requires Python 3.9+ and a Supabase project with a `vacancies` table
(schema in `docs/schema.sql` if present, or see the table definition in
project history).

```bash
git clone https://github.com/ufuomaok/five-pillars-tracker
cd five-pillars-tracker
python -m venv venv
venv\Scripts\Activate.ps1        # Windows (source venv/bin/activate on Mac/Linux)
pip install -r requirements.txt
```

Create `supabase_config.json` (never committed — see `.gitignore`):

```json
{
  "url": "https://YOUR-PROJECT.supabase.co",
  "service_key": "YOUR-SECRET-KEY"
}
```

Then:

```bash
python scraper.py
```

The frontend needs no build step: edit the `SUPABASE_URL` constant in
`index.html` and upload the file to any static host.

## Disclaimer

This is an independent project. It is not affiliated with, endorsed by,
or produced in partnership with the NHS, NHS England, NHS Business
Services Authority, or any NHS organisation. All vacancy data is drawn
from publicly available job listings.

## License

MIT — see `LICENSE`.