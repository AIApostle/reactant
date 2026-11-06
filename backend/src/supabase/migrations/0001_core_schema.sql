-- Reactant core schema. Run once in Supabase SQL Editor.
-- Never edit a migration after it has been run; add a new numbered migration instead.

create extension if not exists pgcrypto with schema extensions;

create type public.business_role as enum ('owner', 'admin', 'staff', 'read_only');
create type public.invitation_status as enum ('pending', 'accepted', 'expired', 'revoked');
create type public.product_status as enum ('active', 'draft', 'archived');
create type public.approval_status as enum ('pending', 'approved', 'rejected', 'expired', 'cancelled');

create table public.businesses (
    id uuid primary key default gen_random_uuid(),
    name text not null check (char_length(name) between 1 and 160),
    country char(2) check (country is null or country ~ '^[A-Z]{2}$'),
    currency char(3) not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
    timezone text not null default 'UTC',
    support_email text,
    phone text,
    website text,
    return_policy text,
    delivery_policy text,
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.business_members (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role public.business_role not null,
    created_at timestamptz not null default now(),
    unique (business_id, user_id),
    unique (business_id, id)
);

create table public.invitations (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    email text not null,
    role public.business_role not null check (role <> 'owner'),
    token_hash text not null unique,
    status public.invitation_status not null default 'pending',
    invited_by uuid not null references auth.users(id),
    expires_at timestamptz not null,
    accepted_at timestamptz,
    created_at timestamptz not null default now()
);

create table public.business_settings (
    business_id uuid primary key references public.businesses(id) on delete cascade,
    notifications jsonb not null default
        '{"new_conversations":true,"approval_requests":true,"payment_updates":true,"weekly_summary":true}'::jsonb,
    privacy jsonb not null default '{"retention_days":365}'::jsonb,
    updated_at timestamptz not null default now()
);

create or replace function public.increment_business_version()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    new.version = old.version + 1;
    return new;
end;
$$;

create trigger businesses_increment_version
before update on public.businesses
for each row execute function public.increment_business_version();

create or replace function public.validate_business_timezone()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_timezone_names
        where name = new.timezone
    ) then
        raise exception 'invalid timezone' using errcode = '22023';
    end if;
    return new;
end;
$$;

create trigger businesses_validate_timezone
before insert or update of timezone on public.businesses
for each row execute function public.validate_business_timezone();

create table public.products (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    source text not null default 'manual',
    provider_product_id text,
    name text not null check (char_length(name) between 1 and 255),
    description text,
    category text,
    price_minor bigint not null check (price_minor >= 0),
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    stock_quantity integer check (stock_quantity is null or stock_quantity >= 0),
    status public.product_status not null default 'active',
    agent_enabled boolean not null default true,
    image_asset_ids uuid[] not null default '{}',
    provider_data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, id),
    unique (business_id, source, provider_product_id)
);

create table public.media_assets (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    storage_path text not null unique,
    file_name text not null,
    content_type text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
    size_bytes bigint not null check (size_bytes between 1 and 5242880),
    delivery_path text,
    status text not null default 'pending' check (status in ('pending', 'validated', 'rejected')),
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    unique (business_id, id)
);

create table public.integrations (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    provider text not null,
    category text not null,
    status text not null default 'pending',
    credentials_ciphertext text,
    connected_at timestamptz,
    last_success_at timestamptz,
    last_error text,
    granted_scopes text[] not null default '{}',
    sync_status text not null default 'idle',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, id)
);

create table public.agent_configs (
    business_id uuid primary key references public.businesses(id) on delete cascade,
    enabled boolean not null default false,
    status text not null default 'disabled',
    business_context text not null default '',
    tone text not null default 'warm_helpful',
    handoff_rule text not null default 'when_uncertain',
    permissions jsonb not null default '{}'::jsonb,
    approval_policy jsonb not null default '{}'::jsonb,
    version bigint not null default 1,
    updated_at timestamptz not null default now()
);

create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    channel text not null,
    provider_conversation_id text,
    status text not null default 'open' check (status in ('open', 'needs_reply', 'resolved')),
    assignee_id uuid,
    handoff_status text not null default 'none' check (handoff_status in ('none', 'pending', 'accepted', 'returned')),
    customer_context jsonb not null default '{}'::jsonb,
    last_message_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, id),
    foreign key (business_id, assignee_id)
        references public.business_members(business_id, id)
);

