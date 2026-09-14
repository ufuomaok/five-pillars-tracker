alter table public.vacancies
  add column if not exists backfilled boolean;
