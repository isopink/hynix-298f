-- 하이닉스 298층 관제실 · 익명 댓글 테이블
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run

create table if not exists public.comments (
  id         bigint generated always as identity primary key,
  nickname   text not null default '익명 개미'
             check (char_length(btrim(nickname)) between 1 and 20),
  body       text not null
             check (char_length(btrim(body)) between 1 and 300),
  hidden     boolean not null default false,   -- true 로 바꾸면 화면에서 숨김
  created_at timestamptz not null default now()
);

alter table public.comments enable row level security;

-- 익명 방문자: 숨기지 않은 댓글만 읽기, 닉네임·내용만 쓰기 (수정·삭제 불가)
revoke all on public.comments from anon, authenticated;
grant select (id, nickname, body, created_at, hidden) on public.comments to anon;
grant insert (nickname, body) on public.comments to anon;

drop policy if exists "anyone reads visible" on public.comments;
create policy "anyone reads visible" on public.comments
  for select to anon using (hidden = false);

drop policy if exists "anyone writes" on public.comments;
create policy "anyone writes" on public.comments
  for insert to anon with check (hidden = false);

-- 도배 방지: 1분에 전체 20개가 넘으면 거절
create or replace function public.comments_flood_guard()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.comments where created_at > now() - interval '1 minute') >= 20 then
    raise exception 'too_many_comments';
  end if;
  return new;
end $$;

drop trigger if exists comments_flood_guard on public.comments;
create trigger comments_flood_guard before insert on public.comments
  for each row execute function public.comments_flood_guard();

-- ============================================================
-- 실시간 잔고 스냅샷 (live/snapshot.py 가 5분마다 올림)
-- ============================================================
create table if not exists public.snapshots (
  id         bigint generated always as identity primary key,
  ts         timestamptz not null default now(),
  account    text not null default '팀',     -- 팀 계좌 1개면 '팀' 그대로
  total      bigint not null,          -- 추정예탁자산 (현금 + 주식 평가금액)
  stock_eval bigint not null,          -- 주식 평가금액
  pur_amt    bigint not null,          -- 주식 매입금액
  holdings   jsonb not null default '[]'::jsonb,
  kospi      numeric
);
create index if not exists snapshots_ts_idx on public.snapshots (ts);

alter table public.snapshots enable row level security;
revoke all on public.snapshots from anon, authenticated;
grant select on public.snapshots to anon;            -- 사이트는 읽기만
drop policy if exists "anyone reads snapshots" on public.snapshots;
create policy "anyone reads snapshots" on public.snapshots for select to anon using (true);

-- 올리는 쪽 비밀문구 (사이트·방문자는 볼 수 없음)
create table if not exists public.app_secret (name text primary key, value text not null);
alter table public.app_secret enable row level security;   -- 정책 없음 = 아무도 못 읽음
revoke all on public.app_secret from anon, authenticated;

create or replace function public.push_snapshot(
  p_secret text, p_account text, p_total bigint, p_stock_eval bigint,
  p_pur_amt bigint, p_holdings jsonb, p_kospi numeric
) returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.app_secret where name = 'snapshot' and value = p_secret) then
    raise exception 'unauthorized';
  end if;
  insert into public.snapshots (account, total, stock_eval, pur_amt, holdings, kospi)
  values (p_account, p_total, p_stock_eval, p_pur_amt, coalesce(p_holdings, '[]'::jsonb), p_kospi);
end $$;
revoke all on function public.push_snapshot(text, text, bigint, bigint, bigint, jsonb, numeric) from public;
grant execute on function public.push_snapshot(text, text, bigint, bigint, bigint, jsonb, numeric) to anon;

-- ▼ 아래 문구를 길고 아무도 모르는 값으로 바꾼 뒤 실행 (live/.env 의 SNAPSHOT_SECRET 과 똑같이)
insert into public.app_secret (name, value) values ('snapshot', '여기에-긴-비밀문구-입력')
  on conflict (name) do update set value = excluded.value;
