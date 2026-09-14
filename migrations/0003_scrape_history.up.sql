create table if not exists public.scrape_runs (
  run_id                text primary key,
  started_at            timestamptz not null,
  finished_at           timestamptz not null,
  keyword_version       text,
  taxonomy_version      text,
  collection_method     text not null,
  days_since_previous_run integer,
  listings_found        integer not null,
  rows_new              integer not null,
  rows_updated          integer not null,
  rows_unclassified     integer not null,
  errors                text,
  comparability_key     text generated always as (
    coalesce(keyword_version, '?') || '|' ||
    coalesce(taxonomy_version, '?') || '|' ||
    coalesce(collection_method, '?')
  ) stored
);

create table if not exists public.vacancy_snapshots (
  job_reference  text not null references public.vacancies(reference),
  run_id         text not null references public.scrape_runs(run_id),
  seen_at        timestamptz not null,
  status         text,
  closing_date   date,
  salary         text,
  title          text,
  primary key (job_reference, run_id)
);

create index if not exists vacancy_snapshots_job_reference_idx
  on public.vacancy_snapshots (job_reference);

alter table public.vacancies
  add column if not exists collection_method text,
  add column if not exists advertised_duration_days integer,
  add column if not exists shorter_than_interval boolean,
  add column if not exists current_closing_date date,
  add column if not exists current_duration_days integer,
  add column if not exists extension_count integer,
  add column if not exists was_extended boolean,
  add column if not exists observed_duration_days integer,
  add column if not exists times_observed integer,
  add column if not exists readvert_key text;

create index if not exists vacancies_readvert_key_idx on public.vacancies (readvert_key);
create index if not exists vacancies_scrape_run_id_idx on public.vacancies (scrape_run_id);