create table public.customer_messages (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    conversation_id uuid not null,
    sender_type text not null check (sender_type in ('customer', 'staff', 'agent')),
    sender_id text,
    text text not null,
    visibility text not null check (visibility in ('customer', 'staff')),
    delivery_status text not null default 'sent' check (delivery_status in ('queued', 'sent', 'failed')),
    provider_message_id text,
    idempotency_key text,
    created_at timestamptz not null default now(),
    foreign key (business_id, conversation_id)
        references public.conversations(business_id, id) on delete cascade,
    unique (business_id, id),
    unique (business_id, idempotency_key)
);

create table public.owner_threads (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null unique references public.businesses(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (business_id, id)
);

create table public.agent_runs (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    status text not null default 'queued',
    created_at timestamptz not null default now(),
    unique (business_id, id)
);

create table public.approvals (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    action_type text not null,
    status public.approval_status not null default 'pending',
    impact jsonb not null default '{}'::jsonb,
    expires_at timestamptz,
    requested_by text not null,
    decided_by uuid references auth.users(id),
    decided_at timestamptz,
    decision_note text,
    idempotency_key text,
    request_idempotency_key text,
    created_at timestamptz not null default now(),
    unique (business_id, id),
    unique (business_id, request_idempotency_key)
);

create table public.owner_messages (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    thread_id uuid not null references public.owner_threads(id) on delete cascade,
    sender_type text not null check (sender_type in ('user', 'agent')),
    sender_id text not null,
    display_name text not null,
    kind text not null check (kind in (
        'text', 'clarification', 'approval_request', 'exception', 'status_update', 'summary'
    )),
    text text not null,
    approval_id uuid,
    agent_run_id uuid,
    idempotency_key text,
    client_message_id uuid,
    read_at timestamptz,
    created_at timestamptz not null default now(),
    foreign key (business_id, thread_id)
        references public.owner_threads(business_id, id) on delete cascade,
    foreign key (business_id, approval_id)
        references public.approvals(business_id, id),
    unique (business_id, id),
    unique (business_id, idempotency_key),
    unique (business_id, client_message_id)
);

create table public.orders (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    customer_name text not null,
    customer_email text,
    status text not null default 'pending',
    payment_status text not null default 'unpaid',
    amount_minor bigint not null check (amount_minor >= 0),
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    created_by uuid references auth.users(id),
    idempotency_key text,
    idempotency_request_hash text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, id),
    unique (business_id, created_by, idempotency_key)
);

create table public.payments (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    order_id uuid not null,
    provider text not null,
    status text not null default 'pending',
    amount_minor bigint not null check (amount_minor >= 0),
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    provider_checkout_id text,
    checkout_url text,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (business_id, order_id) references public.orders(business_id, id) on delete cascade,
    unique (business_id, id)
);

create table public.order_items (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    order_id uuid not null,
    product_id uuid not null,
    product_name text not null,
    quantity integer not null check (quantity > 0),
    unit_price_minor bigint not null check (unit_price_minor >= 0),
    total_minor bigint not null check (total_minor >= 0),
    foreign key (business_id, order_id) references public.orders(business_id, id) on delete cascade,
    foreign key (business_id, product_id) references public.products(business_id, id)
);

create table public.notifications (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    type text not null,
    title text not null,
    body text not null default '',
    data jsonb not null default '{}'::jsonb,
    read_at timestamptz,
    created_at timestamptz not null default now(),
    unique (business_id, id)
);

create table public.conversation_reads (
    business_id uuid not null,
    conversation_id uuid not null,
    user_id uuid not null references auth.users(id) on delete cascade,
    read_at timestamptz not null default now(),
    primary key (business_id, conversation_id, user_id),
    foreign key (business_id, conversation_id)
        references public.conversations(business_id, id) on delete cascade
);

