alter table public.vacancies
  add column if not exists closing_date_parsed date,
  add column if not exists date_posted_parsed date;

create index if not exists vacancies_closing_date_parsed_idx
  on public.vacancies (closing_date_parsed);
