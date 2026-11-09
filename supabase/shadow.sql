-- 11-09 S.Lee: 온톨로지 그림자 운영(가상 계좌)의 장중 1분 자산 + 실행 상태 → 대시보드 실시간 초록 선 · '온톨로지' 상태바
-- Supabase SQL Editor 에서 한 번 실행. 비밀문구는 schema.sql 의 app_secret('snapshot') 을 그대로 씀 (새 값 없음)
-- 쓰는 쪽: live/snapshot.py (실제 잔고 1분 루프)가 그림자 폴더의 agent/work/shadow_live.json 을 읽어 올림. 키움 호출 없음

create table if not exists public.shadow_snapshots (
  id bigserial primary key,
  ts timestamptz not null default now(),
  total bigint,
  cash bigint,
  holdings jsonb not null default '[]'::jsonb,
  status jsonb not null default '{}'::jsonb
);
create index if not exists shadow_snapshots_ts_idx on public.shadow_snapshots (ts);

alter table public.shadow_snapshots enable row level security;
revoke all on public.shadow_snapshots from anon, authenticated;
grant select on public.shadow_snapshots to anon;            -- 사이트는 읽기만
drop policy if exists "anyone reads shadow snapshots" on public.shadow_snapshots;
create policy "anyone reads shadow snapshots" on public.shadow_snapshots for select to anon using (true);

create or replace function public.push_shadow(
  p_secret text, p_total bigint, p_cash bigint, p_holdings jsonb, p_status jsonb
) returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.app_secret where name = 'snapshot' and value = p_secret) then
    raise exception 'unauthorized';
  end if;
  insert into public.shadow_snapshots (total, cash, holdings, status)
  values (p_total, p_cash, coalesce(p_holdings, '[]'::jsonb), coalesce(p_status, '{}'::jsonb));
end $$;
revoke all on function public.push_shadow(text, bigint, bigint, jsonb, jsonb) from public;
grant execute on function public.push_shadow(text, bigint, bigint, jsonb, jsonb) to anon;