create table public.audit_events (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    actor_id uuid references auth.users(id),
    event_type text not null,
    resource_type text not null,
    resource_id text,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table public.idempotency_records (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    actor_id uuid not null references auth.users(id),
    idempotency_key text not null,
    operation text not null,
    response jsonb,
    created_at timestamptz not null default now(),
    unique (business_id, actor_id, idempotency_key, operation)
);

create table public.realtime_tickets (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    business_id uuid not null references public.businesses(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);

create table public.provider_events (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    provider_event_id text not null,
    resource_id text not null,
    payload jsonb not null,
    received_at timestamptz not null default now(),
    processed_at timestamptz,
    unique (provider, resource_id, provider_event_id)
);

create table public.outbox_events (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references public.businesses(id) on delete cascade,
    event_type text not null,
    topic text not null,
    data jsonb not null,
    created_at timestamptz not null default now(),
    published_at timestamptz,
    dedupe_key text,
    unique (business_id, dedupe_key)
);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'product-media',
    'product-media',
    false,
    5242880,
    array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.is_business_member(target_business_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.business_members membership
        where membership.business_id = target_business_id
          and membership.user_id = (select auth.uid())
    );
$$;

create or replace function public.has_business_role(
    target_business_id uuid,
    allowed_roles public.business_role[]
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.business_members membership
        where membership.business_id = target_business_id
          and membership.user_id = (select auth.uid())
          and membership.role = any (allowed_roles)
    );
$$;

create or replace function public.create_business_with_owner(
    business_name text,
    business_country text,
    business_currency text,
    business_timezone text
)
returns public.businesses
language plpgsql
security definer
set search_path = ''
as $$
declare
    created_business public.businesses;
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    insert into public.businesses (name, country, currency, timezone)
    values (business_name, business_country, business_currency, business_timezone)
    returning * into created_business;

    insert into public.business_members (business_id, user_id, role)
    values (created_business.id, auth.uid(), 'owner');

    insert into public.business_settings (business_id)
    values (created_business.id);

    insert into public.agent_configs (business_id)
    values (created_business.id);

    return created_business;
end;
$$;

create or replace function public.accept_business_invitation(invitation_token_hash text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    invitation public.invitations;
    authenticated_email text;
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    select * into invitation
    from public.invitations
    where token_hash = invitation_token_hash
      and status = 'pending'
      and expires_at > now()
    for update;

    if not found then
        raise exception 'invitation unavailable' using errcode = 'P0002';
    end if;

    select lower(email) into authenticated_email
    from auth.users
    where id = auth.uid();

    if authenticated_email is null or authenticated_email <> lower(invitation.email)
       or not exists (
           select 1 from auth.users
           where id = auth.uid() and email_confirmed_at is not null
       ) then
        raise exception 'invitation unavailable' using errcode = 'P0002';
    end if;

    insert into public.business_members (business_id, user_id, role)
    values (invitation.business_id, auth.uid(), invitation.role)
    on conflict (business_id, user_id) do nothing;

    update public.invitations
    set status = 'accepted', accepted_at = now()
    where id = invitation.id;

    return invitation.business_id;
end;
$$;

create or replace function public.update_business_member(
    target_business_id uuid,
    target_member_id uuid,
    new_role public.business_role
)
returns public.business_members
language plpgsql
security definer
set search_path = ''
as $$
declare
    target_member public.business_members;
begin
    if not public.has_business_role(
        target_business_id,
        array['owner']::public.business_role[]
    ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    perform 1 from public.businesses where id = target_business_id for update;
    select * into target_member
    from public.business_members
    where business_id = target_business_id and id = target_member_id
    for update;

    if not found then
        raise exception 'member unavailable' using errcode = 'P0002';
    end if;

    if target_member.role = 'owner' and new_role <> 'owner'
       and (select count(*) from public.business_members
            where business_id = target_business_id and role = 'owner') <= 1 then
        raise exception 'business must retain an owner' using errcode = '23514';
    end if;

    update public.business_members
    set role = new_role
    where id = target_member_id
    returning * into target_member;
    return target_member;
end;
$$;

create or replace function public.remove_business_member(
    target_business_id uuid,
    target_member_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    target_member public.business_members;
begin
    if not public.has_business_role(
        target_business_id,
        array['owner']::public.business_role[]
    ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    perform 1 from public.businesses where id = target_business_id for update;
    select * into target_member
    from public.business_members
    where business_id = target_business_id and id = target_member_id
    for update;

    if not found then
        raise exception 'member unavailable' using errcode = 'P0002';
    end if;

    if target_member.role = 'owner'
       and (select count(*) from public.business_members
            where business_id = target_business_id and role = 'owner') <= 1 then
        raise exception 'business must retain an owner' using errcode = '23514';
    end if;

    delete from public.business_members where id = target_member_id;
end;
$$;

create or replace function public.patch_business_settings(
    target_business_id uuid,
    expected_version bigint,
    business_changes jsonb,
    notification_changes jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    target_business public.businesses;
    target_settings public.business_settings;
begin
    if not public.has_business_role(
        target_business_id,
        array['owner', 'admin']::public.business_role[]
    ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    select * into target_business
    from public.businesses
    where id = target_business_id
    for update;
    if not found then
        raise exception 'business unavailable' using errcode = 'P0002';
    end if;
    if target_business.version <> expected_version then
        raise exception 'stale business version' using errcode = '40001';
    end if;

    if business_changes <> '{}'::jsonb or notification_changes <> '{}'::jsonb then
        update public.businesses
        set name = case when business_changes ? 'name' then business_changes->>'name' else name end,
            support_email = case when business_changes ? 'support_email' then business_changes->>'support_email' else support_email end,
            phone = case when business_changes ? 'phone' then business_changes->>'phone' else phone end,
            website = case when business_changes ? 'website' then business_changes->>'website' else website end,
            country = case when business_changes ? 'country' then business_changes->>'country' else country end,
            currency = case when business_changes ? 'currency' then business_changes->>'currency' else currency end,
            timezone = case when business_changes ? 'timezone' then business_changes->>'timezone' else timezone end,
            return_policy = case when business_changes ? 'return_policy' then business_changes->>'return_policy' else return_policy end,
            delivery_policy = case when business_changes ? 'delivery_policy' then business_changes->>'delivery_policy' else delivery_policy end
        where id = target_business_id
        returning * into target_business;

        if notification_changes <> '{}'::jsonb then
            insert into public.business_settings (business_id, notifications)
            values (target_business_id, notification_changes)
            on conflict (business_id) do update
            set notifications = public.business_settings.notifications || excluded.notifications,
                updated_at = now()
            returning * into target_settings;
        end if;
    else
        select * into target_settings
        from public.business_settings
        where business_id = target_business_id;
    end if;

    if target_settings.business_id is null then
        select * into target_settings
        from public.business_settings
        where business_id = target_business_id;
    end if;

    return jsonb_build_object(
        'business', to_jsonb(target_business),
        'settings', to_jsonb(target_settings)
    );
end;
$$;

create or replace function public.get_or_create_owner_thread(target_business_id uuid)
returns public.owner_threads
language plpgsql
security definer
set search_path = ''
as $$
declare
    result public.owner_threads;
begin
    if not public.is_business_member(target_business_id) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    insert into public.owner_threads (business_id)
    values (target_business_id)
    on conflict (business_id) do update set business_id = excluded.business_id
    returning * into result;
    return result;
end;
$$;

create or replace function public.decide_approval(
    target_business_id uuid,
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
    target_approval public.approvals;
    is_approver boolean;
begin
    if auth.uid() is null or requested_decision not in ('approved', 'rejected') then
        raise exception 'invalid decision' using errcode = '22023';
    end if;

    select * into target_approval
    from public.approvals
    where business_id = target_business_id and id = target_approval_id
    for update;
    if not found then
        raise exception 'approval unavailable' using errcode = 'P0002';
    end if;

    if target_approval.status <> 'pending' then
        if target_approval.idempotency_key = requested_idempotency_key
           and target_approval.decided_by = auth.uid()
           and target_approval.status = requested_decision then
            return target_approval;
        end if;
        raise exception 'approval already decided' using errcode = '23505';
    end if;

    is_approver := public.has_business_role(
        target_business_id,
        array['owner', 'admin']::public.business_role[]
    ) or exists (
        select 1
        from public.business_members member
        join public.agent_configs config on config.business_id = member.business_id
        where member.business_id = target_business_id
          and member.user_id = auth.uid()
          and member.id::text = any (
              array(select jsonb_array_elements_text(config.approval_policy->'approver_member_ids'))
          )
    );
    if not is_approver then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    update public.approvals
    set status = requested_decision,
        decided_by = auth.uid(),
        decided_at = now(),
        decision_note = requested_note,
        idempotency_key = requested_idempotency_key
    where id = target_approval_id
    returning * into target_approval;

    insert into public.audit_events (
        business_id, actor_id, event_type, resource_type, resource_id, data
    )
    values (
        target_business_id, auth.uid(), 'approval.decided', 'approval',
        target_approval_id::text,
        jsonb_build_object('decision', requested_decision, 'note', requested_note)
    );

    insert into public.outbox_events (business_id, event_type, topic, data)
    values (
        target_business_id, 'approval.decided', 'approvals',
        jsonb_build_object('approval_id', target_approval_id, 'status', requested_decision)
    );
    return target_approval;
end;
$$;

create or replace function public.create_order_from_cart(
    target_business_id uuid,
    customer_name text,
    customer_email text,
    requested_currency text,
    requested_items jsonb,
    request_idempotency_key text,
    request_hash text
)
returns public.orders
language plpgsql
security definer
set search_path = ''
as $$
declare
    created_order public.orders;
    current_product public.products;
    item jsonb;
    item_quantity integer;
    line_total bigint;
    order_total bigint := 0;
    existing_order public.orders;
begin
    if not public.has_business_role(
        target_business_id,
        array['owner', 'admin', 'staff']::public.business_role[]
    ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;
    if requested_items is null
       or jsonb_typeof(requested_items) <> 'array'
       or jsonb_array_length(requested_items) = 0 then
        raise exception 'invalid cart' using errcode = '22023';
    end if;
    if request_idempotency_key is null
       or char_length(request_idempotency_key) not between 1 and 200
       or request_hash is null then
        raise exception 'idempotency key required' using errcode = '22023';
    end if;

    select * into existing_order
    from public.orders
    where business_id = target_business_id
      and created_by = auth.uid()
      and idempotency_key = request_idempotency_key
    for update;
    if found then
        if existing_order.idempotency_request_hash <> request_hash then
            raise exception 'idempotency key reused' using errcode = '23505';
        end if;
        return existing_order;
    end if;

    insert into public.orders (
        business_id, customer_name, customer_email, amount_minor, currency, created_by,
        idempotency_key, idempotency_request_hash
    )
    values (
        target_business_id, customer_name, customer_email, 0, requested_currency, auth.uid(),
        request_idempotency_key, request_hash
    )
    returning * into created_order;

    for item in select value from jsonb_array_elements(requested_items)
    loop
        item_quantity := (item->>'quantity')::integer;
        if item_quantity < 1 then
            raise exception 'invalid quantity' using errcode = '22023';
        end if;

        select * into current_product
        from public.products
        where business_id = target_business_id
          and id = (item->>'product_id')::uuid
          and status = 'active'
        for update;
        if not found or current_product.currency <> requested_currency then
            raise exception 'product unavailable' using errcode = 'P0002';
        end if;
        if current_product.stock_quantity is not null
           and current_product.stock_quantity < item_quantity then
            raise exception 'insufficient stock' using errcode = '23514';
        end if;

        line_total := current_product.price_minor * item_quantity;
        order_total := order_total + line_total;
        insert into public.order_items (
            business_id, order_id, product_id, product_name, quantity,
            unit_price_minor, total_minor
        )
        values (
            target_business_id, created_order.id, current_product.id,
            current_product.name, item_quantity, current_product.price_minor, line_total
        );
        if current_product.stock_quantity is not null then
            perform set_config('reactant.allow_inventory_update', 'true', true);
            update public.products
            set stock_quantity = stock_quantity - item_quantity
            where id = current_product.id;
            perform set_config('reactant.allow_inventory_update', 'false', true);
        end if;
    end loop;

    update public.orders
    set amount_minor = order_total
    where id = created_order.id
    returning * into created_order;

    insert into public.audit_events (
        business_id, actor_id, event_type, resource_type, resource_id, data
    )
    values (
        target_business_id, auth.uid(), 'order.created', 'order',
        created_order.id::text, jsonb_build_object('amount_minor', order_total, 'currency', requested_currency)
    );
    return created_order;
end;
$$;

create or replace function public.cancel_unpaid_order(
    target_business_id uuid,
    target_order_id uuid
)
returns public.orders
language plpgsql
security definer
set search_path = ''
as $$
declare
    target_order public.orders;
    line public.order_items;
begin
    if not public.has_business_role(
        target_business_id,
        array['owner', 'admin', 'staff']::public.business_role[]
    ) then
        raise exception 'not authorized' using errcode = '42501';
    end if;

    select * into target_order
    from public.orders
    where business_id = target_business_id and id = target_order_id
    for update;
    if not found then
        raise exception 'order unavailable' using errcode = 'P0002';
    end if;
    if target_order.status <> 'pending' or target_order.payment_status <> 'unpaid' then
        raise exception 'order cannot be cancelled' using errcode = '23514';
    end if;

    for line in
        select * from public.order_items
        where business_id = target_business_id and order_id = target_order_id
    loop
        perform set_config('reactant.allow_inventory_update', 'true', true);
        update public.products
        set stock_quantity = stock_quantity + line.quantity
        where business_id = target_business_id
          and id = line.product_id
          and stock_quantity is not null;
        perform set_config('reactant.allow_inventory_update', 'false', true);
    end loop;

    update public.orders
    set status = 'cancelled'
    where id = target_order_id
    returning * into target_order;
    insert into public.audit_events (
        business_id, actor_id, event_type, resource_type, resource_id
    )
    values (target_business_id, auth.uid(), 'order.cancelled', 'order', target_order_id::text);
    return target_order;
end;
$$;

create or replace function public.consume_realtime_ticket(ticket_token_hash text)
returns table (business_id uuid, user_id uuid)
language plpgsql
security definer
set search_path = ''
as $$
declare
    ticket public.realtime_tickets;
begin
    select * into ticket
    from public.realtime_tickets
    where token_hash = ticket_token_hash
      and consumed_at is null
      and expires_at > now()
    for update;
    if not found or not exists (
        select 1 from public.business_members member
        where member.business_id = ticket.business_id and member.user_id = ticket.user_id
    ) then
        raise exception 'ticket unavailable' using errcode = 'P0002';
    end if;
    update public.realtime_tickets
    set consumed_at = now()
    where id = ticket.id;
    return query select ticket.business_id, ticket.user_id;
end;
$$;

create or replace function public.try_uuid(value text)
returns uuid
language plpgsql
immutable
set search_path = ''
as $$
begin
    return value::uuid;
exception
    when invalid_text_representation then
        return null;
end;
$$;

revoke all on function public.is_business_member(uuid) from public;
revoke all on function public.has_business_role(uuid, public.business_role[]) from public;
revoke all on function public.create_business_with_owner(text, text, text, text) from public;
revoke all on function public.accept_business_invitation(text) from public;
revoke all on function public.update_business_member(uuid, uuid, public.business_role) from public;
revoke all on function public.remove_business_member(uuid, uuid) from public;
revoke all on function public.patch_business_settings(uuid, bigint, jsonb, jsonb) from public;
revoke all on function public.get_or_create_owner_thread(uuid) from public;
revoke all on function public.decide_approval(uuid, uuid, public.approval_status, text, text) from public;
revoke all on function public.create_order_from_cart(uuid, text, text, text, jsonb, text, text) from public;
revoke all on function public.cancel_unpaid_order(uuid, uuid) from public;
revoke all on function public.consume_realtime_ticket(text) from public;
revoke all on function public.try_uuid(text) from public;
grant execute on function public.is_business_member(uuid) to authenticated;
grant execute on function public.has_business_role(uuid, public.business_role[]) to authenticated;
grant execute on function public.create_business_with_owner(text, text, text, text) to authenticated;
grant execute on function public.accept_business_invitation(text) to authenticated;
grant execute on function public.update_business_member(uuid, uuid, public.business_role) to authenticated;
grant execute on function public.remove_business_member(uuid, uuid) to authenticated;
grant execute on function public.patch_business_settings(uuid, bigint, jsonb, jsonb) to authenticated;
grant execute on function public.get_or_create_owner_thread(uuid) to authenticated;
grant execute on function public.decide_approval(uuid, uuid, public.approval_status, text, text) to authenticated;
grant execute on function public.create_order_from_cart(uuid, text, text, text, jsonb, text, text) to authenticated;
grant execute on function public.cancel_unpaid_order(uuid, uuid) to authenticated;
grant execute on function public.consume_realtime_ticket(text) to anon, authenticated;
grant execute on function public.try_uuid(text) to authenticated;

alter table public.businesses enable row level security;
alter table public.business_members enable row level security;
alter table public.invitations enable row level security;
alter table public.business_settings enable row level security;
alter table public.products enable row level security;
alter table public.media_assets enable row level security;
alter table public.integrations enable row level security;
alter table public.agent_configs enable row level security;
alter table public.conversations enable row level security;
alter table public.customer_messages enable row level security;
alter table public.owner_threads enable row level security;
alter table public.owner_messages enable row level security;
alter table public.approvals enable row level security;
alter table public.orders enable row level security;
alter table public.payments enable row level security;
alter table public.order_items enable row level security;
alter table public.agent_runs enable row level security;
alter table public.notifications enable row level security;
alter table public.audit_events enable row level security;
alter table public.idempotency_records enable row level security;
alter table public.realtime_tickets enable row level security;
alter table public.conversation_reads enable row level security;
alter table public.provider_events enable row level security;
alter table public.outbox_events enable row level security;

create policy "business members can read their business"
on public.businesses for select to authenticated
using (public.is_business_member(id));
create policy "business admins can update their business"
on public.businesses for update to authenticated
using (public.has_business_role(id, array['owner', 'admin']::public.business_role[]))
with check (public.has_business_role(id, array['owner', 'admin']::public.business_role[]));

create policy "members can read memberships"
on public.business_members for select to authenticated
using (public.is_business_member(business_id));
create policy "members can read invitations"
on public.invitations for select to authenticated
using (public.is_business_member(business_id));
create policy "admins can create invitations"
on public.invitations for insert to authenticated
with check (
    public.has_business_role(business_id, array['owner', 'admin']::public.business_role[])
    and invited_by = (select auth.uid())
);
create policy "admins can delete invitations"
on public.invitations for delete to authenticated
using (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]));
revoke select (token_hash) on public.invitations from authenticated;
grant insert (token_hash) on public.invitations to authenticated;

create policy "members can read business settings"
on public.business_settings for select to authenticated
using (public.is_business_member(business_id));
create policy "admins can manage business settings"
on public.business_settings for all to authenticated
using (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]));

create policy "members can read products"
on public.products for select to authenticated
using (public.is_business_member(business_id));
create policy "staff can manage products"
on public.products for all to authenticated
using (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]));

create or replace function public.protect_provider_managed_products()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.source is distinct from old.source
       and coalesce(auth.role(), '') <> 'service_role' then
        raise exception 'product source is read-only' using errcode = '42501';
    end if;
    if old.source <> 'manual' and (
        new.source <> old.source or
        new.provider_product_id is distinct from old.provider_product_id or
        new.name is distinct from old.name or
        new.description is distinct from old.description or
        new.category is distinct from old.category or
        new.price_minor is distinct from old.price_minor or
        new.currency is distinct from old.currency or
        new.stock_quantity is distinct from old.stock_quantity or
        new.provider_data is distinct from old.provider_data or
        new.status is distinct from old.status or
        new.agent_enabled is distinct from old.agent_enabled or
        new.image_asset_ids is distinct from old.image_asset_ids
    ) and coalesce(auth.role(), '') <> 'service_role'
      and coalesce(current_setting('reactant.allow_inventory_update', true), '') <> 'true' then
        raise exception 'provider-managed product fields are read-only' using errcode = '42501';
    end if;
    return new;
end;
$$;

create trigger products_protect_provider_managed
before update on public.products
for each row execute function public.protect_provider_managed_products();

create policy "members can read media assets"
on public.media_assets for select to authenticated
using (public.is_business_member(business_id));
create policy "staff can manage media assets"
on public.media_assets for all to authenticated
using (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]));

create policy "members can read integrations"
on public.integrations for select to authenticated
using (public.is_business_member(business_id));
create policy "admins can manage integrations"
on public.integrations for all to authenticated
using (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]));
revoke select (credentials_ciphertext) on public.integrations from authenticated;
grant insert (credentials_ciphertext) on public.integrations to authenticated;
grant update (credentials_ciphertext) on public.integrations to authenticated;

