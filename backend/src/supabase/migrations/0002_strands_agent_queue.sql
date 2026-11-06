-- Add a durable, leased queue for Strands owner-assistant runs.
-- 0001_core_schema.sql remains unchanged; this migration is safe to apply separately.

alter table public.agent_runs
    add column input_message_id uuid,
    add column attempts integer not null default 0,
    add column lease_token uuid,
    add column lease_expires_at timestamptz,
    add column started_at timestamptz,
    add column completed_at timestamptz,
    add column updated_at timestamptz not null default now(),
    add column error_code text,
    add constraint agent_runs_attempts_nonnegative check (attempts >= 0),
    add constraint agent_runs_business_input_message_key
        unique (business_id, input_message_id),
    add constraint agent_runs_input_message_fk
        foreign key (business_id, input_message_id)
        references public.owner_messages (business_id, id)
        on delete cascade;

create index agent_runs_queue_idx
    on public.agent_runs (created_at)
    where status in ('queued', 'running') and input_message_id is not null;

revoke all on public.agent_runs from anon;
revoke insert, update, delete on public.agent_runs from authenticated;
grant select on public.agent_runs to authenticated;
grant all on public.agent_runs to service_role;

create or replace function public.enqueue_owner_assistant_message(
    target_business_id uuid,
    target_thread_id uuid,
    requested_text text,
    requested_idempotency_key text,
    requested_client_message_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    existing_message public.owner_messages;
    queued_run public.agent_runs;
begin
    if auth.uid() is null
       or not public.has_business_role(
           target_business_id,
           array['owner', 'admin', 'staff']::public.business_role[]
       ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    if requested_text is null
       or char_length(requested_text) not between 1 and 10000
       or btrim(requested_text) = ''
       or requested_idempotency_key is null
       or char_length(requested_idempotency_key) not between 1 and 200 then
        raise exception 'invalid owner message' using errcode = '22023';
    end if;

    if not exists (
        select 1
        from public.owner_threads
        where business_id = target_business_id
          and id = target_thread_id
    ) then
        raise exception 'owner thread unavailable' using errcode = 'P0002';
    end if;

    select * into existing_message
    from public.owner_messages
    where business_id = target_business_id
      and idempotency_key = requested_idempotency_key
    limit 1
    for update;

    if existing_message.id is null and requested_client_message_id is not null then
        select * into existing_message
        from public.owner_messages
        where business_id = target_business_id
          and client_message_id = requested_client_message_id
        limit 1
        for update;
    end if;

    if existing_message.id is null then
        insert into public.owner_messages (
            business_id,
            thread_id,
            sender_type,
            sender_id,
            display_name,
            kind,
            text,
            idempotency_key,
            client_message_id
        )
        values (
            target_business_id,
            target_thread_id,
            'user',
            auth.uid()::text,
            'Team member',
            'text',
            requested_text,
            requested_idempotency_key,
            requested_client_message_id
        )
        on conflict do nothing
        returning * into existing_message;
    end if;

    if existing_message.id is null then
        select * into existing_message
        from public.owner_messages
        where business_id = target_business_id
          and (
              idempotency_key = requested_idempotency_key
              or (
                  requested_client_message_id is not null
                  and client_message_id = requested_client_message_id
              )
          )
        order by created_at
        limit 1
        for update;
    end if;

    if existing_message.id is null then
        raise exception 'owner message could not be persisted' using errcode = 'P0001';
    end if;

    if existing_message.sender_type <> 'user'
       or existing_message.sender_id <> auth.uid()::text
       or existing_message.text <> requested_text
       or existing_message.thread_id <> target_thread_id
       or (
           requested_client_message_id is not null
           and existing_message.client_message_id is distinct from requested_client_message_id
           and existing_message.idempotency_key = requested_idempotency_key
       ) then
        raise exception 'idempotency key conflict' using errcode = '23505';
    end if;

    insert into public.agent_runs (business_id, status, input_message_id)
    values (target_business_id, 'queued', existing_message.id)
    on conflict (business_id, input_message_id) do nothing
    returning * into queued_run;

    if queued_run.id is null then
        select * into queued_run
        from public.agent_runs
        where business_id = target_business_id
          and input_message_id = existing_message.id;
    end if;

    if queued_run.id is null then
        raise exception 'agent run could not be persisted' using errcode = 'P0001';
    end if;

    update public.owner_messages
    set agent_run_id = queued_run.id
    where business_id = target_business_id
      and id = existing_message.id
      and agent_run_id is distinct from queued_run.id;

    insert into public.outbox_events (
        business_id,
        event_type,
        topic,
        data,
        dedupe_key
    )
    values (
        target_business_id,
        'owner_assistant.message_created',
        'owner_assistant',
        jsonb_build_object(
            'message_id', existing_message.id,
            'thread_id', target_thread_id,
            'agent_run_id', queued_run.id
        ),
        'owner-message:' || existing_message.id::text
    )
    on conflict (business_id, dedupe_key) do nothing;

    return jsonb_build_object(
        'message', to_jsonb(existing_message),
        'run', to_jsonb(queued_run)
    );
end;
$$;

create or replace function public.claim_agent_run()
returns setof public.agent_runs
language plpgsql
security definer
set search_path = ''
as $$
declare
    claimed_run public.agent_runs;
begin
    update public.agent_runs
    set status = 'failed',
        lease_token = null,
        lease_expires_at = null,
        completed_at = now(),
        updated_at = now(),
        error_code = 'agent_runtime_error'
    where status = 'running'
      and input_message_id is not null
      and (lease_expires_at is null or lease_expires_at <= now())
      and attempts >= 3;

    select * into claimed_run
    from public.agent_runs
    where input_message_id is not null
      and attempts < 3
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

    update public.agent_runs
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

create or replace function public.heartbeat_agent_run(
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

    update public.agent_runs
    set lease_expires_at = now() + make_interval(secs => lease_seconds),
        updated_at = now()
    where business_id = target_business_id
      and id = target_run_id
      and status = 'running'
      and lease_token = requested_lease_token;

    return found;
end;
$$;

create or replace function public.complete_agent_run(
    target_business_id uuid,
    target_run_id uuid,
    requested_lease_token uuid,
    response_text text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    target_run public.agent_runs;
    target_thread_id uuid;
    response_message_id uuid;
begin
    if response_text is null
       or char_length(response_text) not between 1 and 10000
       or btrim(response_text) = '' then
        raise exception 'invalid agent response' using errcode = '22023';
    end if;

    select * into target_run
    from public.agent_runs
    where business_id = target_business_id
      and id = target_run_id
    for update;

    if not found then
        raise exception 'agent run unavailable' using errcode = 'P0002';
    end if;

    if target_run.status = 'succeeded' then
        select id into response_message_id
        from public.owner_messages
        where business_id = target_business_id
          and agent_run_id = target_run_id
          and sender_type = 'agent'
        limit 1;
        return response_message_id;
    end if;

    if target_run.status <> 'running'
       or target_run.lease_token is distinct from requested_lease_token then
        raise exception 'agent run lease is stale' using errcode = '40001';
    end if;

    select thread_id into target_thread_id
    from public.owner_messages
    where business_id = target_business_id
      and id = target_run.input_message_id;

    if target_thread_id is null then
        raise exception 'owner thread unavailable' using errcode = 'P0002';
    end if;

    insert into public.owner_messages (
        business_id,
        thread_id,
        sender_type,
        sender_id,
        display_name,
        kind,
        text,
        agent_run_id,
        idempotency_key
    )
    values (
        target_business_id,
        target_thread_id,
        'agent',
        'reactant-agent',
        'Business agent',
        'text',
        response_text,
        target_run_id,
        'agent-run:' || target_run_id::text
    )
    returning id into response_message_id;

    update public.agent_runs
    set status = 'succeeded',
        lease_token = null,
        lease_expires_at = null,
        completed_at = now(),
        updated_at = now(),
        error_code = null
    where business_id = target_business_id
      and id = target_run_id;

    insert into public.outbox_events (
        business_id,
        event_type,
        topic,
        data,
        dedupe_key
    )
    values (
        target_business_id,
        'owner_assistant.message_created',
        'owner_assistant',
        jsonb_build_object(
            'message_id', response_message_id,
            'thread_id', target_thread_id,
            'agent_run_id', target_run_id
        ),
        'owner-message:' || response_message_id::text
    )
    on conflict (business_id, dedupe_key) do nothing;

    return response_message_id;
end;
$$;

create or replace function public.fail_agent_run(
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
    target_run public.agent_runs;
    next_status text;
begin
    if max_attempts not between 1 and 10 then
        raise exception 'invalid attempt limit' using errcode = '22023';
    end if;

    select * into target_run
    from public.agent_runs
    where business_id = target_business_id
      and id = target_run_id
    for update;

    if not found then
        raise exception 'agent run unavailable' using errcode = 'P0002';
    end if;

    if target_run.status <> 'running'
       or target_run.lease_token is distinct from requested_lease_token then
        return target_run.status;
    end if;

    next_status := case
        when target_run.attempts >= max_attempts then 'failed'
        else 'queued'
    end;

    update public.agent_runs
    set status = next_status,
        lease_token = null,
        lease_expires_at = null,
        completed_at = case when next_status = 'failed' then now() else null end,
        updated_at = now(),
        error_code = 'agent_runtime_error'
    where business_id = target_business_id
      and id = target_run_id;

    return next_status;
end;
$$;

revoke all on function public.enqueue_owner_assistant_message(uuid, uuid, text, text, uuid) from public, anon;
revoke all on function public.claim_agent_run() from public, anon, authenticated;
revoke all on function public.heartbeat_agent_run(uuid, uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.complete_agent_run(uuid, uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.fail_agent_run(uuid, uuid, uuid, integer) from public, anon, authenticated;

grant execute on function public.enqueue_owner_assistant_message(uuid, uuid, text, text, uuid) to authenticated;
grant execute on function public.claim_agent_run() to service_role;
grant execute on function public.heartbeat_agent_run(uuid, uuid, uuid, integer) to service_role;
grant execute on function public.complete_agent_run(uuid, uuid, uuid, text) to service_role;
grant execute on function public.fail_agent_run(uuid, uuid, uuid, integer) to service_role;
