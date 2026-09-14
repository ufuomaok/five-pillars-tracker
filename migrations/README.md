# Migrations

Numbered, paired `.up.sql` / `.down.sql` files, applied in order via
Supabase SQL Editor (no CI/automation runs these — there's no direct
Postgres connection available to this project, only the REST API).
Never edit an already-applied migration file; add a new one instead.
One-off Python backfill scripts that accompany a migration are named
`NNNN_<description>.py` alongside it.

## Pillar taxonomy versioning

`vacancies.pillar` / `pillar_secondary` / `pillar_confidence` /
`taxonomy_version` always reflect classification under the taxonomy
version currently pinned in `requirements.txt`. They get overwritten
on every scrape, same as `status` — that's fine for the *current*
taxonomy, but classification history would be lost the moment the
taxonomy itself changes, unless it's archived first.

**When you deliberately revise the taxonomy (a real rule change you've
decided to adopt — not just "main moved"), before running the scraper
again:**

1. Write a migration that adds archive columns for the *outgoing*
   version and backfills them from the current live columns, e.g. for
   a move away from `0.6.0`:
   ```sql
   alter table public.vacancies
     add column if not exists pillar_0_6_0 text,
     add column if not exists pillar_secondary_0_6_0 text,
     add column if not exists pillar_confidence_0_6_0 text;

   update public.vacancies
     set pillar_0_6_0 = pillar,
         pillar_secondary_0_6_0 = pillar_secondary,
         pillar_confidence_0_6_0 = pillar_confidence
     where taxonomy_version = '0.6.0';
   ```
   Run this — and confirm it's applied — **before** the next scrape,
   while `pillar` still holds the outgoing version's classifications.
   This is the one legitimate `UPDATE` in the whole migrations
   folder: it's archiving history, not touching `scrape_runs` or
   `vacancy_snapshots`, which stay strictly append-only.

2. Bump the pinned commit (or tag, once the taxonomy repo has one) in
   `requirements.txt`.

3. Run the scraper. From this point, `pillar`/`pillar_secondary`/
   `pillar_confidence`/`taxonomy_version` reflect the new taxonomy;
   `pillar_0_6_0` etc. stay frozen as the old version's audit trail.

**Reclassifying the full historical corpus** (e.g. at year end, per
the project's stated methodology) under the new taxonomy is a separate,
explicit backfill step — re-run the new classifier over every stored
`title` and write fresh `pillar`/`pillar_secondary`/`pillar_confidence`/
`taxonomy_version`, the same way Stage 7 backfills other fields. Do
this only after step 1 has archived the outgoing version, and flag the
backfilled rows the same way Stage 7 asks for band/salary/employer.