create policy "members can read agent configuration"
on public.agent_configs for select to authenticated
using (public.is_business_member(business_id));
create policy "admins can manage agent configuration"
on public.agent_configs for all to authenticated
using (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin']::public.business_role[]));

create policy "members can read conversations"
on public.conversations for select to authenticated
using (public.is_business_member(business_id))
;
create policy "staff can update conversations"
on public.conversations for update to authenticated
using (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]))
with check (public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[]));
create policy "members can read customer messages"
on public.customer_messages for select to authenticated
using (public.is_business_member(business_id));
create policy "staff can send customer messages"
on public.customer_messages for insert to authenticated
with check (
    public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[])
    and sender_type = 'staff'
    and sender_id = (select auth.uid())::text
    and visibility = 'customer'
);
create policy "members can read owner threads"
on public.owner_threads for select to authenticated
using (public.is_business_member(business_id));
create policy "members can create owner threads"
on public.owner_threads for insert to authenticated
with check (public.is_business_member(business_id));
create policy "members can read owner messages"
on public.owner_messages for select to authenticated
using (public.is_business_member(business_id));
create policy "members can send owner messages"
on public.owner_messages for insert to authenticated
with check (
    public.has_business_role(
        business_id,
        array['owner', 'admin', 'staff']::public.business_role[]
    )
    and sender_type = 'user'
    and sender_id = (select auth.uid())::text
);
create policy "members can mark agent owner messages read"
on public.owner_messages for update to authenticated
using (public.is_business_member(business_id) and sender_type = 'agent')
with check (public.is_business_member(business_id) and sender_type = 'agent');
revoke update on public.owner_messages from authenticated;
grant update (read_at) on public.owner_messages to authenticated;

