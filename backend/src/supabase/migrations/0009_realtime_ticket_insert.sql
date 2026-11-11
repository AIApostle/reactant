revoke insert on public.realtime_tickets from authenticated;
grant insert (token_hash, business_id, user_id, expires_at)
on public.realtime_tickets to authenticated;
