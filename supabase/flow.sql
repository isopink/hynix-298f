-- 실시간 KOSPI 투자자별 순매수 (외국인·기관·개인, 억 원, 장 시작부터 누적)
-- 네이버 증권 시세 요약을 Supabase 안에서 1분마다 받아 쌓음 (PC를 켜 둘 필요 없음)
-- 네이버는 "지금까지의 누적값"만 주므로 분별 기록은 이 수집이 시작된 뒤부터 쌓임
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run (비밀문구 없음, 다시 실행해도 안전함)

create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.investor_flow (
  ts            timestamptz primary key,   -- 요청한 분 (KST 09:00~15:45)
  foreign_net   numeric not null,          -- 외국인 누적 순매수 (억 원)
  inst_net      numeric not null,          -- 기관 누적 순매수 (억 원)
  personal_net  numeric not null           -- 개인 누적 순매수 (억 원)
);
alter table public.investor_flow enable row level security;
revoke all on public.investor_flow from anon, authenticated;
grant select on public.investor_flow to anon;          -- 사이트는 읽기만
drop policy if exists "anyone reads flow" on public.investor_flow;
create policy "anyone reads flow" on public.investor_flow for select to anon using (true);

-- 보낸 요청 번호와 보낸 시각 (응답은 다음 회차에 꺼냄)
create table if not exists public.flow_req (id bigint primary key, at timestamptz not null default now());
alter table public.flow_req enable row level security;
revoke all on public.flow_req from anon, authenticated;

create or replace function public.flow_collect()
returns void language plpgsql security definer set search_path = public as $$
declare r record; j jsonb; k timestamp; num text := '[^0-9.-]';
begin
  -- 1) 지난 회차 응답 저장
  for r in select q.id, q.at, h.status_code, h.content from public.flow_req q join net._http_response h on h.id = q.id loop
    k := r.at at time zone 'Asia/Seoul';
    begin
      j := r.content::jsonb;
    exception when others then j := null;
    end;
    -- 오늘 장중(09:00~15:45) 값만. 장 시작 전엔 전일 값이 오므로 bizdate 로 거름
    if r.status_code = 200 and j ? 'foreignValue' and j ->> 'bizdate' = to_char(k, 'YYYYMMDD')
       and k::time between '09:00' and '15:45' then
      insert into public.investor_flow (ts, foreign_net, inst_net, personal_net)
      values (date_trunc('minute', r.at),
              regexp_replace(j ->> 'foreignValue', num, '', 'g')::numeric,
              regexp_replace(j ->> 'institutionalValue', num, '', 'g')::numeric,
              regexp_replace(j ->> 'personalValue', num, '', 'g')::numeric)
      on conflict (ts) do update set foreign_net = excluded.foreign_net, inst_net = excluded.inst_net,
        personal_net = excluded.personal_net;
    end if;
    delete from public.flow_req where id = r.id;
  end loop;
  delete from public.flow_req where at < now() - interval '10 minutes';
  delete from public.investor_flow where ts < now() - interval '40 days';   -- 대회 기간(약 4주) 전체 보관
  -- 2) 다음 회차 요청
  insert into public.flow_req (id) select net.http_get(
    'https://m.stock.naver.com/api/index/KOSPI/trend',
    headers := '{"User-Agent": "Mozilla/5.0"}'::jsonb);
end $$;
revoke all on function public.flow_collect() from public, anon, authenticated;

-- 평일 09:00~15:59 KST (= UTC 0~6시) 매분 실행
select cron.unschedule('flow') where exists (select 1 from cron.job where jobname = 'flow');
select cron.schedule('flow', '* 0-6 * * 1-5', 'select public.flow_collect()');
select public.flow_collect();   -- 지금 한 번 요청