create policy "members can read approvals"
on public.approvals for select to authenticated
using (public.is_business_member(business_id));
create policy "business members can request approvals"
on public.approvals for insert to authenticated
with check (
    public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[])
);
create policy "members can read orders"
on public.orders for select to authenticated
using (public.is_business_member(business_id));
create policy "members can read order items"
on public.order_items for select to authenticated
using (public.is_business_member(business_id));
create policy "members can read payments"
on public.payments for select to authenticated
using (public.is_business_member(business_id));
create policy "members can manage conversation read receipts"
on public.conversation_reads for all to authenticated
using (user_id = (select auth.uid()) and public.is_business_member(business_id))
with check (user_id = (select auth.uid()) and public.is_business_member(business_id));
create policy "members can read agent runs"
on public.agent_runs for select to authenticated
using (public.is_business_member(business_id));

create policy "members can read notifications"
on public.notifications for select to authenticated
using (public.is_business_member(business_id));
create policy "members can mark notifications read"
on public.notifications for update to authenticated
using (public.is_business_member(business_id))
with check (public.is_business_member(business_id));
revoke update on public.notifications from authenticated;
grant update (read_at) on public.notifications to authenticated;
create policy "members can read audit events"
on public.audit_events for select to authenticated
using (public.is_business_member(business_id));
create policy "members can read outbox events"
on public.outbox_events for select to authenticated
using (public.is_business_member(business_id));
create policy "admins can queue outbox events"
on public.outbox_events for insert to authenticated
with check (
    public.has_business_role(business_id, array['owner', 'admin', 'staff']::public.business_role[])
    and topic in ('conversations', 'owner_assistant', 'approvals', 'orders', 'notifications')
);
create policy "members can read idempotency records"
on public.idempotency_records for select to authenticated
using (public.is_business_member(business_id));
create policy "members can manage realtime tickets"
on public.realtime_tickets for insert to authenticated
with check (user_id = (select auth.uid()) and public.is_business_member(business_id));

