drop index if exists vacancies_scrape_run_id_idx;
drop index if exists vacancies_readvert_key_idx;

alter table public.vacancies
  drop column if exists readvert_key,
  drop column if exists times_observed,
  drop column if exists observed_duration_days,
  drop column if exists was_extended,
  drop column if exists extension_count,
  drop column if exists current_duration_days,
  drop column if exists current_closing_date,
  drop column if exists shorter_than_interval,
  drop column if exists advertised_duration_days,
  drop column if exists collection_method;

drop table if exists public.vacancy_snapshots;
drop table if exists public.scrape_runs;
