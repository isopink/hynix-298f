-- 밤사이 지표 · EWY(미국 상장 한국 ETF)를 미국장 시간(프리·애프터 포함)에 5분마다 수집
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run (kospi.sql 을 먼저 실행해 둔 상태여야 함)

create table if not exists public.ewy_ticks (
  ts         timestamptz primary key,
  price      numeric not null,
  prev_close numeric                  -- 미국 전일 종가
);
alter table public.ewy_ticks enable row level security;
revoke all on public.ewy_ticks from anon, authenticated;
grant select on public.ewy_ticks to anon;
drop policy if exists "anyone reads ewy" on public.ewy_ticks;
create policy "anyone reads ewy" on public.ewy_ticks for select to anon using (true);

create table if not exists public.ewy_req (id bigint primary key, at timestamptz not null default now());
alter table public.ewy_req enable row level security;
revoke all on public.ewy_req from anon, authenticated;

create or replace function public.ewy_collect()
returns void language plpgsql security definer set search_path = public as $$
declare r record; body jsonb;
begin
  for r in select q.id, h.status_code, h.content from public.ewy_req q join net._http_response h on h.id = q.id loop
    if r.status_code = 200 then
      body := r.content::jsonb -> 'chart' -> 'result' -> 0;
      insert into public.ewy_ticks (ts, price, prev_close)
      select to_timestamp(t.v::bigint), c.v::numeric,
             coalesce(body -> 'meta' ->> 'previousClose', body -> 'meta' ->> 'chartPreviousClose')::numeric
      from jsonb_array_elements_text(body -> 'timestamp') with ordinality t(v, i)
      join jsonb_array_elements_text(body -> 'indicators' -> 'quote' -> 0 -> 'close') with ordinality c(v, i) using (i)
      where c.v is not null
      on conflict (ts) do update set price = excluded.price, prev_close = excluded.prev_close;
    end if;
    delete from public.ewy_req where id = r.id;
  end loop;
  delete from public.ewy_req where at < now() - interval '30 minutes';
  delete from public.ewy_ticks where ts < now() - interval '7 days';
  insert into public.ewy_req (id) select net.http_get(
    'https://query1.finance.yahoo.com/v8/finance/chart/EWY?interval=5m&range=1d&includePrePost=true',
    headers := '{"User-Agent": "Mozilla/5.0"}'::jsonb);
end $$;
revoke all on function public.ewy_collect() from public, anon, authenticated;

-- 미국 프리마켓 시작 ~ 애프터마켓 끝 (UTC 08:00 ~ 다음 날 01:00, 서머타임 여부와 무관하게 넉넉히)
select cron.unschedule(jobname) from cron.job where jobname in ('ewy', 'ewy-late');
select cron.schedule('ewy', '*/5 8-23 * * 1-5', 'select public.ewy_collect()');
select cron.schedule('ewy-late', '*/5 0 * * 2-6', 'select public.ewy_collect()');
select public.ewy_collect();   -- 지금 한 번 요청
