alter table public.vacancies
  rename column date_posted_parsed to posted_date;

alter table public.vacancies
  add column if not exists band text,
  add column if not exists salary_min numeric,
  add column if not exists salary_max numeric,
  add column if not exists salary_period text,
  add column if not exists working_pattern_normalised text,
  add column if not exists employer_normalised text,
  add column if not exists org_type text,
  add column if not exists region text,
  add column if not exists status text,
  add column if not exists keyword_version text,
  add column if not exists scrape_run_id text;

create index if not exists vacancies_status_idx on public.vacancies (status);
create index if not exists vacancies_org_type_idx on public.vacancies (org_type);
