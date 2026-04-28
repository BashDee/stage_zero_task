-- Unit 3: User Service - Users Table
-- Stores GitHub-authenticated users with profile data and status tracking
create extension if not exists "pgcrypto";

create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),
    github_id integer not null unique,
    username varchar not null,
    email varchar,
    avatar_url varchar,
    role varchar not null default 'analyst' check (role in ('analyst', 'admin')),
    is_active boolean not null default true,
    last_login_at timestamp without time zone,
    created_at timestamp without time zone not null default (now() at time zone 'utc')
);

create index if not exists idx_users_github_id on public.users (github_id);
create index if not exists idx_users_is_active on public.users (is_active);
create index if not exists idx_users_created_at on public.users (created_at);
create index if not exists idx_users_last_login_at on public.users (last_login_at);
