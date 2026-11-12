create or replace function public.notify_agentcard_sale()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    transaction_row public.agentcard_transactions;
    notification_id uuid;
    owner_thread_id uuid;
    owner_message_id uuid;
    amount_text text;
    message_text text;
begin
    select *
    into transaction_row
    from public.agentcard_transactions
    where business_id = new.business_id
      and id = new.transaction_id;

    if not found then
        raise exception 'AgentCard transaction unavailable' using errcode = 'P0002';
    end if;

    if not coalesce(
        (
            select (settings.notifications->>'payment_updates')::boolean
            from public.business_settings settings
            where settings.business_id = new.business_id
        ),
        true
    ) then
        return new;
    end if;

    amount_text := transaction_row.currency::text || ' ' ||
        to_char(transaction_row.total_amount_minor::numeric / 100, 'FM999999999999990.00');
    message_text := format(
        'Verified AgentCard payment received. Amount: %s. Receipt: %s. Transaction reference: %s. Check the current status with list_agentcard_transactions before reporting any further details.',
        amount_text,
        new.receipt_number,
        transaction_row.public_transaction_id
    );

    insert into public.notifications (
        business_id, type, title, body, data
    )
    values (
        new.business_id,
        'agentcard_sale',
        'Payment received',
        format('Verified payment of %s. Receipt %s.', amount_text, new.receipt_number),
        jsonb_build_object(
            'transaction_id', transaction_row.id,
            'public_transaction_id', transaction_row.public_transaction_id,
            'order_id', transaction_row.order_id,
            'receipt_number', new.receipt_number,
            'amount_minor', transaction_row.total_amount_minor,
            'currency', transaction_row.currency
        )
    )
    returning id into notification_id;

    insert into public.outbox_events (
        business_id, event_type, topic, data, dedupe_key
    )
    values (
        new.business_id,
        'notification.agentcard_sale',
        'notifications',
        jsonb_build_object('notification_id', notification_id),
        'agentcard-sale-notification:' || transaction_row.id::text
    )
    on conflict (business_id, dedupe_key) do nothing;

    insert into public.owner_threads (business_id)
    values (new.business_id)
    on conflict (business_id) do update set business_id = excluded.business_id
    returning id into owner_thread_id;

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
        new.business_id,
        owner_thread_id,
        'user',
        'payment-system',
        'Payment notification',
        'status_update',
        message_text,
        'agentcard-sale-event:' || transaction_row.id::text
    )
    on conflict (business_id, idempotency_key) do nothing
    returning id into owner_message_id;

    if owner_message_id is null then
        select id into owner_message_id
        from public.owner_messages
        where business_id = new.business_id
          and idempotency_key = 'agentcard-sale-event:' || transaction_row.id::text;
    end if;

    insert into public.agent_runs (business_id, status, input_message_id)
    values (new.business_id, 'queued', owner_message_id)
    on conflict (business_id, input_message_id) do nothing;

    insert into public.outbox_events (
        business_id, event_type, topic, data, dedupe_key
    )
    values (
        new.business_id,
        'owner_assistant.message_created',
        'owner_assistant',
        jsonb_build_object(
            'message_id', owner_message_id,
            'thread_id', owner_thread_id
        ),
        'owner-message:' || owner_message_id::text
    )
    on conflict (business_id, dedupe_key) do nothing;

    return new;
end;
$$;

revoke all on function public.notify_agentcard_sale() from public, anon, authenticated;

create trigger agentcard_receipts_notify_sale
after insert on public.agentcard_receipts
for each row execute function public.notify_agentcard_sale();
