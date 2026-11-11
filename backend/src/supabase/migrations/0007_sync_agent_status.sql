update public.agent_configs
set status = case when enabled then 'active' else 'disabled' end
where status is distinct from case when enabled then 'active' else 'disabled' end;
