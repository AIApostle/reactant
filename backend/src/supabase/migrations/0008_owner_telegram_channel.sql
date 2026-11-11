create table public.owner_telegram_channels (
    business_id uuid primary key references public.businesses(id) on delete cascade,
    integration_id uuid not null,
    owner_user_id uuid not null references auth.users(id) on delete cascade,
    telegram_chat_id text,
    pairing_token_hash text unique,
    pairing_expires_at timestamptz,
    paired_at timestamptz,
    created_at timestamptz not null default now(),
    constraint owner_telegram_channel_pairing_token_hash_format
        check (pairing_token_hash is null or pairing_token_hash ~ '^[0-9a-f]{64}$'),
    constraint owner_telegram_channel_pairing_state
        check (
            (telegram_chat_id is null and paired_at is null)
            or (telegram_chat_id is not null and paired_at is not null)
        ),
    foreign key (business_id, integration_id)
        references public.integrations(business_id, id) on delete cascade
);

alter table public.owner_telegram_channels enable row level security;
revoke all on public.owner_telegram_channels from anon, authenticated;
grant all on public.owner_telegram_channels to service_role;

create or replace function public.pair_owner_telegram_chat(
    target_business_id uuid,
    target_integration_id uuid,
    requested_token_hash text,
    requested_chat_id text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    paired_owner_id uuid;
begin
    if requested_chat_id is null
       or char_length(requested_chat_id) not between 1 and 32
       or requested_token_hash is null
       or requested_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'invalid pairing request' using errcode = '22023';
    end if;

    update public.owner_telegram_channels channel
    set telegram_chat_id = requested_chat_id,
        paired_at = now(),
        pairing_token_hash = null,
        pairing_expires_at = null
    where channel.business_id = target_business_id
      and channel.integration_id = target_integration_id
      and channel.pairing_token_hash = requested_token_hash
      and channel.pairing_expires_at > now()
      and exists (
          select 1
          from public.business_members member
          where member.business_id = channel.business_id
            and member.user_id = channel.owner_user_id
            and member.role = 'owner'::public.business_role
      )
    returning channel.owner_user_id into paired_owner_id;

    return paired_owner_id;
end;
$$;

create or replace function public.enqueue_owner_telegram_message(
    target_business_id uuid,
    target_integration_id uuid,
    target_chat_id text,
    requested_text text,
    requested_idempotency_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    owner_id uuid;
    owner_thread public.owner_threads;
    owner_message public.owner_messages;
    queued_run public.agent_runs;
begin
    select channel.owner_user_id into owner_id
    from public.owner_telegram_channels channel
    join public.business_members member
      on member.business_id = channel.business_id
     and member.user_id = channel.owner_user_id
     and member.role = 'owner'::public.business_role
    where channel.business_id = target_business_id
      and channel.integration_id = target_integration_id
      and channel.telegram_chat_id = target_chat_id
      and channel.paired_at is not null
    for update of channel;

    if owner_id is null then
        raise exception 'owner channel unavailable' using errcode = '42501';
    end if;
    if requested_text is null
       or char_length(requested_text) not between 1 and 4000
       or btrim(requested_text) = ''
       or requested_idempotency_key is null
       or char_length(requested_idempotency_key) not between 1 and 200 then
        raise exception 'invalid owner message' using errcode = '22023';
    end if;

    insert into public.owner_threads (business_id)
    values (target_business_id)
    on conflict (business_id) do update set business_id = excluded.business_id
    returning * into owner_thread;

    select * into owner_message
    from public.owner_messages
    where business_id = target_business_id
      and idempotency_key = requested_idempotency_key
    for update;

    if owner_message.id is null then
        insert into public.owner_messages (
            business_id,
            thread_id,
            sender_type,
            sender_id,
            display_name,
            kind,
            text,
            idempotency_key
        )
        values (
            target_business_id,
            owner_thread.id,
            'user',
            owner_id::text,
            'Owner on Telegram',
            'text',
            requested_text,
            requested_idempotency_key
        )
        returning * into owner_message;
    elsif owner_message.sender_type <> 'user'
       or owner_message.sender_id <> owner_id::text
       or owner_message.text <> requested_text then
        raise exception 'idempotency key conflict' using errcode = '23505';
    end if;

    insert into public.agent_runs (business_id, status, input_message_id)
    values (target_business_id, 'queued', owner_message.id)
    on conflict (business_id, input_message_id) do nothing
    returning * into queued_run;

    if queued_run.id is null then
        select * into queued_run
        from public.agent_runs
        where business_id = target_business_id
          and input_message_id = owner_message.id;
    end if;

    if queued_run.id is null then
        raise exception 'agent run could not be persisted' using errcode = 'P0001';
    end if;

    update public.owner_messages
    set agent_run_id = queued_run.id
    where business_id = target_business_id
      and id = owner_message.id
      and agent_run_id is distinct from queued_run.id;

    insert into public.outbox_events (
        business_id, event_type, topic, data, dedupe_key
    )
    values (
        target_business_id,
        'owner_assistant.message_created',
        'owner_assistant',
        jsonb_build_object(
            'message_id', owner_message.id,
            'thread_id', owner_thread.id,
            'agent_run_id', queued_run.id
        ),
        'owner-message:' || owner_message.id::text
    )
    on conflict (business_id, dedupe_key) do nothing;

    return jsonb_build_object(
        'message', to_jsonb(owner_message),
        'run', to_jsonb(queued_run)
    );
end;
$$;

create or replace function public.decide_telegram_approval(
    target_business_id uuid,
    target_integration_id uuid,
    target_chat_id text,
    target_approval_id uuid,
    requested_decision public.approval_status,
    requested_note text,
    requested_idempotency_key text
)
returns public.approvals
language plpgsql
security definer
set search_path = ''
as $$
declare
    owner_id uuid;
    target_approval public.approvals;
begin
    select channel.owner_user_id into owner_id
    from public.owner_telegram_channels channel
    join public.business_members member
      on member.business_id = channel.business_id
     and member.user_id = channel.owner_user_id
     and member.role = 'owner'::public.business_role
    where channel.business_id = target_business_id
      and channel.integration_id = target_integration_id
      and channel.telegram_chat_id = target_chat_id
      and channel.paired_at is not null
    for update of channel;

    if owner_id is null
       or requested_decision not in ('approved', 'rejected')
       or requested_idempotency_key is null
       or char_length(requested_idempotency_key) not between 1 and 200 then
        raise exception 'invalid decision' using errcode = '22023';
    end if;

    select * into target_approval
    from public.approvals
    where business_id = target_business_id
      and id = target_approval_id
    for update;
    if not found then
        raise exception 'approval unavailable' using errcode = 'P0002';
    end if;

    if target_approval.status <> 'pending' then
        if target_approval.idempotency_key = requested_idempotency_key
           and target_approval.decided_by = owner_id
           and target_approval.status = requested_decision then
            return target_approval;
        end if;
        raise exception 'approval already decided' using errcode = '23505';
    end if;

    update public.approvals
    set status = requested_decision,
        decided_by = owner_id,
        decided_at = now(),
        decision_note = requested_note,
        idempotency_key = requested_idempotency_key
    where business_id = target_business_id
      and id = target_approval_id
    returning * into target_approval;

    insert into public.audit_events (
        business_id, actor_id, event_type, resource_type, resource_id, data
    )
    values (
        target_business_id, owner_id, 'approval.decided', 'approval',
        target_approval_id::text,
        jsonb_build_object('decision', requested_decision, 'note', requested_note, 'source', 'telegram')
    );

    insert into public.outbox_events (business_id, event_type, topic, data)
    values (
        target_business_id,
        'approval.decided',
        'approvals',
        jsonb_build_object('approval_id', target_approval_id, 'status', requested_decision)
    );
    return target_approval;
end;
$$;

revoke all on function public.pair_owner_telegram_chat(uuid, uuid, text, text) from public;
revoke all on function public.enqueue_owner_telegram_message(uuid, uuid, text, text, text) from public;
revoke all on function public.decide_telegram_approval(uuid, uuid, text, uuid, public.approval_status, text, text) from public;
grant execute on function public.pair_owner_telegram_chat(uuid, uuid, text, text) to service_role;
grant execute on function public.enqueue_owner_telegram_message(uuid, uuid, text, text, text) to service_role;
grant execute on function public.decide_telegram_approval(uuid, uuid, text, uuid, public.approval_status, text, text) to service_role;
