-- Align existing Stage 1 table with Stage 2 requirements.
alter table if exists public.profiles
    add column if not exists country_name varchar;

-- Backfill and normalize values before constraints.
update public.profiles
set name = lower(trim(name))
where name is not null;

update public.profiles
set gender = lower(trim(gender))
where gender is not null;

update public.profiles
set age_group = lower(trim(age_group))
where age_group is not null;

update public.profiles
set country_id = upper(trim(country_id))
where country_id is not null;

update public.profiles
set country_name = case
    when country_name is null or trim(country_name) = '' then upper(trim(country_id))
    else country_name
end;

alter table if exists public.profiles
    alter column name type varchar,
    alter column name set not null,
    alter column gender type varchar,
    alter column gender set not null,
    alter column age type integer,
    alter column age set not null,
    alter column age_group type varchar,
    alter column age_group set not null,
    alter column country_id type varchar(2),
    alter column country_id set not null,
    alter column country_name type varchar,
    alter column country_name set not null,
    alter column created_at set default (now() at time zone 'utc');

alter table if exists public.profiles
    drop constraint if exists profiles_gender_check;

alter table if exists public.profiles
    add constraint profiles_gender_check check (gender in ('male', 'female'));

alter table if exists public.profiles
    drop constraint if exists profiles_age_group_check;

alter table if exists public.profiles
    add constraint profiles_age_group_check check (age_group in ('child', 'teenager', 'adult', 'senior'));

alter table if exists public.profiles
    add constraint profiles_name_unique unique (name);

create index if not exists idx_profiles_gender on public.profiles (gender);
create index if not exists idx_profiles_age_group on public.profiles (age_group);
create index if not exists idx_profiles_country_id on public.profiles (country_id);
create index if not exists idx_profiles_age on public.profiles (age);
create index if not exists idx_profiles_created_at on public.profiles (created_at);
create index if not exists idx_profiles_gender_probability on public.profiles (gender_probability);
create index if not exists idx_profiles_country_probability on public.profiles (country_probability);

alter table if exists public.profiles drop column if exists sample_size;
alter table if exists public.profiles drop column if exists normalized_name;
alter table if exists public.profiles drop column if exists normalized_gender;
alter table if exists public.profiles drop column if exists normalized_age_group;
alter table if exists public.profiles drop column if exists normalized_country_id;
