create table public.agentcard_transactions (
    id uuid primary key default gen_random_uuid(),
    public_transaction_id text not null unique
        check (public_transaction_id ~ '^txn_[A-Za-z0-9_-]{20,80}$'),
    business_id uuid not null,
    order_id uuid not null,
    conversation_id uuid not null,
    customer_name text not null,
    customer_reference text,
    provider text not null check (provider = 'paypal'),
    provider_integration_id uuid not null,
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    subtotal_minor bigint not null check (subtotal_minor >= 0),
    discount_total_minor bigint not null default 0 check (discount_total_minor >= 0),
    tax_total_minor bigint not null default 0 check (tax_total_minor >= 0),
    delivery_total_minor bigint not null default 0 check (delivery_total_minor >= 0),
    total_amount_minor bigint not null check (total_amount_minor >= 0),
    status text not null default 'awaiting_customer' check (status in (
        'awaiting_customer', 'awaiting_payment', 'payment_processing',
        'payment_pending', 'payment_failed', 'paid', 'cancelled', 'expired',
        'reconciliation', 'receipt_generation', 'receipt_issued', 'receipt_delivered',
        'partially_refunded', 'refunded'
    )),
    checkout_snapshot jsonb not null,
    idempotency_key text not null,
    request_hash text not null check (request_hash ~ '^[a-f0-9]{64}$'),
    expires_at timestamptz not null,
    paid_at timestamptz,
    cancelled_at timestamptz,
    failure_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, id),
    unique (business_id, idempotency_key),
    foreign key (business_id, order_id)
        references public.orders(business_id, id),
    foreign key (business_id, conversation_id)
        references public.conversations(business_id, id),
    foreign key (business_id, provider_integration_id)
        references public.integrations(business_id, id)
);

create table public.agentcard_transaction_items (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    product_id uuid not null,
    product_name text not null,
    description text,
    image_asset_ids uuid[] not null default '{}',
    quantity integer not null check (quantity between 1 and 10000),
    unit_price_minor bigint not null check (unit_price_minor >= 0),
    total_minor bigint not null check (total_minor >= 0),
    stock_reserved boolean not null default false,
    created_at timestamptz not null default now(),
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id) on delete cascade,
    foreign key (business_id, product_id)
        references public.products(business_id, id),
    unique (business_id, transaction_id, product_id)
);

create table public.agentcard_checkout_sessions (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    checkout_id text not null unique
        check (checkout_id ~ '^chk_[A-Za-z0-9_-]{20,80}$'),
    token_hash text not null unique check (token_hash ~ '^[a-f0-9]{64}$'),
    status text not null default 'active'
        check (status in ('active', 'revoked', 'completed', 'expired')),
    expires_at timestamptz not null,
    customer_verified_at timestamptz,
    authorization_id uuid,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    last_accessed_at timestamptz,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    revoked_at timestamptz,
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id) on delete cascade,
    unique (business_id, id),
    unique (business_id, transaction_id, id)
);

create table public.agentcard_authorizations (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    checkout_session_id uuid not null,
    authorization_type text not null default 'internal_customer_consent'
        check (authorization_type = 'internal_customer_consent'),
    authorization_version text not null default 'internal-consent/v1',
    checkout_hash text not null check (checkout_hash ~ '^[a-f0-9]{64}$'),
    checkout_snapshot jsonb not null,
    customer_approval_method text not null
        check (customer_approval_method = 'explicit_checkout_button'),
    approved_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id),
    foreign key (business_id, transaction_id, checkout_session_id)
        references public.agentcard_checkout_sessions(business_id, transaction_id, id),
    unique (business_id, checkout_session_id)
);

alter table public.agentcard_checkout_sessions
    add constraint agentcard_checkout_authorization_fk
    foreign key (authorization_id)
    references public.agentcard_authorizations(id);

create table public.agentcard_payments (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    provider text not null check (provider = 'paypal'),
    provider_order_id text not null,
    approval_url text,
    provider_payment_id text,
    provider_capture_id text unique,
    provider_status text not null,
    status text not null check (status in (
        'created', 'processing', 'pending', 'completed', 'failed', 'reconciliation', 'refunded'
    )),
    amount_minor bigint not null check (amount_minor >= 0),
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    captured_at timestamptz,
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id),
    unique (business_id, transaction_id, id),
    unique (provider, provider_order_id)
);

create unique index agentcard_one_completed_payment_per_transaction
    on public.agentcard_payments (business_id, transaction_id)
    where status = 'completed';

create table public.agentcard_webhook_events (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    provider_event_id text not null,
    event_type text not null,
    business_id uuid references public.businesses(id),
    transaction_id uuid,
    signature_verified boolean not null default false,
    processing_status text not null default 'received'
        check (processing_status in ('received', 'processed', 'ignored', 'failed')),
    failure_reason text,
    processed_at timestamptz,
    received_at timestamptz not null default now(),
    unique (provider, provider_event_id),
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id)
);

