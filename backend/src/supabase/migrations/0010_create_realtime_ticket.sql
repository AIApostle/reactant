create or replace function public.create_realtime_ticket(
    target_business_id uuid,
    requested_token_hash text,
    requested_expires_at timestamptz
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    requesting_user_id uuid := auth.uid();
begin
    if requesting_user_id is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if requested_token_hash is null
       or requested_token_hash !~ '^[a-f0-9]{64}$'
       or requested_expires_at <= now()
       or requested_expires_at > now() + interval '2 minutes' then
        raise exception 'invalid realtime ticket request' using errcode = '22023';
    end if;
    if not exists (
        select 1
        from public.business_members member
        where member.business_id = target_business_id
          and member.user_id = requesting_user_id
    ) then
        raise exception 'business membership required' using errcode = '42501';
    end if;

    insert into public.realtime_tickets (
        token_hash,
        business_id,
        user_id,
        expires_at
    ) values (
        requested_token_hash,
        target_business_id,
        requesting_user_id,
        requested_expires_at
    );
end;
$$;

revoke all on function public.create_realtime_ticket(uuid, text, timestamptz)
from public, anon, authenticated;
grant execute on function public.create_realtime_ticket(uuid, text, timestamptz)
to authenticated;

notify pgrst, 'reload schema';
