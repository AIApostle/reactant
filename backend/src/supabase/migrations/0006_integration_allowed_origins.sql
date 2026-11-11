alter table public.integrations
    add column if not exists allowed_origin text;

alter table public.integrations
    add constraint integrations_allowed_origin_provider_check
    check (allowed_origin is null or provider = 'website_chat');

grant select (allowed_origin) on public.integrations to authenticated;
grant insert (allowed_origin) on public.integrations to authenticated;
grant update (allowed_origin) on public.integrations to authenticated;