create table public.agentcard_receipts (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    receipt_number text not null unique,
    storage_path text,
    file_hash text,
    status text not null default 'queued'
        check (status in ('queued', 'generated', 'delivered', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    lease_token uuid,
    lease_expires_at timestamptz,
    available_at timestamptz not null default now(),
    generated_at timestamptz,
    delivered_at timestamptz,
    delivery_channel text,
    delivery_reference text,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id),
    unique (business_id, transaction_id)
);

create table public.agentcard_refunds (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    transaction_id uuid not null,
    payment_id uuid not null,
    provider_refund_id text unique,
    amount_minor bigint not null check (amount_minor > 0),
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    reason text,
    status text not null check (status in ('pending', 'completed', 'failed', 'reconciliation')),
    idempotency_key text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    foreign key (business_id, transaction_id)
        references public.agentcard_transactions(business_id, id),
    foreign key (business_id, transaction_id, payment_id)
        references public.agentcard_payments(business_id, transaction_id, id),
    unique (business_id, transaction_id, idempotency_key)
);

create index agentcard_transactions_conversation_idx
    on public.agentcard_transactions (business_id, conversation_id, created_at desc);
create index agentcard_transactions_expiry_idx
    on public.agentcard_transactions (expires_at)
    where status in ('awaiting_customer', 'awaiting_payment', 'payment_failed');
create index agentcard_receipts_queue_idx
    on public.agentcard_receipts (available_at, created_at)
    where status in ('queued', 'generated', 'failed');
create index agentcard_refunds_queue_idx
    on public.agentcard_refunds (updated_at)
    where status in ('pending', 'reconciliation');

alter table public.agentcard_transactions enable row level security;
alter table public.agentcard_transaction_items enable row level security;
alter table public.agentcard_checkout_sessions enable row level security;
alter table public.agentcard_authorizations enable row level security;
alter table public.agentcard_payments enable row level security;
alter table public.agentcard_webhook_events enable row level security;
alter table public.agentcard_receipts enable row level security;
alter table public.agentcard_refunds enable row level security;

revoke all on public.agentcard_transactions from public, anon, authenticated;
revoke all on public.agentcard_transaction_items from public, anon, authenticated;
revoke all on public.agentcard_checkout_sessions from public, anon, authenticated;
revoke all on public.agentcard_authorizations from public, anon, authenticated;
revoke all on public.agentcard_payments from public, anon, authenticated;
revoke all on public.agentcard_webhook_events from public, anon, authenticated;
revoke all on public.agentcard_receipts from public, anon, authenticated;
revoke all on public.agentcard_refunds from public, anon, authenticated;
grant all on public.agentcard_transactions to service_role;
grant all on public.agentcard_transaction_items to service_role;
grant all on public.agentcard_checkout_sessions to service_role;
grant all on public.agentcard_authorizations to service_role;
grant all on public.agentcard_payments to service_role;
grant all on public.agentcard_webhook_events to service_role;
grant all on public.agentcard_receipts to service_role;
grant all on public.agentcard_refunds to service_role;
grant select on public.agentcard_transactions to authenticated;
grant select on public.agentcard_transaction_items to authenticated;
grant select on public.agentcard_payments to authenticated;
grant select on public.agentcard_receipts to authenticated;
grant select on public.agentcard_refunds to authenticated;

create policy "business members can read AgentCard transactions"
on public.agentcard_transactions for select to authenticated
using (public.is_business_member(business_id));
create policy "business members can read AgentCard items"
on public.agentcard_transaction_items for select to authenticated
using (public.is_business_member(business_id));
create policy "business members can read AgentCard receipts"
on public.agentcard_receipts for select to authenticated
using (public.is_business_member(business_id));
create policy "business members can read AgentCard payments"
on public.agentcard_payments for select to authenticated
using (public.is_business_member(business_id));
create policy "business members can read AgentCard refunds"
on public.agentcard_refunds for select to authenticated
using (public.is_business_member(business_id));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('agentcard-receipts', 'agentcard-receipts', false, 5242880, array['application/pdf'])
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.create_agentcard_transaction(
    target_business_id uuid,
    target_conversation_id uuid,
    target_customer_name text,
    target_customer_reference text,
    requested_items jsonb,
    requested_idempotency_key text,
    requested_payload_hash text,
    requested_transaction_id text,
    requested_checkout_id text,
    requested_token_hash text,
    requested_provider_integration_id uuid,
    requested_expires_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    current_transaction public.agentcard_transactions;
    current_session public.agentcard_checkout_sessions;
    business_row public.businesses;
    product_row public.products;
    integration_row public.integrations;
    requested_item jsonb;
    item_product_id uuid;
    item_quantity integer;
    item_total bigint;
    calculated_subtotal bigint := 0;
    transaction_currency char(3);
    item_snapshot jsonb := '[]'::jsonb;
    result_snapshot jsonb;
    transaction_row public.agentcard_transactions;
    session_row public.agentcard_checkout_sessions;
    order_row public.orders;
    reserved boolean;
    item_count integer := 0;
begin
    if requested_idempotency_key is null or char_length(requested_idempotency_key) not between 1 and 200
       or requested_payload_hash !~ '^[a-f0-9]{64}$'
       or requested_token_hash !~ '^[a-f0-9]{64}$'
       or requested_transaction_id !~ '^txn_[A-Za-z0-9_-]{20,80}$'
       or requested_checkout_id !~ '^chk_[A-Za-z0-9_-]{20,80}$'
       or requested_expires_at <= now()
       or requested_expires_at > now() + interval '2 hours'
       or jsonb_typeof(requested_items) <> 'array'
       or jsonb_array_length(requested_items) not between 1 and 100
       or char_length(btrim(coalesce(target_customer_name, ''))) not between 1 and 160 then
        raise exception 'invalid AgentCard request' using errcode = '22023';
    end if;

    select * into business_row from public.businesses
    where id = target_business_id;
    if not found or not exists (
        select 1
        from public.conversations
        where business_id = target_business_id
          and id = target_conversation_id
          and status <> 'resolved'
    ) then
        raise exception 'business conversation unavailable' using errcode = 'P0002';
    end if;

    if not exists (
        select 1
        from public.agent_configs
        where business_id = target_business_id
          and enabled
          and coalesce((permissions ->> 'create_carts_and_orders')::boolean, false)
          and coalesce((permissions ->> 'create_paypal_checkout')::boolean, false)
    ) then
        raise exception 'AgentCard is not permitted' using errcode = '42501';
    end if;
    select * into integration_row
    from public.integrations
    where business_id = target_business_id
      and id = requested_provider_integration_id
      and provider = 'paypal'
      and category = 'payments'
      and status = 'connected'
      and credentials_ciphertext is not null;
    if not found then
        raise exception 'PayPal merchant integration unavailable' using errcode = 'P0002';
    end if;

    select * into current_transaction
    from public.agentcard_transactions
    where business_id = target_business_id
      and idempotency_key = requested_idempotency_key
    for update;
    if found then
        if current_transaction.request_hash <> requested_payload_hash
           or current_transaction.conversation_id <> target_conversation_id then
            raise exception 'AgentCard idempotency conflict' using errcode = '23505';
        end if;
        if current_transaction.status not in ('awaiting_customer', 'awaiting_payment')
           or current_transaction.expires_at <= now() then
            raise exception 'AgentCard transaction is no longer reusable' using errcode = '23505';
        end if;
        update public.agentcard_checkout_sessions
        set status = 'revoked', revoked_at = now()
        where business_id = target_business_id
          and transaction_id = current_transaction.id
          and status = 'active';
        insert into public.agentcard_checkout_sessions (
            business_id, transaction_id, checkout_id, token_hash, expires_at
        ) values (
            target_business_id, current_transaction.id, requested_checkout_id,
            requested_token_hash, current_transaction.expires_at
        ) returning * into session_row;
        return jsonb_build_object(
            'transaction_id', current_transaction.id,
            'public_transaction_id', current_transaction.public_transaction_id,
            'order_id', current_transaction.order_id,
            'checkout_id', session_row.checkout_id,
            'expires_at', current_transaction.expires_at,
            'status', current_transaction.status,
            'snapshot', current_transaction.checkout_snapshot
        );
    end if;

    for requested_item in select value from jsonb_array_elements(requested_items)
    loop
        item_count := item_count + 1;
        if jsonb_typeof(requested_item) <> 'object'
           or coalesce(requested_item ->> 'product_id', '') !~* '^[0-9a-f-]{36}$'
           or coalesce(requested_item ->> 'quantity', '') !~ '^[0-9]{1,5}$' then
            raise exception 'invalid AgentCard item' using errcode = '22023';
        end if;
        item_product_id := (requested_item ->> 'product_id')::uuid;
        item_quantity := (requested_item ->> 'quantity')::integer;
        if item_quantity not between 1 and 10000 or exists (
            select 1
            from jsonb_array_elements(item_snapshot) as prior(value)
            where prior.value ->> 'product_id' = item_product_id::text
        ) then
            raise exception 'invalid AgentCard quantity or duplicate product' using errcode = '22023';
        end if;

        select * into product_row
        from public.products
        where business_id = target_business_id
          and id = item_product_id
          and status = 'active'
          and agent_enabled
        for update;
        if not found then
            raise exception 'AgentCard product unavailable' using errcode = 'P0002';
        end if;
        if product_row.stock_quantity is not null and product_row.stock_quantity < item_quantity then
            raise exception 'AgentCard product is out of stock' using errcode = '23514';
        end if;
        if item_count = 1 then
            transaction_currency := product_row.currency;
        elsif transaction_currency <> product_row.currency then
            raise exception 'AgentCard products must use one currency' using errcode = '22023';
        end if;
        item_total := product_row.price_minor * item_quantity;
        calculated_subtotal := calculated_subtotal + item_total;
        reserved := product_row.stock_quantity is not null;
        if reserved then
            update public.products
            set stock_quantity = stock_quantity - item_quantity,
                updated_at = now()
            where business_id = target_business_id
              and id = item_product_id;
        end if;
        item_snapshot := item_snapshot || jsonb_build_array(jsonb_build_object(
            'product_id', product_row.id,
            'name', product_row.name,
            'description', left(coalesce(product_row.description, ''), 2000),
            'image_asset_ids', product_row.image_asset_ids,
            'provider_image_urls', case
                when jsonb_typeof(product_row.provider_data -> 'image_urls') = 'array'
                then product_row.provider_data -> 'image_urls'
                else '[]'::jsonb
            end,
            'quantity', item_quantity,
            'unit_price_minor', product_row.price_minor,
            'total_minor', item_total
        ));
    end loop;

    if calculated_subtotal <= 0 then
        raise exception 'AgentCard checkout total must be positive' using errcode = '22023';
    end if;
    if transaction_currency <> 'USD' then
        raise exception 'PayPal AgentCard currently supports USD only' using errcode = '22023';
    end if;
    result_snapshot := jsonb_build_object(
        'business', jsonb_build_object('name', business_row.name, 'country', business_row.country),
        'items', item_snapshot,
        'subtotal_minor', calculated_subtotal,
        'discount_total_minor', 0,
        'tax_total_minor', 0,
        'delivery_total_minor', 0,
        'total_amount_minor', calculated_subtotal,
        'currency', transaction_currency
    );

    insert into public.orders (
        business_id, customer_name, status, payment_status,
        amount_minor, currency
    ) values (
        target_business_id, left(btrim(target_customer_name), 160), 'pending',
        'unpaid', calculated_subtotal, transaction_currency
    ) returning * into order_row;

    insert into public.agentcard_transactions (
        public_transaction_id, business_id, order_id, conversation_id,
        customer_name, customer_reference, provider, provider_integration_id,
        currency, subtotal_minor, total_amount_minor, checkout_snapshot,
        idempotency_key, request_hash, expires_at
    ) values (
        requested_transaction_id, target_business_id, order_row.id,
        target_conversation_id, left(btrim(target_customer_name), 160),
        left(target_customer_reference, 255), 'paypal', requested_provider_integration_id,
        transaction_currency, calculated_subtotal, calculated_subtotal,
        result_snapshot, requested_idempotency_key, requested_payload_hash,
        requested_expires_at
    ) returning * into transaction_row;

    for requested_item in select value from jsonb_array_elements(item_snapshot)
    loop
        insert into public.agentcard_transaction_items (
            business_id, transaction_id, product_id, product_name, description,
            image_asset_ids, quantity, unit_price_minor, total_minor, stock_reserved
        ) values (
            target_business_id, transaction_row.id,
            (requested_item ->> 'product_id')::uuid,
            requested_item ->> 'name',
            requested_item ->> 'description',
            array(select jsonb_array_elements_text(requested_item -> 'image_asset_ids')::uuid),
            (requested_item ->> 'quantity')::integer,
            (requested_item ->> 'unit_price_minor')::bigint,
            (requested_item ->> 'total_minor')::bigint,
            exists (
                select 1 from public.products
                where business_id = target_business_id
                  and id = (requested_item ->> 'product_id')::uuid
                  and stock_quantity is not null
            )
        );
        insert into public.order_items (
            business_id, order_id, product_id, product_name,
            quantity, unit_price_minor, total_minor
        ) values (
            target_business_id, order_row.id,
            (requested_item ->> 'product_id')::uuid,
            requested_item ->> 'name',
            (requested_item ->> 'quantity')::integer,
            (requested_item ->> 'unit_price_minor')::bigint,
            (requested_item ->> 'total_minor')::bigint
        );
    end loop;

    insert into public.agentcard_checkout_sessions (
        business_id, transaction_id, checkout_id, token_hash, expires_at
    ) values (
        target_business_id, transaction_row.id, requested_checkout_id,
        requested_token_hash, requested_expires_at
    ) returning * into session_row;

    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        target_business_id, 'agentcard.transaction.created',
        'agentcard_transaction', transaction_row.id::text,
        jsonb_build_object(
            'conversation_id', target_conversation_id,
            'order_id', order_row.id,
            'total_amount_minor', calculated_subtotal,
            'currency', transaction_currency
        )
    );
    insert into public.outbox_events (
        business_id, event_type, topic, data, dedupe_key
    ) values (
        target_business_id, 'agentcard.transaction.created', 'orders',
        jsonb_build_object(
            'transaction_id', transaction_row.id,
            'public_transaction_id', transaction_row.public_transaction_id,
            'conversation_id', target_conversation_id,
            'status', transaction_row.status
        ),
        'agentcard-created:' || transaction_row.id::text
    );

    return jsonb_build_object(
        'transaction_id', transaction_row.id,
        'public_transaction_id', transaction_row.public_transaction_id,
        'order_id', order_row.id,
        'checkout_id', session_row.checkout_id,
        'expires_at', transaction_row.expires_at,
        'status', transaction_row.status,
        'snapshot', transaction_row.checkout_snapshot
    );
end;
$$;

create or replace function public.authorize_agentcard_checkout(
    requested_token_hash text,
    requested_checkout_hash text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    session_row public.agentcard_checkout_sessions;
    transaction_row public.agentcard_transactions;
    authorization_row public.agentcard_authorizations;
begin
    select * into session_row
    from public.agentcard_checkout_sessions
    where token_hash = requested_token_hash
    for update;
    if not found or session_row.status <> 'active'
       or session_row.expires_at <= now() then
        raise exception 'checkout unavailable' using errcode = 'P0002';
    end if;
    select * into transaction_row
    from public.agentcard_transactions
    where business_id = session_row.business_id
      and id = session_row.transaction_id
    for update;
    if transaction_row.status <> 'awaiting_customer'
       or transaction_row.expires_at <= now()
       or requested_checkout_hash !~ '^[a-f0-9]{64}$' then
        raise exception 'checkout unavailable' using errcode = 'P0002';
    end if;
    insert into public.agentcard_authorizations (
        business_id, transaction_id, checkout_session_id,
        checkout_hash, checkout_snapshot, customer_approval_method
    ) values (
        transaction_row.business_id, transaction_row.id, session_row.id,
        requested_checkout_hash, transaction_row.checkout_snapshot,
        'explicit_checkout_button'
    )
    on conflict (business_id, checkout_session_id) do nothing
    returning * into authorization_row;
    if authorization_row.id is null then
        select * into authorization_row
        from public.agentcard_authorizations
        where business_id = transaction_row.business_id
          and checkout_session_id = session_row.id;
        if authorization_row.checkout_hash <> requested_checkout_hash then
            raise exception 'checkout authorization conflict' using errcode = '23505';
        end if;
    end if;
    update public.agentcard_checkout_sessions
    set authorization_id = authorization_row.id
    where id = session_row.id and business_id = session_row.business_id;
    update public.agentcard_transactions
    set status = 'awaiting_payment', updated_at = now()
    where id = transaction_row.id and business_id = transaction_row.business_id;
    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        transaction_row.business_id, 'agentcard.customer.authorized',
        'agentcard_transaction', transaction_row.id::text,
        jsonb_build_object(
            'authorization_id', authorization_row.id,
            'authorization_version', authorization_row.authorization_version,
            'checkout_hash', authorization_row.checkout_hash
        )
    );
    return jsonb_build_object(
        'authorization_id', authorization_row.id,
        'transaction_id', transaction_row.id,
        'status', 'awaiting_payment'
    );
end;
$$;

create or replace function public.start_agentcard_payment_attempt(
    target_transaction_id uuid,
    target_provider_order_id text,
    target_approval_url text,
    target_amount_minor bigint,
    target_currency text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    transaction_row public.agentcard_transactions;
    payment_row public.agentcard_payments;
begin
    select * into transaction_row
    from public.agentcard_transactions
    where id = target_transaction_id
    for update;
    if not found or transaction_row.status not in ('awaiting_payment', 'payment_failed')
       or transaction_row.expires_at <= now()
       or target_amount_minor <> transaction_row.total_amount_minor
       or target_currency <> transaction_row.currency then
        raise exception 'payment attempt unavailable' using errcode = 'P0002';
    end if;
    insert into public.agentcard_payments (
        business_id, transaction_id, provider, provider_order_id,
        approval_url, provider_status, status, amount_minor, currency
    ) values (
        transaction_row.business_id, transaction_row.id, 'paypal',
        target_provider_order_id, target_approval_url, 'CREATED', 'created',
        transaction_row.total_amount_minor, transaction_row.currency
    ) returning * into payment_row;
    update public.agentcard_transactions
    set status = 'payment_processing', updated_at = now(), failure_reason = null
    where id = transaction_row.id and business_id = transaction_row.business_id;
    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        transaction_row.business_id, 'agentcard.payment.started',
        'agentcard_transaction', transaction_row.id::text,
        jsonb_build_object('payment_id', payment_row.id, 'provider', 'paypal')
    );
    return jsonb_build_object('payment_id', payment_row.id, 'status', 'payment_processing');
end;
$$;

create or replace function public.record_agentcard_payment_result(
    target_provider_order_id text,
    target_provider_capture_id text,
    target_provider_status text,
    target_amount_minor bigint,
    target_currency text,
    provider_result_verified boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    payment_row public.agentcard_payments;
    transaction_row public.agentcard_transactions;
    mismatch boolean;
    mapped_status text;
    receipt_code text;
begin
    select * into payment_row
    from public.agentcard_payments
    where provider = 'paypal'
      and provider_order_id = target_provider_order_id
    for update;
    if not found then
        raise exception 'payment attempt unavailable' using errcode = 'P0002';
    end if;
    select * into transaction_row
    from public.agentcard_transactions
    where business_id = payment_row.business_id
      and id = payment_row.transaction_id
    for update;
    if not found then
        raise exception 'transaction unavailable' using errcode = 'P0002';
    end if;

    mismatch := target_amount_minor <> transaction_row.total_amount_minor
        or target_currency <> transaction_row.currency;
    if target_provider_status = 'COMPLETED' and
       (not provider_result_verified or mismatch or target_provider_capture_id is null) then
        mapped_status := 'reconciliation';
    elsif target_provider_status = 'COMPLETED' then
        mapped_status := 'completed';
    elsif target_provider_status in ('PENDING', 'PAYER_ACTION_REQUIRED') then
        mapped_status := 'pending';
    elsif target_provider_status in ('DENIED', 'DECLINED', 'FAILED', 'VOIDED') then
        mapped_status := 'failed';
    else
        mapped_status := 'processing';
    end if;

    if mapped_status = 'completed'
       and transaction_row.status not in (
           'awaiting_payment', 'payment_processing', 'payment_pending',
           'payment_failed', 'reconciliation'
       ) then
        mapped_status := 'reconciliation';
    end if;
    if mapped_status = 'completed' and exists (
        select 1
        from public.agentcard_payments other_payment
        where other_payment.business_id = payment_row.business_id
          and other_payment.transaction_id = payment_row.transaction_id
          and other_payment.id <> payment_row.id
          and other_payment.status = 'completed'
    ) then
        mapped_status := 'reconciliation';
    end if;

    if payment_row.status in ('completed', 'refunded') then
        return jsonb_build_object(
            'transaction_id', transaction_row.id,
            'status', transaction_row.status,
            'duplicate', true
        );
    end if;

    update public.agentcard_payments
    set provider_payment_id = coalesce(provider_payment_id, target_provider_order_id),
        provider_capture_id = coalesce(provider_capture_id, target_provider_capture_id),
        provider_status = target_provider_status,
        status = mapped_status,
        amount_minor = target_amount_minor,
        currency = target_currency,
        captured_at = case when mapped_status = 'completed' then now() else captured_at end,
        verified_at = case when provider_result_verified then now() else verified_at end,
        updated_at = now()
    where id = payment_row.id and business_id = payment_row.business_id;

    if mapped_status = 'completed' then
        update public.agentcard_transactions
        set status = 'paid', paid_at = now(), updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
        update public.orders
        set status = 'confirmed', payment_status = 'paid', updated_at = now()
        where business_id = transaction_row.business_id and id = transaction_row.order_id;
        update public.agentcard_checkout_sessions
        set status = 'completed', completed_at = now()
        where business_id = transaction_row.business_id
          and transaction_id = transaction_row.id and status = 'active';
        receipt_code := 'rcpt_' || replace(transaction_row.id::text, '-', '');
        insert into public.agentcard_receipts (
            business_id, transaction_id, receipt_number, status
        ) values (
            transaction_row.business_id, transaction_row.id, receipt_code, 'queued'
        )
        on conflict (business_id, transaction_id) do nothing;
        insert into public.outbox_events (
            business_id, event_type, topic, data, dedupe_key
        ) values (
            transaction_row.business_id, 'agentcard.payment.completed', 'orders',
            jsonb_build_object(
                'transaction_id', transaction_row.id,
                'public_transaction_id', transaction_row.public_transaction_id,
                'conversation_id', transaction_row.conversation_id,
                'order_id', transaction_row.order_id,
                'provider', 'paypal',
                'provider_capture_id', target_provider_capture_id,
                'amount_minor', transaction_row.total_amount_minor,
                'currency', transaction_row.currency,
                'verified_at', now()
            ),
            'agentcard-payment-completed:' || transaction_row.id::text
        )
        on conflict (business_id, dedupe_key) do nothing;
        insert into public.audit_events (
            business_id, event_type, resource_type, resource_id, data
        ) values (
            transaction_row.business_id, 'agentcard.payment.verified',
            'agentcard_transaction', transaction_row.id::text,
            jsonb_build_object(
                'payment_id', payment_row.id,
                'provider_capture_id', target_provider_capture_id,
                'amount_minor', transaction_row.total_amount_minor,
                'currency', transaction_row.currency
            )
        );
    elsif mapped_status = 'pending' then
        update public.agentcard_transactions
        set status = 'payment_pending', updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    elsif mapped_status = 'failed' then
        update public.agentcard_transactions
        set status = 'payment_failed', failure_reason = 'provider_declined', updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    elsif mapped_status = 'reconciliation' then
        update public.agentcard_transactions
        set status = 'reconciliation', failure_reason = 'provider_result_mismatch', updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    else
        update public.agentcard_transactions
        set status = 'payment_processing', updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    end if;
    return jsonb_build_object(
        'transaction_id', transaction_row.id,
        'status', case
            when mapped_status = 'completed' then 'paid'
            when mapped_status = 'processing' then 'payment_processing'
            else mapped_status
        end,
        'duplicate', false
    );
end;
$$;

create or replace function public.start_agentcard_refund(
    target_business_id uuid,
    target_transaction_id uuid,
    target_idempotency_key text,
    target_amount_minor bigint,
    target_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    transaction_row public.agentcard_transactions;
    payment_row public.agentcard_payments;
    refund_row public.agentcard_refunds;
    reserved_amount bigint;
    available_amount bigint;
    normalized_reason text := nullif(left(btrim(coalesce(target_reason, '')), 500), '');
begin
    if target_idempotency_key is null
       or char_length(target_idempotency_key) not between 1 and 200
       or target_amount_minor is null
       or target_amount_minor <= 0 then
        raise exception 'invalid AgentCard refund request' using errcode = '22023';
    end if;
    select * into transaction_row
    from public.agentcard_transactions
    where business_id = target_business_id and id = target_transaction_id
    for update;
    if not found then
        raise exception 'AgentCard transaction is not refundable' using errcode = 'P0002';
    end if;
    select * into refund_row
    from public.agentcard_refunds
    where business_id = target_business_id
      and transaction_id = target_transaction_id
      and idempotency_key = target_idempotency_key;
    if found then
        if refund_row.amount_minor <> target_amount_minor
           or refund_row.reason is distinct from normalized_reason then
            raise exception 'AgentCard refund idempotency conflict' using errcode = '23505';
        end if;
        return jsonb_build_object(
            'refund_id', refund_row.id,
            'provider_refund_id', refund_row.provider_refund_id,
            'amount_minor', refund_row.amount_minor,
            'status', refund_row.status
        );
    end if;
    if transaction_row.status not in (
        'paid', 'receipt_issued', 'receipt_delivered', 'partially_refunded'
    ) then
        raise exception 'AgentCard transaction is not refundable' using errcode = 'P0002';
    end if;
    select * into payment_row
    from public.agentcard_payments
    where business_id = target_business_id
      and transaction_id = target_transaction_id
      and status in ('completed', 'refunded')
    order by captured_at desc
    limit 1
    for update;
    if not found then
        raise exception 'completed AgentCard payment not found' using errcode = 'P0002';
    end if;
    select coalesce(sum(amount_minor), 0)::bigint into reserved_amount
    from public.agentcard_refunds
    where business_id = target_business_id
      and transaction_id = target_transaction_id
      and status in ('pending', 'completed', 'reconciliation');
    available_amount := transaction_row.total_amount_minor - reserved_amount;
    if target_amount_minor > available_amount then
        raise exception 'refund amount exceeds unrefunded balance' using errcode = '23514';
    end if;
    insert into public.agentcard_refunds (
        business_id, transaction_id, payment_id, amount_minor, currency,
        reason, status, idempotency_key
    ) values (
        target_business_id, target_transaction_id, payment_row.id,
        target_amount_minor, transaction_row.currency, normalized_reason,
        'pending', target_idempotency_key
    ) returning * into refund_row;
    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        target_business_id, 'agentcard.refund.started',
        'agentcard_refund', refund_row.id::text,
        jsonb_build_object(
            'transaction_id', target_transaction_id,
            'amount_minor', target_amount_minor,
            'currency', transaction_row.currency
        )
    );
    return jsonb_build_object(
        'refund_id', refund_row.id,
        'provider_refund_id', null,
        'amount_minor', refund_row.amount_minor,
        'status', refund_row.status
    );
end;
$$;

create or replace function public.record_agentcard_refund_result(
    target_refund_id uuid,
    target_provider_refund_id text,
    target_provider_status text,
    provider_result_verified boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    refund_row public.agentcard_refunds;
    transaction_row public.agentcard_transactions;
    payment_row public.agentcard_payments;
    completed_amount bigint;
    mapped_status text;
    full_refund boolean;
begin
    select * into refund_row
    from public.agentcard_refunds
    where id = target_refund_id
    for update;
    if not found then
        raise exception 'AgentCard refund not found' using errcode = 'P0002';
    end if;
    select * into transaction_row
    from public.agentcard_transactions
    where business_id = refund_row.business_id and id = refund_row.transaction_id
    for update;
    select * into payment_row
    from public.agentcard_payments
    where business_id = refund_row.business_id and id = refund_row.payment_id
    for update;
    if refund_row.status = 'completed' then
        return jsonb_build_object(
            'refund_id', refund_row.id,
            'status', transaction_row.status,
            'duplicate', true
        );
    end if;
    if target_provider_status = 'COMPLETED'
       and provider_result_verified
       and target_provider_refund_id is not null then
        mapped_status := 'completed';
    elsif target_provider_status in ('FAILED', 'CANCELLED', 'DENIED') then
        mapped_status := 'failed';
    elsif target_provider_status = 'COMPLETED' then
        mapped_status := 'reconciliation';
    else
        mapped_status := 'pending';
    end if;
    update public.agentcard_refunds
    set provider_refund_id = coalesce(provider_refund_id, target_provider_refund_id),
        status = mapped_status,
        updated_at = now(),
        completed_at = case when mapped_status = 'completed' then now() else completed_at end
    where id = refund_row.id and business_id = refund_row.business_id;
    if mapped_status = 'completed' then
        select coalesce(sum(amount_minor), 0)::bigint into completed_amount
        from public.agentcard_refunds
        where business_id = refund_row.business_id
          and transaction_id = refund_row.transaction_id
          and status = 'completed';
        full_refund := completed_amount >= transaction_row.total_amount_minor;
        update public.agentcard_transactions
        set status = case when full_refund then 'refunded' else 'partially_refunded' end,
            updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
        update public.orders
        set payment_status = case when full_refund then 'refunded' else 'partially_refunded' end,
            status = case when full_refund then 'refunded' else status end,
            updated_at = now()
        where id = transaction_row.order_id and business_id = transaction_row.business_id;
        if full_refund then
            update public.agentcard_payments
            set status = 'refunded', updated_at = now()
            where id = payment_row.id and business_id = payment_row.business_id;
        end if;
        insert into public.outbox_events (
            business_id, event_type, topic, data, dedupe_key
        ) values (
            refund_row.business_id, 'agentcard.refund.completed', 'orders',
            jsonb_build_object(
                'transaction_id', transaction_row.id,
                'refund_id', refund_row.id,
                'public_transaction_id', transaction_row.public_transaction_id,
                'amount_minor', refund_row.amount_minor,
                'currency', refund_row.currency,
                'full_refund', full_refund
            ),
            'agentcard-refund-completed:' || refund_row.id::text
        )
        on conflict (business_id, dedupe_key) do nothing;
    elsif mapped_status = 'reconciliation' then
        update public.agentcard_transactions
        set status = 'reconciliation', failure_reason = 'refund_result_mismatch', updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    elsif mapped_status = 'failed' and transaction_row.status = 'reconciliation' then
        select coalesce(sum(amount_minor), 0)::bigint into completed_amount
        from public.agentcard_refunds
        where business_id = refund_row.business_id
          and transaction_id = refund_row.transaction_id
          and status = 'completed';
        update public.agentcard_transactions
        set status = case
                when completed_amount >= transaction_row.total_amount_minor then 'refunded'
                when completed_amount > 0 then 'partially_refunded'
                else 'paid'
            end,
            failure_reason = null,
            updated_at = now()
        where id = transaction_row.id and business_id = transaction_row.business_id;
    end if;
    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        refund_row.business_id, 'agentcard.refund.' || mapped_status,
        'agentcard_refund', refund_row.id::text,
        jsonb_build_object(
            'provider_refund_id', target_provider_refund_id,
            'amount_minor', refund_row.amount_minor,
            'currency', refund_row.currency
        )
    );
    return jsonb_build_object(
        'refund_id', refund_row.id,
        'status', case when full_refund then 'refunded'
                       when mapped_status = 'completed' then 'partially_refunded'
                       else mapped_status end,
        'duplicate', false
    );
end;
$$;

create or replace function public.cancel_agentcard_transaction(
    target_business_id uuid,
    target_transaction_id uuid,
    cancellation_source text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    transaction_row public.agentcard_transactions;
    item_row public.agentcard_transaction_items;
begin
    select * into transaction_row
    from public.agentcard_transactions
    where business_id = target_business_id and id = target_transaction_id
    for update;
    if not found then
        return false;
    end if;
    if transaction_row.status not in ('awaiting_customer', 'awaiting_payment', 'payment_failed') then
        return false;
    end if;
    for item_row in
        select * from public.agentcard_transaction_items
        where business_id = target_business_id
          and transaction_id = target_transaction_id
          and stock_reserved
    loop
        update public.products
        set stock_quantity = stock_quantity + item_row.quantity,
            updated_at = now()
        where business_id = target_business_id
          and id = item_row.product_id
          and stock_quantity is not null;
    end loop;
    update public.agentcard_transactions
    set status = case when cancellation_source = 'expiry' then 'expired' else 'cancelled' end,
        cancelled_at = case when cancellation_source = 'expiry' then cancelled_at else now() end,
        updated_at = now()
    where id = target_transaction_id and business_id = target_business_id;
    update public.orders
    set status = 'cancelled', updated_at = now()
    where business_id = target_business_id and id = transaction_row.order_id
      and payment_status = 'unpaid';
    update public.agentcard_checkout_sessions
    set status = case when cancellation_source = 'expiry' then 'expired' else 'revoked' end,
        revoked_at = now()
    where business_id = target_business_id
      and transaction_id = target_transaction_id
      and status = 'active';
    insert into public.audit_events (
        business_id, event_type, resource_type, resource_id, data
    ) values (
        target_business_id,
        case when cancellation_source = 'expiry' then 'agentcard.transaction.expired' else 'agentcard.transaction.cancelled' end,
        'agentcard_transaction', target_transaction_id::text,
        jsonb_build_object('source', cancellation_source)
    );
    return true;
end;
$$;

create or replace function public.claim_agentcard_receipt()
returns setof public.agentcard_receipts
language plpgsql
security definer
set search_path = ''
as $$
declare
    receipt_row public.agentcard_receipts;
begin
    select * into receipt_row
    from public.agentcard_receipts
    where available_at <= now()
      and (
          status in ('queued', 'failed')
          or (status = 'generated' and (lease_expires_at is null or lease_expires_at <= now()))
      )
    order by available_at, created_at
    limit 1
    for update skip locked;
    if not found then
        return;
    end if;
    update public.agentcard_receipts
    set attempts = attempts + 1,
        lease_token = gen_random_uuid(),
        lease_expires_at = now() + interval '5 minutes',
        status = case when receipt_row.storage_path is null then 'queued' else 'generated' end,
        updated_at = now()
    where id = receipt_row.id
    returning * into receipt_row;
    return next receipt_row;
end;
$$;

create or replace function public.expire_agentcard_transactions()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    transaction_row public.agentcard_transactions;
    expired_count integer := 0;
begin
    for transaction_row in
        select * from public.agentcard_transactions
        where status in ('awaiting_customer', 'awaiting_payment', 'payment_failed')
          and expires_at <= now()
        order by expires_at
        limit 100
        for update skip locked
    loop
        if public.cancel_agentcard_transaction(
            transaction_row.business_id, transaction_row.id, 'expiry'
        ) then
            expired_count := expired_count + 1;
        end if;
    end loop;
    return expired_count;
end;
$$;

revoke all on function public.create_agentcard_transaction(uuid, uuid, text, text, jsonb, text, text, text, text, text, uuid, timestamptz) from public, anon, authenticated;
revoke all on function public.authorize_agentcard_checkout(text, text) from public, anon, authenticated;
revoke all on function public.start_agentcard_payment_attempt(uuid, text, text, bigint, text) from public, anon, authenticated;
revoke all on function public.record_agentcard_payment_result(text, text, text, bigint, text, boolean) from public, anon, authenticated;
revoke all on function public.start_agentcard_refund(uuid, uuid, text, bigint, text) from public, anon, authenticated;
revoke all on function public.record_agentcard_refund_result(uuid, text, text, boolean) from public, anon, authenticated;
revoke all on function public.cancel_agentcard_transaction(uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.claim_agentcard_receipt() from public, anon, authenticated;
revoke all on function public.expire_agentcard_transactions() from public, anon, authenticated;
grant execute on function public.create_agentcard_transaction(uuid, uuid, text, text, jsonb, text, text, text, text, text, uuid, timestamptz) to service_role;
grant execute on function public.authorize_agentcard_checkout(text, text) to service_role;
grant execute on function public.start_agentcard_payment_attempt(uuid, text, text, bigint, text) to service_role;
grant execute on function public.record_agentcard_payment_result(text, text, text, bigint, text, boolean) to service_role;
grant execute on function public.start_agentcard_refund(uuid, uuid, text, bigint, text) to service_role;
grant execute on function public.record_agentcard_refund_result(uuid, text, text, boolean) to service_role;
grant execute on function public.cancel_agentcard_transaction(uuid, uuid, text) to service_role;
grant execute on function public.claim_agentcard_receipt() to service_role;
grant execute on function public.expire_agentcard_transactions() to service_role;
