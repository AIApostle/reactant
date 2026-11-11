alter table public.customer_messages
    add column attachments jsonb not null default '[]'::jsonb
    check (jsonb_typeof(attachments) = 'array');
