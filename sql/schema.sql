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

-- GHL calls that failed, kept with the payload so scripts/replay_failed.py can run them again.
create table if not exists failed_events (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    step text not null,
    payload jsonb not null,
    error text not null,
    replayed_at timestamptz
);

-- One row per booked visit. The unique key stops two bookings in the same slot.
create table if not exists bookings (
    event_id text primary key,
    calendar_id text not null,
    contact_id text not null,
    conversation_id text,
    start_time timestamptz not null,
    end_time timestamptz not null,
    created_at timestamptz not null default now(),
    unique (calendar_id, start_time)
);

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
