-- 실시간 KOSPI · 네이버 증권 1분봉을 Supabase 안에서 1분마다 수집 (PC를 켜 둘 필요 없음)
-- 11-02 Yahoo(^KS11, 약 20분 지연)에서 교체. 다시 실행해도 안전함
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run (비밀문구 없음, 그대로 실행)

create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.kospi_ticks (
  ts         timestamptz primary key,
  price      numeric not null,
  prev_close numeric                  -- 전일 종가 (등락 계산용)
);
alter table public.kospi_ticks add column if not exists volume bigint;   -- 1분 거래량
alter table public.kospi_ticks enable row level security;
revoke all on public.kospi_ticks from anon, authenticated;
grant select on public.kospi_ticks to anon;            -- 사이트는 읽기만
drop policy if exists "anyone reads kospi" on public.kospi_ticks;
create policy "anyone reads kospi" on public.kospi_ticks for select to anon using (true);

-- 보낸 요청 번호 (응답은 다음 회차에 꺼냄)
create table if not exists public.kospi_req (id bigint primary key, at timestamptz not null default now());
alter table public.kospi_req enable row level security;
revoke all on public.kospi_req from anon, authenticated;

create or replace function public.kospi_collect()
returns void language plpgsql security definer set search_path = public as $$
declare r record; kday text := to_char(now() at time zone 'Asia/Seoul', 'YYYYMMDD');
begin
  -- 1) 지난 회차 응답 저장. 네이버 증권 1분봉 (지연 없음, 오늘 09:00부터 전부, 15:3x 봉에 장 마감 종가 포함)
  for r in select q.id, h.status_code, h.content from public.kospi_req q join net._http_response h on h.id = q.id loop
    if r.status_code = 200 and jsonb_typeof(r.content::jsonb) = 'array' then
      insert into public.kospi_ticks (ts, price, prev_close, volume)
      select x.ts, x.price,
             -- 전일 종가 = 오늘 이전 마지막 행 (전일 마지막 1분봉이 곧 종가)
             (select k.price from public.kospi_ticks k where k.ts < date_trunc('day', x.ts at time zone 'Asia/Seoul') at time zone 'Asia/Seoul'
              order by k.ts desc limit 1),
             x.volume
      from (select to_timestamp((e ->> 'localDateTime') || ' +09', 'YYYYMMDDHH24MISS TZH') as ts,
                   (e ->> 'currentPrice')::numeric as price, (e ->> 'accumulatedTradingVolume')::bigint as volume
            from jsonb_array_elements(r.content::jsonb) e
            where e ->> 'currentPrice' is not null) x
      on conflict (ts) do update set price = excluded.price, volume = excluded.volume,
        prev_close = coalesce(public.kospi_ticks.prev_close, excluded.prev_close);
    end if;
    delete from public.kospi_req where id = r.id;
  end loop;
  delete from public.kospi_req where at < now() - interval '10 minutes';
  delete from public.kospi_ticks where ts < now() - interval '40 days';   -- 대회 기간(약 4주) 전체 보관
  -- 2) 다음 회차 요청
  insert into public.kospi_req (id) select net.http_get(
    format('https://api.stock.naver.com/chart/domestic/index/KOSPI/minute?startDateTime=%s0900&endDateTime=%s1600', kday, kday),
    headers := '{"User-Agent": "Mozilla/5.0"}'::jsonb);
end $$;
revoke all on function public.kospi_collect() from public, anon, authenticated;

-- 날짜별 종가 (대시보드 수익률 그래프의 KOSPI 예비값)
-- 1분봉 마지막 값엔 장 마감 동시호가가 빠져 있어서, 다음 거래일에 기록된 전일 종가를 우선 사용
create or replace view public.kospi_daily with (security_invoker = true) as
  with t as (select (ts at time zone 'Asia/Seoul')::date as d, ts, price, prev_close from public.kospi_ticks),
  last as (select distinct on (d) d, price from t order by d, ts desc),
  pc as (select d, max(prev_close) as prev_close from t group by d)
  select l.d as date,
         coalesce((select pc.prev_close from pc where pc.d > l.d order by pc.d limit 1), l.price) as close
  from last l;
grant select on public.kospi_daily to anon;

-- Yahoo 시절 1분봉 사이에 끼어 있던 실시간 중간값 정리 (네이버는 정각 1분봉만 있음)
delete from public.kospi_ticks where extract(second from ts) <> 0;

-- 평일 09:00~15:59 KST (= UTC 0~6시) 매분 실행
select cron.unschedule('kospi') where exists (select 1 from cron.job where jobname = 'kospi');
select cron.schedule('kospi', '* 0-6 * * 1-5', 'select public.kospi_collect()');
select public.kospi_collect();   -- 지금 한 번 요청 (장 마감 후에도 마지막 거래일 데이터가 들어옴)
