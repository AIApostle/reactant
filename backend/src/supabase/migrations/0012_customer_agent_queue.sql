create table public.customer_agent_runs (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    source_type text not null check (source_type in ('customer_message', 'telegram_update')),
    customer_message_id uuid,
    telegram_channel_id uuid,
    telegram_provider_event_id text,
    telegram_payload_ciphertext text,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'succeeded', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    lease_token uuid,
    lease_expires_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz not null default now(),
    error_code text,
    created_at timestamptz not null default now(),
    unique (business_id, id),
    unique (business_id, customer_message_id),
    unique (business_id, telegram_channel_id, telegram_provider_event_id),
    foreign key (business_id, customer_message_id)
        references public.customer_messages (business_id, id) on delete cascade,
    foreign key (business_id, telegram_channel_id)
        references public.integrations (business_id, id) on delete cascade,
    check (
        (
            source_type = 'customer_message'
            and customer_message_id is not null
            and telegram_channel_id is null
            and telegram_provider_event_id is null
            and telegram_payload_ciphertext is null
        )
        or (
            source_type = 'telegram_update'
            and customer_message_id is null
            and telegram_channel_id is not null
            and telegram_provider_event_id is not null
            and telegram_payload_ciphertext is not null
        )
    )
);

create index customer_agent_runs_queue_idx
    on public.customer_agent_runs (created_at)
    where status in ('queued', 'running');

alter table public.customer_agent_runs enable row level security;
revoke all on public.customer_agent_runs from anon, authenticated;
grant all on public.customer_agent_runs to service_role;

create or replace function public.enqueue_website_customer_agent_run()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.sender_type = 'customer'
       and new.visibility = 'customer'
       and exists (
           select 1
           from public.conversations
           where business_id = new.business_id
             and id = new.conversation_id
             and channel = 'website'
       ) then
        insert into public.customer_agent_runs (
            business_id,
            source_type,
            customer_message_id
        )
        values (new.business_id, 'customer_message', new.id)
        on conflict (business_id, customer_message_id) do nothing;
    end if;
    return new;
end;
$$;

create trigger customer_messages_enqueue_agent_run
after insert on public.customer_messages
for each row
execute function public.enqueue_website_customer_agent_run();

create or replace function public.claim_customer_agent_run()
returns setof public.customer_agent_runs
language plpgsql
security definer
set search_path = ''
as $$
declare
    claimed_run public.customer_agent_runs;
begin
    update public.customer_agent_runs
    set status = 'failed',
        lease_token = null,
        lease_expires_at = null,
        completed_at = now(),
        updated_at = now(),
        error_code = 'agent_runtime_error'
    where status = 'running'
      and (lease_expires_at is null or lease_expires_at <= now())
      and attempts >= 3;

    select * into claimed_run
    from public.customer_agent_runs
    where attempts < 3
      and (
          status = 'queued'
          or (
              status = 'running'
              and (lease_expires_at is null or lease_expires_at <= now())
          )
      )
    order by created_at
    limit 1
    for update skip locked;

    if not found then
        return;
    end if;

    update public.customer_agent_runs
    set status = 'running',
        attempts = attempts + 1,
        lease_token = gen_random_uuid(),
        lease_expires_at = now() + interval '5 minutes',
        started_at = coalesce(started_at, now()),
        updated_at = now(),
        error_code = null
    where id = claimed_run.id
      and business_id = claimed_run.business_id
    returning * into claimed_run;

    return next claimed_run;
end;
$$;

create or replace function public.heartbeat_customer_agent_run(
    target_business_id uuid,
    target_run_id uuid,
    requested_lease_token uuid,
    lease_seconds integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
    if lease_seconds not between 60 and 3600 then
        raise exception 'invalid lease duration' using errcode = '22023';
    end if;

    update public.customer_agent_runs
    set lease_expires_at = now() + make_interval(secs => lease_seconds),
        updated_at = now()
    where business_id = target_business_id
      and id = target_run_id
      and status = 'running'
      and lease_token = requested_lease_token;

    return found;
end;
$$;

create or replace function public.complete_customer_agent_run(
    target_business_id uuid,
    target_run_id uuid,
    requested_lease_token uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.customer_agent_runs
    set status = 'succeeded',
        lease_token = null,
        lease_expires_at = null,
        completed_at = now(),
        updated_at = now(),
        error_code = null
    where business_id = target_business_id
      and id = target_run_id
      and status = 'running'
      and lease_token = requested_lease_token;

    if not found then
        raise exception 'customer agent run lease is stale' using errcode = '40001';
    end if;

    return target_run_id;
end;
$$;

create or replace function public.fail_customer_agent_run(
    target_business_id uuid,
    target_run_id uuid,
    requested_lease_token uuid,
    max_attempts integer
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    next_status text;
begin
    if max_attempts not between 1 and 10 then
        raise exception 'invalid attempt limit' using errcode = '22023';
    end if;

    update public.customer_agent_runs
    set status = case when attempts >= max_attempts then 'failed' else 'queued' end,
        lease_token = null,
        lease_expires_at = null,
        completed_at = case when attempts >= max_attempts then now() else null end,
        updated_at = now(),
        error_code = 'agent_runtime_error'
    where business_id = target_business_id
      and id = target_run_id
      and status = 'running'
      and lease_token = requested_lease_token
    returning status into next_status;

    if next_status is null then
        raise exception 'customer agent run lease is stale' using errcode = '40001';
    end if;

    return next_status;
end;
$$;

create or replace function public.enqueue_telegram_customer_agent_run(
    target_business_id uuid,
    target_channel_id uuid,
    target_provider_event_id text,
    requested_payload_ciphertext text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    queued_run public.customer_agent_runs;
begin
    if target_provider_event_id is null
       or char_length(target_provider_event_id) not between 1 and 255
       or requested_payload_ciphertext is null
       or char_length(requested_payload_ciphertext) > 2000000 then
        raise exception 'invalid Telegram update' using errcode = '22023';
    end if;

    insert into public.customer_agent_runs (
        business_id,
        source_type,
        telegram_channel_id,
        telegram_provider_event_id,
        telegram_payload_ciphertext
    )
    values (
        target_business_id,
        'telegram_update',
        target_channel_id,
        target_provider_event_id,
        requested_payload_ciphertext
    )
    on conflict (business_id, telegram_channel_id, telegram_provider_event_id)
    do update set updated_at = now()
    returning * into queued_run;

    return queued_run.id;
end;
$$;

revoke all on function public.claim_customer_agent_run()
    from public, anon, authenticated;
grant execute on function public.claim_customer_agent_run() to service_role;
revoke all on function public.heartbeat_customer_agent_run(uuid, uuid, uuid, integer)
    from public, anon, authenticated;
grant execute on function public.heartbeat_customer_agent_run(uuid, uuid, uuid, integer)
    to service_role;
revoke all on function public.complete_customer_agent_run(uuid, uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.complete_customer_agent_run(uuid, uuid, uuid)
    to service_role;
revoke all on function public.fail_customer_agent_run(uuid, uuid, uuid, integer)
    from public, anon, authenticated;
grant execute on function public.fail_customer_agent_run(uuid, uuid, uuid, integer)
    to service_role;
revoke all on function public.enqueue_telegram_customer_agent_run(uuid, uuid, text, text)
    from public, anon, authenticated;
grant execute on function public.enqueue_telegram_customer_agent_run(uuid, uuid, text, text)
    to service_role;
