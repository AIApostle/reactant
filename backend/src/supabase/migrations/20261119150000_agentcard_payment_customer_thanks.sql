alter table public.customer_agent_runs
    add column agentcard_transaction_id uuid,
    drop constraint customer_agent_runs_source_type_check,
    add constraint customer_agent_runs_source_type_check
        check (source_type in ('customer_message', 'telegram_update', 'agentcard_payment')),
    drop constraint customer_agent_runs_check,
    add constraint customer_agent_runs_source_payload_check
        check (
            (
                source_type = 'customer_message'
                and customer_message_id is not null
                and telegram_channel_id is null
                and telegram_provider_event_id is null
                and telegram_payload_ciphertext is null
                and agentcard_transaction_id is null
            )
            or (
                source_type = 'telegram_update'
                and customer_message_id is null
                and telegram_channel_id is not null
                and telegram_provider_event_id is not null
                and telegram_payload_ciphertext is not null
                and agentcard_transaction_id is null
            )
            or (
                source_type = 'agentcard_payment'
                and customer_message_id is null
                and telegram_channel_id is null
                and telegram_provider_event_id is null
                and telegram_payload_ciphertext is null
                and agentcard_transaction_id is not null
            )
        ),
    add constraint customer_agent_runs_payment_transaction_fk
        foreign key (business_id, agentcard_transaction_id)
        references public.agentcard_transactions(business_id, id)
        on delete cascade,
    add constraint customer_agent_runs_business_payment_key
        unique (business_id, agentcard_transaction_id);

create or replace function public.enqueue_agentcard_payment_customer_run()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    conversation_channel text;
begin
    select channel into conversation_channel
    from public.conversations
    where business_id = new.business_id
      and id = (
          select conversation_id
          from public.agentcard_transactions
          where business_id = new.business_id
            and id = new.transaction_id
      );

    if new.status <> 'delivered'
       and not (new.status = 'generated' and conversation_channel <> 'telegram') then
        return new;
    end if;

    insert into public.customer_agent_runs (
        business_id,
        source_type,
        agentcard_transaction_id
    )
    values (
        new.business_id,
        'agentcard_payment',
        new.transaction_id
    )
    on conflict (business_id, agentcard_transaction_id) do nothing;
    return new;
end;
$$;

revoke all on function public.enqueue_agentcard_payment_customer_run()
    from public, anon, authenticated;

create trigger agentcard_receipts_enqueue_customer_thanks
after update of status on public.agentcard_receipts
for each row execute function public.enqueue_agentcard_payment_customer_run();
