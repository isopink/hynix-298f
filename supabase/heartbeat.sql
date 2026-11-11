-- 11-11 S.Lee: 데스크톱 연결 신호 (대시보드 머리글 'Server' 점)
-- 데스크톱의 agent/src/sync.py 가 로그온부터 1분마다 push_heartbeat 를 부름 (장 밖에도).
-- 대시보드는 마지막 신호가 3분 안이면 초록 깜빡임, 넘으면 빨강 (PC 꺼짐 · 절전 · 인터넷 끊김).
-- Supabase SQL Editor 에서 한 번 실행. 비밀문구는 schema.sql 의 app_secret('snapshot') 을 그대로 씀.

create table if not exists public.heartbeat (
  host text primary key,
  ts timestamptz not null default now(),
  info jsonb not null default '{}'::jsonb
);

alter table public.heartbeat enable row level security;
drop policy if exists "heartbeat read" on public.heartbeat;
create policy "heartbeat read" on public.heartbeat for select to anon using (true);

create or replace function public.push_heartbeat(p_secret text, p_host text, p_info jsonb default '{}'::jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.app_secret where name = 'snapshot' and value = p_secret) then
    raise exception 'unauthorized';
  end if;
  insert into public.heartbeat (host, ts, info) values (left(p_host, 40), now(), coalesce(p_info, '{}'::jsonb))
  on conflict (host) do update set ts = excluded.ts, info = excluded.info;
end $$;
revoke all on function public.push_heartbeat(text, text, jsonb) from public;
grant execute on function public.push_heartbeat(text, text, jsonb) to anon;
