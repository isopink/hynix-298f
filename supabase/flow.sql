-- 실시간 KOSPI 투자자별 순매수 (외국인·기관·개인, 억 원, 장 시작부터 누적)
-- 다음 금융 "투자자별 매매동향 시간대별"을 Supabase 안에서 1분마다 받아 쌓음 (PC를 켜 둘 필요 없음)
-- 한 번 받으면 그날 09:01부터의 분별 기록이 전부 오므로, 빠진 분이 있어도 다음 회차에 채워짐
-- 11-02 네이버(현재 누적값 하나만 줌)에서 교체
--
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run (비밀문구 없음, 다시 실행해도 안전함)
-- 장 마감 뒤에 실행했다면 몇 초 뒤 아래 한 줄을 한 번 더 Run 해야 그날 기록이 들어감 (응답은 다음 호출 때 저장)
--   select public.flow_collect();

create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.investor_flow (
  ts            timestamptz primary key,   -- 분 (KST 09:00~15:45)
  foreign_net   numeric not null,          -- 외국인 누적 순매수 (억 원)
  inst_net      numeric not null,          -- 기관 누적 순매수 (억 원)
  personal_net  numeric not null           -- 개인 누적 순매수 (억 원)
);
alter table public.investor_flow enable row level security;
revoke all on public.investor_flow from anon, authenticated;
grant select on public.investor_flow to anon;          -- 사이트는 읽기만
drop policy if exists "anyone reads flow" on public.investor_flow;
create policy "anyone reads flow" on public.investor_flow for select to anon using (true);

-- 보낸 요청 번호 (응답은 다음 회차에 꺼냄)
create table if not exists public.flow_req (id bigint primary key, at timestamptz not null default now());
alter table public.flow_req enable row level security;
revoke all on public.flow_req from anon, authenticated;

create or replace function public.flow_collect()
returns void language plpgsql security definer set search_path = public as $$
declare r record; j jsonb;
begin
  -- 1) 지난 회차 응답 저장. data = [{date "YYYY-MM-DD HH:MM:SS", foreign/institution/individualStraightPurchasePrice (원)}]
  for r in select q.id, h.status_code, h.content from public.flow_req q join net._http_response h on h.id = q.id loop
    begin
      j := r.content::jsonb;
    exception when others then j := null;
    end;
    if r.status_code = 200 and jsonb_typeof(j -> 'data') = 'array' then
      insert into public.investor_flow (ts, foreign_net, inst_net, personal_net)
      select to_timestamp(e ->> 'date' || ' +09', 'YYYY-MM-DD HH24:MI:SS TZH'),
             round((e ->> 'foreignStraightPurchasePrice')::numeric / 1e8),
             round((e ->> 'institutionStraightPurchasePrice')::numeric / 1e8),
             round((e ->> 'individualStraightPurchasePrice')::numeric / 1e8)
      from jsonb_array_elements(j -> 'data') e
      where e ->> 'foreignStraightPurchasePrice' is not null
        and (e ->> 'date')::timestamp::time between '09:00' and '15:45'   -- 정규장 + 장 마감 확정값
      on conflict (ts) do update set foreign_net = excluded.foreign_net, inst_net = excluded.inst_net,
        personal_net = excluded.personal_net;
    end if;
    delete from public.flow_req where id = r.id;
  end loop;
  delete from public.flow_req where at < now() - interval '10 minutes';
  delete from public.investor_flow where ts < now() - interval '40 days';   -- 대회 기간(약 4주) 전체 보관
  -- 2) 다음 회차 요청 (Referer 가 없으면 다음 금융이 거절함)
  insert into public.flow_req (id) select net.http_get(
    'https://finance.daum.net/api/investor/KOSPI/times?page=1&perPage=500',
    headers := '{"User-Agent": "Mozilla/5.0", "Referer": "https://finance.daum.net/domestic/investors"}'::jsonb);
end $$;
revoke all on function public.flow_collect() from public, anon, authenticated;

-- 평일 09:00~15:59 KST (= UTC 0~6시) 매분 실행
select cron.unschedule('flow') where exists (select 1 from cron.job where jobname = 'flow');
select cron.schedule('flow', '* 0-6 * * 1-5', 'select public.flow_collect()');
select public.flow_collect();   -- 지금 한 번 요청
