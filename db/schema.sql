-- Stage 2 canonical profiles schema.
create extension if not exists "pgcrypto";

create table if not exists public.profiles (
    id uuid primary key,
    name varchar not null unique,
    gender varchar not null check (gender in ('male', 'female')),
    gender_probability double precision not null,
    age integer not null,
    age_group varchar not null check (age_group in ('child', 'teenager', 'adult', 'senior')),
    country_id varchar(2) not null,
    country_name varchar not null,
    country_probability double precision not null,
    created_at timestamp without time zone not null default (now() at time zone 'utc')
);

create index if not exists idx_profiles_gender on public.profiles (gender);
create index if not exists idx_profiles_age_group on public.profiles (age_group);
create index if not exists idx_profiles_country_id on public.profiles (country_id);
create index if not exists idx_profiles_age on public.profiles (age);
create index if not exists idx_profiles_created_at on public.profiles (created_at);
create index if not exists idx_profiles_gender_probability on public.profiles (gender_probability);
create index if not exists idx_profiles_country_probability on public.profiles (country_probability);
