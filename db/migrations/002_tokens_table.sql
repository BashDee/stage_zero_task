-- Token service: JTI tracking and refresh token revocation
create table if not exists public.tokens (
    jti varchar not null primary key,
    github_id integer not null,
    token_type varchar not null check (token_type in ('access', 'refresh')),
    expires_at bigint not null,
    is_revoked boolean not null default false,
    created_at timestamp without time zone not null default (now() at time zone 'utc'),
    used_at timestamp without time zone default null
);

create index if not exists idx_tokens_github_id on public.tokens (github_id);
create index if not exists idx_tokens_expires_at on public.tokens (expires_at);
create index if not exists idx_tokens_is_revoked on public.tokens (is_revoked);
