-- 실시간 KOSPI · Yahoo Finance ^KS11 1분봉을 Supabase 안에서 1분마다 수집 (PC를 켜 둘 필요 없음)
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run (비밀문구 없음, 그대로 실행)

create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.kospi_ticks (
  ts         timestamptz primary key,
  price      numeric not null,
  prev_close numeric                  -- 전일 종가 (등락 계산용)
);
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
declare r record; body jsonb;
begin
  -- 1) 지난 회차 응답 저장
  for r in select q.id, h.status_code, h.content from public.kospi_req q join net._http_response h on h.id = q.id loop
    if r.status_code = 200 then
      body := r.content::jsonb -> 'chart' -> 'result' -> 0;
      insert into public.kospi_ticks (ts, price, prev_close)
      select to_timestamp(t.v::bigint), c.v::numeric, (body -> 'meta' ->> 'chartPreviousClose')::numeric
      from jsonb_array_elements_text(body -> 'timestamp') with ordinality t(v, i)
      join jsonb_array_elements_text(body -> 'indicators' -> 'quote' -> 0 -> 'close') with ordinality c(v, i) using (i)
      where c.v is not null
      on conflict (ts) do update set price = excluded.price, prev_close = excluded.prev_close;
    end if;
    delete from public.kospi_req where id = r.id;
  end loop;
  delete from public.kospi_req where at < now() - interval '10 minutes';
  delete from public.kospi_ticks where ts < now() - interval '14 days';
  -- 2) 다음 회차 요청
  insert into public.kospi_req (id) select net.http_get(
    'https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?interval=1m&range=1d',
    headers := '{"User-Agent": "Mozilla/5.0"}'::jsonb);
end $$;
revoke all on function public.kospi_collect() from public, anon, authenticated;

-- 평일 09:00~15:59 KST (= UTC 0~6시) 매분 실행
select cron.unschedule('kospi') where exists (select 1 from cron.job where jobname = 'kospi');
select cron.schedule('kospi', '* 0-6 * * 1-5', 'select public.kospi_collect()');
select public.kospi_collect();   -- 지금 한 번 요청 (장 마감 후에도 마지막 거래일 데이터가 들어옴)
