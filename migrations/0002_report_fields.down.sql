drop index if exists vacancies_org_type_idx;
drop index if exists vacancies_status_idx;

alter table public.vacancies
  drop column if exists scrape_run_id,
  drop column if exists keyword_version,
  drop column if exists status,
  drop column if exists region,
  drop column if exists org_type,
  drop column if exists employer_normalised,
  drop column if exists working_pattern_normalised,
  drop column if exists salary_period,
  drop column if exists salary_max,
  drop column if exists salary_min,
  drop column if exists band;

alter table public.vacancies
  rename column posted_date to date_posted_parsed;