create policy "business members can read private product media"
on storage.objects for select to authenticated
using (
    bucket_id = 'product-media'
    and public.is_business_member(public.try_uuid(split_part(name, '/', 1)))
);
create policy "staff can upload private product media"
on storage.objects for insert to authenticated
with check (
    bucket_id = 'product-media'
    and public.has_business_role(
        public.try_uuid(split_part(name, '/', 1)),
        array['owner', 'admin', 'staff']::public.business_role[]
    )
);
create policy "staff can update private product media"
on storage.objects for update to authenticated
using (
    bucket_id = 'product-media'
    and public.has_business_role(
        public.try_uuid(split_part(name, '/', 1)),
        array['owner', 'admin', 'staff']::public.business_role[]
    )
)
with check (
    bucket_id = 'product-media'
    and public.has_business_role(
        public.try_uuid(split_part(name, '/', 1)),
        array['owner', 'admin', 'staff']::public.business_role[]
    )
);

create index business_members_user_idx on public.business_members (user_id, business_id);
create index invitations_business_status_idx on public.invitations (business_id, status, expires_at);
create index products_business_status_idx on public.products (business_id, status, created_at desc);
create index conversations_business_recent_idx on public.conversations (business_id, last_message_at desc);
create index conversation_reads_user_idx on public.conversation_reads (business_id, user_id, read_at desc);
create index customer_messages_thread_idx on public.customer_messages (business_id, conversation_id, created_at);
create index owner_messages_thread_idx on public.owner_messages (business_id, thread_id, created_at);
create index approvals_business_status_idx on public.approvals (business_id, status, created_at desc);
create index orders_business_created_idx on public.orders (business_id, created_at desc);
create index notifications_business_created_idx on public.notifications (business_id, created_at desc);
create index audit_events_business_created_idx on public.audit_events (business_id, created_at desc);
create index outbox_unpublished_idx on public.outbox_events (created_at) where published_at is null;
