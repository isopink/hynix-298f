-- 11-12 S.Lee: KOSPI 1분봉 · 투자자별 수급 수집을 1분 → 20초마다 (대시보드 실시간 갱신)
-- Supabase SQL Editor 에서 kospi.sql · flow.sql 다음에 한 번 실행. 되돌리려면 kospi.sql · flow.sql 마지막 cron.schedule 줄을 다시 실행.
-- pg_cron 의 '20 seconds' 일정은 요일 · 시간을 못 정해서, 평일 09:00~15:59 KST 인지 함수 안에서 확인.

create or replace function public.market_tick()
returns void language plpgsql security definer set search_path = public as $$
declare k timestamp := now() at time zone 'Asia/Seoul';
begin
  if extract(isodow from k) > 5 or extract(hour from k) < 9 or extract(hour from k) > 15 then
    return;
  end if;
  perform public.kospi_collect();
  perform public.flow_collect();
end $$;
revoke all on function public.market_tick() from public, anon, authenticated;

select cron.unschedule('kospi') where exists (select 1 from cron.job where jobname = 'kospi');
select cron.unschedule('flow') where exists (select 1 from cron.job where jobname = 'flow');
select cron.unschedule('market_tick') where exists (select 1 from cron.job where jobname = 'market_tick');
select cron.schedule('market_tick', '20 seconds', 'select public.market_tick()');
