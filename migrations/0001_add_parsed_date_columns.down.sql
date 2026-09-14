drop index if exists vacancies_closing_date_parsed_idx;

alter table public.vacancies
  drop column if exists closing_date_parsed,
  drop column if exists date_posted_parsed;
