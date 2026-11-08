-- Safe to run more than once.
-- Unqualified names on purpose: the receptionist role's search_path starts with its own schema,
-- because the Supabase database is shared with the other portfolio projects.
create extension if not exists vector;

create table if not exists kb_chunks (
    id text primary key,
    article_id text not null,
    title text not null,
    content text not null,
    embedding vector(384) not null
);

create index if not exists kb_chunks_embedding_idx
    on kb_chunks using hnsw (embedding vector_cosine_ops);

-- One row per inbound message. The primary key is the idempotency check.
create table if not exists message_log (
    message_id text primary key,
    conversation_id text not null,
    contact_id text not null,
    received_at timestamptz not null default now(),
    body text not null,
    intent text,
    tier text,
    score int,
    next_action text,
    reply text,
    articles text[],
    model text,
    used_fallback boolean not null default false,
    error text,
    input_tokens int,
    output_tokens int,
    cost_usd numeric(10, 6),
    latency_ms int
);

-- processing -> done, or failed (the error workflow sets it, and the replay can claim it again).
alter table message_log add column if not exists status text not null default 'processing';

-- GHL calls that failed, kept with the payload so scripts/replay_failed.py can run them again.
create table if not exists failed_events (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    step text not null,
    payload jsonb not null,
    error text not null,
    replayed_at timestamptz
);

-- One row per visit. The slot is reserved here before the GHL appointment is created, so two
-- conversations can never book the same time; event_id is filled in once GHL confirms.
create table if not exists bookings (
    calendar_id text not null,
    start_time timestamptz not null,
    end_time timestamptz not null,
    contact_id text not null,
    conversation_id text,
    message_id text,
    event_id text,
    created_at timestamptz not null default now(),
    unique (calendar_id, start_time)
);

-- Upgrades for a database created by the first version of this file.
alter table bookings drop constraint if exists bookings_pkey;
alter table bookings alter column event_id drop not null;
alter table bookings add column if not exists message_id text;
alter table message_log add column if not exists reply_sent_at timestamptz;

-- search_path is pinned so the vector type and the <=> operator resolve the same way for every caller.
create or replace function match_chunks(query_embedding vector(384), match_count int)
returns table (id text, article_id text, title text, content text, similarity float)
language sql
stable
set search_path = receptionist, public, extensions
as $$
    select c.id, c.article_id, c.title, c.content, 1 - (c.embedding <=> query_embedding)
    from kb_chunks c
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
