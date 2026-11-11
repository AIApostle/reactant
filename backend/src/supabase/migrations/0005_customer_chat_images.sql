insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'customer-chat-media',
    'customer-chat-media',
    false,
    5242880,
    array['image/jpeg']
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy "business members can read customer chat images"
on storage.objects for select to authenticated
using (
    bucket_id = 'customer-chat-media'
    and public.is_business_member(
        public.try_uuid(split_part(name, '/', 1))
    )
);
