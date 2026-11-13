# 결정 기록 (예전 CLAUDE.md 전문)

11-13 CLAUDE.md 를 지금 규칙만 남기고 줄이면서, 그때까지 날짜별로 쌓인 결정 · 이유 · 사고 기록을 그대로 옮겨 둔 문서입니다. 주간 보고서에 변경 이유를 쓸 때 참고합니다. 지금 기준은 루트 `CLAUDE.md` 와 `agent/config/*.json` 입니다.

---

# (11-13 이전 CLAUDE.md)

이 저장소에서 작업할 때 Claude Code가 먼저 읽는 프로젝트 맥락입니다. 사용자(S.Lee, 이석민)는 한국어로 소통하며, 설명은 간단명료하게·과정은 단계별로·할 일은 개조식으로 정리하는 걸 선호합니다.

## 프로젝트

- 2026 나비스트 UOStock AI 자동매매 모의주식투자대회 참가작 (팀 「하이닉스 298층 주민」: 이석민, 박문화)
- 대회 기간 2026-11-02(월) ~ 11-27(금), 국내 주식만, **팀 계좌 1개 · 초기 자산 5,000만 원**
- AI 에이전트(Claude Code)가 투자 판단과 주문을 자동 수행해야 함
  - ❌ 수동 주문, 사람이 AI 주문을 골라 승인·거절하는 것 금지
  - ✅ 코드·프롬프트·전략은 대회 중에도 수정 가능
  - ❌ 키움 API 이용 제한 위반 = 부정행위 → 호출 빈도 보수적으로. 모의서버는 **API별 초당 1회** (넘기면 429 "유량=1") → 연속 호출은 1.1초 간격 (`broker._call`, `snapshot.py`)
- 최소 8회 거래. 동률 시 회전율 → 매매일수 → 보고서 진정성 순
- 이 저장소는 S.Lee의 GitHub 포트폴리오이기도 함 (공개 저장소)

## 일정

| 날짜 | 할 일 |
|---|---|
| 10-28 (수) | 사전 계획서 제출 (PDF 2~5쪽) |
| 10-31 (토) 이후 | 상시모의투자 계좌 취소 → 대회용 계좌 재신청, App Key 재발급 |
| 11-02 (월) | 대회 시작 |
| 11-08 · 11-15 · 11-22 (일) | 주간 운용보고서 (AI 판단 근거 포함) |
| 11-29 (일) | 최종 성과보고서 (고찰 포함) |

## 구조

```
docs/       GitHub Pages 대시보드 (https://isopink.github.io/hynix-298f/)
  index.html   단일 파일, D3 v7 (cdnjs), 빌드 없음. 샘플 데이터가 <script id="sample-data">에 내장
  config.js    Supabase URL / anon key / liveSince
  data/*.json  에이전트 로그 (equity, holdings, trades, risk, system, reviews)
  DEPLOY.md    배포 가이드 (한국어)
live/       snapshot.py — 키움 kt00018 잔고 + ka20001 KOSPI를 1분마다 조회 (11-02부터, `live/.env` INTERVAL_SEC=60) → Supabase RPC push_snapshot
supabase/   schema.sql — comments(익명 게시판), snapshots, app_secret, push_snapshot()
            kospi.sql · flow.sql — 네이버 증권에서 KOSPI 1분봉 · 투자자별 누적 순매수(억 원)를 pg_cron 으로 1분마다 수집
agent/      트레이딩 에이전트 (구조·실행법은 agent/README.md)
  config/      risk_limits.json(고정, Hook이 강제) · params.json(판단 기준값)
  src/         data_prep · sizing · risk · broker(mock/live) · mcp_server · logger · monitor
  .claude/     서브에이전트 4개, risk_check.py Hook, 도구 권한(Bash/Edit/Write 금지)
  run.py       prep / decide / exit / close / review / monitor
  work/        실행 산출물 (커밋 안 함): journal.jsonl이 모든 기록의 원본
reports/    보고서 PDF, drafts/ = 주간 회고 에이전트가 쓴 초안
```

### 실행 일정 (10-29 결정: 하루 1번 → 2번 + 장중 감시)

평일 08:25 잔고 수집 시작 · 08:30 준비 · 08:30~15:20 1분 감시(손절·익절 걸리면 매도 전용 실행. **11-06 S.Lee: 09:30 전엔 걸려도 매도 안 함** (장 전·장 초반 투매 구간, KODEX 200 이 시가 −8.6% 에 손절된 일). 11-04 09:05→08:30, 장 전 매도는 09:00 동시호가로 체결되고 09:05 뒤 남아 있으면 한 번 더. 11-04 오후 5분→1분, "같은 종목 하루 1번" 제한 폐기 → 같은 매수 건은 실행 뒤 10분 지나도 남아 있으면 다시) · **09:30~15:15 15분마다 판단하고 매번 주문 (하루 24번, `params.schedule.interval_min`. 11-05 밤 10분으로 바꿨다가 같은 날 15분으로 되돌림 — 1회 판단 6~16분·사용 한도. 간격을 바꾸면 sync 가 작업 스케줄러도 맞춤, 11-05 모든 판단을 매매로 · 그날 판 종목은 재매수 금지 `decision.no_rebuy_same_day`)** (11-05 12:30 추가: 점심 1시간 30분 공백 메움) (11-04 추가: 매매 회차가 실행되지 않았으면 다음 판단 회차가 대신 매매 `C.missed_trade`, 매매 회차는 앞 실행이 끝날 때까지 최대 10분 대기) (11-04 오후 정각·30분 회차를 피해 조정, 마지막은 15:15) (11-04 매시 30분에서 변경: 장 초반 변동·점심 피하고 마감 직전 포함) (11-02 하루 2번 → 3번 → 11-03 판단 30분마다 · 매매 매시 → 11-04 판단 15분마다 (하루 23번, 토큰 약 2배). 작업 `Hynix298-decide` 하나가 반복, `run.py` 가 `params.schedule.trade_times` 로 매매/판단 갱신(view)을 가름) · 15:45 마감 기록 · **평일 16:00 기준값 자동 조정** (11-02 화·수·목 추가 → 11-03 매일). **수·금 15:50 주간 회고** (11-06 S.Lee: 토 10:00 → 수요일 중간·금요일 주간. 작업 `Hynix298-review` 는 sync 가 다시 등록, 초안 수 `reports/drafts/week{n}-mid.md` · 금 `week{n}.md`. 16:00 기준값 조정은 회고가 끝나길 최대 40분 기다렸다 그 제안을 바로 검토 → **목·월요일 장부터 반영**).
계획서의 "장 시작 전 1회"에서 바꾼 것이므로 첫 주간 보고서에 변경 이유를 적을 것.
손절 주문도 코드가 직접 내지 않고 에이전트 + Hook을 거침 (AI 주문 규정).

### 실행 PC와 수정 (11-02 결정)


에이전트는 계속 켜두는 데스크톱에서 돌고, 노트북은 수정 전용. 노트북에서 push → 데스크톱 `sync`(로그온부터 상시)가 1분 안에 검사·반영, 장중이면 감시·잔고 루프 재시작. 옮기는 순서는 `agent/MOVE_PC.md`.

### 에이전트 구조 (11-12 S.Lee 분리, `agent/CLAUDE.md` A · D · E, `params.agents.split` 로 되돌릴 수 있음)

| 단계 | 에이전트 | 하는 일 | 모델 · effort |
|---|---|---|---|
| 15분 판단 | 총괄 | 최종 확신도 · 행동, 지휘 | Opus 5.5 xhigh (`params.effort.decide`) |
| 15분 판단 | regime | 국면 | Opus 5.5 high (11-12 14:16 Sonnet → Opus) |
| 15분 판단 | position (새) | 보유 종목 매도 · 보유 · 추가 매수 확신도 (오른 종목 일찍 팔지 않기) | Opus 5.5 xhigh (11-12 14:16 high → xhigh) |
| 15분 판단 | research (새) | 토론 대상 종목의 사실 표, 검색 6번 · 8분 상한 | Opus 5.5 xhigh |
| 15분 판단 | bull · bear | 같은 사실 표로 후보만 토론 (직접 검색 안 함) | Opus 5.5 · bull high · bear xhigh (11-12 14:16) |
| 15분 판단 | executor (새) | 결정 목록대로 매도 → 매수 → 기록 | Haiku 5.5 medium |
| 손절 · 익절 | 총괄 | 조건 확인 후 직접 주문 (속도 때문에 executor 안 씀) | Opus 5.5 high |
| 16:00 조정 | scorer (새) → tuner (새) | 채점 → 기준값 0~2개 · 교훈 `apply_tuning` | Opus 5.5 max (실행 60분) |
| 수 · 금 15:50 | review | 분석 · 조정 제안 | Opus 5.5 max |
| 수 · 금 17:00 | writer (새) | 주간 보고서 초안 `reports/drafts/week{n}[-mid].report.md` (작업 `Hynix298-report`, sync 가 등록) | Sonnet 5.5 medium |

- 순서: regime · position · research 동시 → bull → bear → `verify_claims`(근거 숫자를 브리핑과 대조, 코드) → 총괄 → executor
- **라우팅** (`src/routing.py`, `params.routing`): 직전 회차 대비 가격 ±1.5% · 외국인/기관 순매수 방향 바뀜(5억 이상) · 새 뉴스 · 새 후보만 research · 토론, 나머지 후보는 직전 판단 이어 쓰기. 그날 첫 회차 · 09:30 · 15:00 · 15:15 는 전부 토론. 이어 쓴 종목은 마지막으로 토론한 때의 값과 비교
- 11-12 13:38 main 에 합쳐 13:45 회차부터 적용 (S.Lee, mock 시험 없이). 첫 회차(전부 토론): 471초 · 47k 토큰 (직전 13:30 예전 흐름 297초 · 84k), 15종목 기록 정상. 근거 숫자 대조가 처음엔 15종목 전부 잘못 걸려(단위 없는 이평선 가격) 고침, research 사실 표도 `facts` 로 같이 넘김. 문제가 생기면 `params.agents.split=false` 한 줄로 예전 흐름(A-0 · D-0)
- 11-12 14:16 S.Lee: 토큰이 예상보다 줄어서(14:00 회차 3.5만) effort 올림 — position xhigh · regime Opus · bear xhigh. 국면 · 보유 관리는 동시 실행이라 시간 영향 작음, bear 는 1~2분 늘 수 있음. 전부 토론 회차(09:30 · 15:00 · 15:15)가 12분 넘으면 bear 를 high 로 되돌릴 것
- 2주차 보고서에 기록

### 에이전트 설계 (사전 계획서 기준)

"에이전트는 제안하고, 규칙이 결정한다"
1. 데이터 준비 (Python): pykrx·네이버 뉴스·키움 → GS Quant 지표 → 후보 선별, LLM엔 숫자 요약만
2. 시장 국면 서브에이전트: 상승/횡보/하락 → 투자 비중 상한 (상승 90% · 횡보 70% · 하락 50%, 1주차만 ×0.75 — 11-03 기획팀 0.5→0.75)
   - 11-03부터 수익률 순위 대회(4주)에 맞춰 변경: 국면·종목 추세 기준을 20·60일선 → **5·20일선**, 상한 하락 30→50 · 횡보 60→70, 4주차 계수 0.5→1.0, 후보에서 변동성 100% 초과 제외(11-03부터 300% 이하는 ⚡고변동 몫으로 최대 3개 따로 포함, 종목당 5% · 손절 −12% · 익절 +20%, `params.high_vol`), 5일 +20% 넘게 오른 종목 감점. 1주차 운용보고서(11-08)에 근거 기록
3. 매수 ⇄ 매도 서브에이전트 토론
   - 11-04 장중 재선별 통과가 5개 미만이면 08:30 후보로 5개까지 채움 (`screen.intraday.min_candidates`). 🔻인버스 KODEX 인버스(114800) 매매 허용(운영진 확인): 매일 후보에 따로 포함, **하락 국면에서만** 매수, 주식 상한과 별도로 최대 20% (`params.inverse`, sizing·Hook 이 강제). 📈지수 KODEX 200(069500)도 후보에 따로 포함, **상승·횡보 국면에서만** 매수, 주식 상한 안에서, 매도 규칙은 인버스와 같음(`params.index`). 1주차 보고서에 기록
4. 총괄 Agent: 확신도 산출 → 매수/보유/매도 (기준 미달 시 관망)
   - 11-04 🔻인버스(KODEX 인버스 114800) 허용: 하락 국면에서만 · 비중 20% 따로 · **하루 1번 매수 · 수수료·세금 뺀 순익 +1.5%에 익절 · 최대 2일**. KOSPI 1분봉 시뮬레이션에서 폭을 1% 안쪽으로 좁히면 왕복 비용 약 0.9% 때문에 전부 손해였음. 1주차 보고서에 기록
   - 11-04 저녁 (기획팀 합의): 매수 확신도 0.65→**0.62** · 하락 국면 상한 50→**60%** · 종목당 크기 10~20% → **5~10%** (`decision.max_weight`, 여러 종목으로 나눠 최대 20종목) · 후보 10→**15**개 · 08:30 분석 대상을 코스피 45 + 코스닥 25로 따로 · KODEX 인버스·200 외 ETF·ETN 차단 · 자동 조정이 관망 확신도를 보정 후 값으로 봄. 1주차 보고서에 기록
   - 11-05 오전: 1주차 계수 0.75 → **1.0** (S.Lee). 남은 1주차(목·금)도 국면 상한·종목당 크기를 줄이지 않음. 1주차 보고서에 기록
   - 11-05 오전 회전율 올리기 (S.Lee): 소액 매수 구간 기준 −0.04 → **−0.07** (지금 0.55~0.62) · 익절 +15→**+10%** · 최대 보유 10→**5거래일** (이미 산 종목에도 평단 기준으로 적용) · 하락 국면이면 후보 추세 조건을 '현재가 > 20일선'으로 완화 (`screen.falling_trend`). 1주차 보고서에 기록
   - 11-06 오후 (S.Lee): 종목당 크기 5~10% → **8~12%** (`decision.min_weight`·`max_weight`) · 소액 매수 2~5% → **4~8%** (`decision.probe`) · KODEX 200 급락일 예외 매수 **폐기** (`index.dip_buy.enabled=false`, 하락 국면에서는 KODEX 200 매수 안 함). 1주차 보고서에 기록
   - 11-06 오후 (S.Lee): 📈KODEX 200 국면 제한 없앰 → 매수 측 ⇄ 매도 측 토론과 확신도로만 결정 · 매수·판단 매도는 15:00 이후 회차만 (`index.trade_from`) · 손절가 없음, 1분 감시가 떨어졌다고 팔지 않음 (`index.no_stop`). 익절은 같은 날 +1.5%·2일 → **순익 +2%·최대 3거래일** (`index.take_profit_net_pct`·`max_hold_days`). 1주차 보고서에 기록
   - 11-06 오후 (S.Lee): 🔻인버스도 국면 제한 없앰 → 토론·확신도로만 결정 · 매수·판단 매도는 10:00 이후 회차만 (`inverse.trade_from`) · 손절 −7% → **−3%** (`inverse.stop_loss_pct`). 익절 +1.5%·최대 2일, +4% 이상 오른 날 추격 금지, 비중 10~20% 는 그대로. 1주차 보고서에 기록
   - 11-06 오후 (S.Lee): 에이전트 확신도 설명표를 기준값에 맞춤 (예전 "0.50~0.64 대개 관망" → 매수 기준 이상 매수 · 소액 매수 구간 · 0.45~하한 관망 · 0.45 미만 관망). 11-06 오후 3시간 매수 0건, 보정 전 확신도 최고 0.50 이던 문제. 기준값은 그대로. 1주차 보고서에 기록
   - 11-12 14:1x S.Lee: **KODEX 200 매수 다시 허용** (`index.enabled=true` · `buy_banned=false`). 규칙은 11-06 그대로: 15:00 · 15:15 회차만, 하루 1번, 손절가 없음, 순익 +2% 익절 · 최대 3거래일, 주식 상한 안에서 종목당 최대 20%. 급락일 예외 매수는 계속 꺼짐. 2주차 보고서에 기록
   - 11-11 S.Lee: **KODEX 200 매수 금지** (`params.index.buy_banned`, 후보 제외 + Hook `risk.py` 가 매수 차단, 보유분은 기존 규칙으로 처분. 인버스는 허용 유지. 코드·규칙은 남겨 두고 다시 켤 수 있음). 2주차 보고서에 기록
   - 11-05 소액 매수 구간: 보정 후 확신도가 매수 기준 바로 아래(기준 −0.04 ~ 기준, 지금 0.58~0.62)면 종목당 2.5%로만 매수 (`decision.probe`, 수량 계산·Hook 이 강제). 하락장에서 기준을 내리지 않고 매매·분산을 늘리려고. 1주차 보고서에 기록
   - 11-03 코드 보정: 하락 국면이면 신규 매수 확신도 +0.05 (예전 −0.05를 뒤집음), RSI(14) 35 미만 매수 +0.05 · 65 이상 보유 매도 +0.05 (11-03 70→65). RSI는 판단 직전 현재가로 다시 계산한 장중 값. 1주차 보고서에 기록
5. 수량 계산 (Python): 확신도 → 수량, 손절·익절·최대 보유일
6. 리스크 검증 Hook (PreToolUse, 주문 도구 직전): 현금·종목 한도·일일 손실 → 위반 시 차단
7. 주문 실행 (키움 REST API / MCP) → 판단 근거·체결 결과 기록 → `docs/data/*.json`
8. 주간 회고 서브에이전트: 기준값 조정 제안 + 주간 보고서 초안 (리스크 한도는 수정 불가)
9. 기준값 자동 조정 (평일 매일, `run.py tune`, 11-02 추가 · 11-03 화·수·목 → 매일): 에이전트가 `get_tuning_context`로 성과를 보고 `apply_tuning`으로 0~2개 제안 → `src/tuning.py`가 `config/tuning.json` 규칙(허용 키·범위·1회 변경폭·쿨다운·일관성)으로 검사해 통과분만 `params.json`에 쓰고 커밋. 이력은 `docs/data/tuning.json` → 대시보드 Feedback Loop. 사람 검토 없이 반영되므로 계획서 대비 변경점으로 1주차 보고서에 기록. **11-06 S.Lee: 조정 전에 판단을 결과로 채점** (`tuning.outcomes`: 관망→올랐으면 놓침·내렸으면 맞음 / 보유→더 내렸으면 손해 / 매수→오르면 맞음·내리면 틀림 / 매도→내리면 맞음·오르면 일찍 팖). 맞은 판단은 유지, 틀린 판단은 기준값 + 교훈(`apply_tuning(lessons)` → `work/lessons.json` → 다음 판단 브리핑)으로 조정. 수·금 회고는 앞선 조정들을 총괄 분석

### 대시보드 데이터 형식 (에이전트가 맞춰서 써야 함)

- `equity.json`: `[{date, total, kospi, regime, cap}]` — 실시간 스냅샷이 있으면 자산은 그쪽 우선, regime/cap은 여기서 날짜로 매칭
- `holdings.json`: `[{code, name, qty, avg_price, price, value, pnl_pct, weight, stop, take, held_days, max_days}]`
- `trades.json`: `[{id, time "YYYY-MM-DD HH:MM", code, name, side "매수"|"매도", qty, price, amount, confidence 0~1, regime, bull, bear, decision}]`
- `risk.json`: `[{id, time, name, side, rule, detail}]`
- `system.json`: `[{date, runs, failures, tokens_k}]`
- `reviews.json`: `[{week, period, suggestion, status "반영"|"검토 중"}]`
- `status.json`: `{last_run "YYYY-MM-DD HH:MM", last_ok, next_run "YYYY-MM-DD HH:MM", runs_today, failures_today, note}` — 에이전트가 실행할 때마다 덮어씀. next_run을 30분 넘기면 대시보드에 "지연" 표시 (시각은 화면에 안 보이고 상태 판정에만 씀)
- `decision.json`: `{time, regime, cap, reason, items: [{code, name, action "매수"|"매도"|"관망"|"보유", qty?, price?, confidence, bull, bear, decision, blocked?}]}` — 가장 최근 정기 판단 1회분. 대시보드 상단 "현재 판단" 카드
- `debates.json`: `[{time, regime, cap, reason, mode "trade"|"view", items: [decision.json 의 items 와 같음]}]` — 정기 판단 회차별 매수 측 ⇄ 매도 측 토론과 총괄 결정, 최신 순 120회차. Agent Black Box '에이전트 토론' 카드
- `briefing.json`: `{created, asof, universe, source, market {close, ma20, ma60, ret5, ret20, rsi14, rule_hint}, intraday {time, pool, passed, kept_prep, error?}, candidates [{code, name, close, ret5, ret20, rsi14, vol20, foreign_net, inst_net, score, news, (장중 재선별 시) price, chg, activity, foreign_today, inst_today}]}` — 08:30 데이터 준비 직후 push, 정기 판단마다 장중 수급 재선별 결과로 다시 push. 오늘 판단이 아직 없으면 같은 카드에 "오늘의 시장 자료"로 표시
- KOSPI 수익률 기준은 `docs/config.js`의 `kospiStart` (대회 시작일 11-02 09:00 1분봉 5,645.52)

## 디자인 규칙 (대시보드)

- **11-10 S.Lee: 본 화면은 VoltAgent 디자인** (`index.html` 의 `VOLT` 스크립트 블록이 기본으로 켜짐, 예전 화면은 `?theme=classic`). 새로 고칠 때는 VoltAgent 규칙을 따름:
  - **11-12 S.Lee: 수익 · 매수 = 빨강 `#ff5a65`, 손실 · 매도 = 파랑 `#4e94ff` (한국식)** — 큰 수익률 숫자 · 표 · 캘린더 · 일별 초과수익 · 승률 점 · 체결 구분 모두. 코드는 `C.up` · `C.upHi` · `C.down` 과 `.up` · `.down` 클래스(`volt-pl` 스타일). **11-12 S.Lee: 초록은 아예 안 씀 → 검정 · 흰 · 회색 + 빨강 · 파랑 계열만.** 예전 초록 강조(`#00d992` 등)는 흰색 `#f2f2f2` 계열로 바꿈 (Sigma 이름 · 선 · LIVE · 상태 점 정상 · 활성 탭 · 커버 글자). 상태 점은 **초록 `#34c759` = 작동(실행 중이면 깜빡임), 회색 = 꺼짐, 빨강 = 오류** (11-12 S.Lee, 화면에서 초록은 상태 점만). 레이아웃은 그대로 (11-12 심플 시안 `simple.html` 은 비교용으로만 남김). 예전: 초록 = 수익, 회색 = 손실
  - 11-10 S.Lee: 화면 글자에서 괄호와 그 안 내용은 지움 (`noParen`, 판단 근거 · 툴팁 포함)
  - 11-10 S.Lee: 모션 묶음 (`VOLT` 블록 8번 `fx`, 움직임 줄이기 설정이면 꺼짐, 초록 · 무채색만). **커버는 신경망 + 글 세 줄** (가운데 `SIGMA ENGINE`(11-10 S.Lee: The 뺀 대문자, 글자 간격만큼 왼쪽 여백으로 가운데 보정) / `Built to think` / `Wired to act`(초록) / LAUNCH 버튼, 글이 보이게 신경망은 50% 로 연하게 + 가운데 어두운 막. 문양 없음, 생체 · 기계 엔진 · 조립 장면 시안은 해 보고 되돌림): 천천히 숨 쉬듯 다가왔다 물러나고(`nn-breathe`), 터치하면 확대 없이 그대로 페이드 아웃. **대시보드 = 기계 · 군용 계기판**: 카드는 왼쪽 위 · 오른쪽 아래 모서리를 14px 딴 판(`clip-path`, 딴 변의 선과 오른쪽 위 경고 줄무늬는 배경 층 `PLATE`), 모서리 2px, 이름판 앞 초록 표식, 태그 · 칩도 각지게. 처음 드러날 때만 (엔진 탭을 바꿀 때는 애니메이션 없이 바로, 11-10 S.Lee) 판이 격납고 문처럼 가운데서 열리고(`fx-door`) 확신도 막대가 충전되며 큰 숫자는 기호에서 해독됨. 늘 도는 것: 깊은 우주 배경(`#fx-space` 별 · 초록 신호 줄기) + 흐르는 전술 격자(`#fx-grid`) + 오로라, 수익률 차트를 훑는 스캐너, 도넛의 레이더 빛과 궤도 위성, 판 윗변을 지나가는 신호, 머리글 제목은 PC · 폰 모두 중앙 정렬, 앞에 로고 없음 (11-10 S.Lee). 카드는 84% 불투명이라 별이 살짝 비침
  - **11-12 S.Lee: 글꼴은 영어 · 한글 · 숫자 모두 Noto Serif KR** (`serif` 스타일, 숫자는 tabular-nums). 예전: 영문 Inter, 한글 Pretendard, 숫자 · 표 · 차트 글자 JetBrains Mono. 큰 숫자 · 제목은 400 굵기
  - 색은 예전 빨강/파랑 값으로 써도 `voltColor` 가 CSS 글자 · d3 색 · 캔버스 · 인라인 style 에서 한 번에 바꿈. 새 색은 그 표(`HEX` · `RGB`)에 넣을 것
- 흐린 글씨는 `#8c8c8c` 이상 (대비 4.5:1 유지), 축 글씨 11px 이상
- 글은 최소화, 상세는 툴팁(마우스 오버 + 터치 시 고정 + 키보드 Tab·Esc). HTML 요소는 `tipTarget`, 막대·점·도넛은 `tipMark`, 연속 차트는 `tipAxis`(← → 로 시점 이동). 폰의 판단 행은 말풍선 대신 탭하면 행 아래로 펼침
- 화면 이름은 Sigma Engine으로 통일 (11-06 Sigma Six에서 바꿈). 큰 숫자는 수익률(11-10 S.Lee: 금액 대신, 총 손익 금액·양도차익·평가손익은 툴팁)
- 이모지 아이콘과 가운뎃점 나열 쓰지 않기
- 탭 아이콘(11-10 S.Lee, 11-12 색 변경): 어두운 바탕에 흰 시그마(Σ) 모양 신경망(모서리 네 점 + 가운데 빨간 점이 선으로 이어짐, 초록 없음). 원본 `docs/icon.svg`, PNG 는 `favicon-32.png` · `apple-touch-icon.png` · `icon-512.png` (예전: 빨강 298). 11-12: 아이폰용은 모서리 둥글림 · 투명 없이 꽉 찬 사각형 (`icon-ios.svg` → `apple-touch-icon.png` 180 · `icon-ios-1024.png`, iOS 가 직접 둥글림)
- 하단: `Designed by S.Lee & M.Park` 한 줄 (11-04 GitHub 로고 링크 뺌)
- 응원하기 버튼 없음 (11-06 S.Lee). 11-10 상단 응원 띠도 없앰 → 응원 게시판은 화면에서 열 곳 없음 (글은 Supabase comments 에 남음)
- **11-12 S.Lee: 대회 게시판 기준 보정 없앰** (`OFFICIAL_ADJ = 0`, 화면 수익률 = 키움 모의 잔고 그대로). 아래는 예전 기록
- 11-11 S.Lee: 수익률 비교 기준을 KOSPI → **KODEX 200** 으로 (`docs/data/kodex200.json` = 일봉 시가·종가, 시작은 11-02 시가 89,280. 마감 때 `run.py close` 가 `src/benchmark.py` 로 갱신, 장중 오늘 값은 KOSPI 1분봉 등락 × 전일 종가로 추정). 차트·범례·툴팁·이긴 날·일별 초과수익 카드가 대상. 헤더 KOSPI 칩과 Live KOSPI 카드는 시장 지표라 그대로
- 누적 수익률 차트 가로축: 11/2 가 맨 왼쪽, 최신 기록일이 맨 오른쪽 (11-06 S.Lee, 날이 늘면 칸이 좁아짐). 남은 기간 흐림·D-n·11/27 깃발은 없음. 커버 제목은 정가운데, 크기 clamp(20px, 5vw, 34px) (11-10 S.Lee, VoltAgent 화면. 예전: 조금 위 · clamp(26px, 6vw, 60px))
- 11-12: sync 가 판단 실행이 끝나길 기다리는 동안(장중 push 반영 대기)에도 연결 신호를 보냄. 예전엔 최대 15분 끊겨 Server 가 빨강
- 11-10 머리글 칩 줄 맨 앞에 실시간 KOSPI 칩(지수 · 등락률 · RSI, 네이버 1분봉). 폰은 머리글 칩 줄을 숨기고 같은 내용을 수익률 카드 맨 위 한 줄(연한 구분선)로, 'Live KOSPI' 접는 칸도 숨김 (PC 는 그대로)
- 11-10 S.Lee: PC(641px 이상)는 접는 칸(Table · 최근 체결 · Live KOSPI · Record · Feedback Loop)을 전부 펼친 채로, + − 표시·클릭 없음. 폰은 지금처럼 접힘
- 링크 미리보기(11-10): 제목 'The Sigma Engine' 만(설명 없음), 그림 `docs/og.jpg` = 커버 신경망(11-12: 흰 · 회색 · 빨강, 초록 없음) + 가운데 Inter 'The Sigma Engine' (1200×630). `/volt/` 는 예전 시안 주소라 본 화면으로 넘김
- 11-10 S.Lee: 처음에 예전(classic) 화면이 잠깐 보이던 것 막음. `<head>` 맨 앞 스크립트가 `data-theme=volt` 를 먼저 켜고 `html.volt-wait` 로 본문을 숨겼다가 VOLT 스타일이 들어가면 보임 (CDN이 느려도 3초 뒤엔 보임)
- 11-11: 상태 점의 '판단 실행 중'은 회차 시작 뒤 15분까지 (실행이 8~14분이라 6분 뒤 실패로 보이던 것), 장 마감 뒤 기준값 조정 실패는 판단 실패로 안 봄 (툴팁에만)
- **11-12 S.Lee: 애니메이션 전부 없앰** (`no-motion` 스타일: 판 열림 · 숫자 해독 · 우주 배경 · 격자 · 오로라 · 스캐너 · 레이더 · 궤도 · 판 윗변 신호 · 선 그리기 · 끝점 맥박). 상태 점 깜빡임(실행 중 · 오류)만 남김. 위 '모션 묶음' 설명은 예전 기록
- 11-12 첫 화면 로딩 줄이기: d3 를 `<head>` 에서 미리 받기(preload) · Noto Serif KR 은 `?theme=classic` 일 때만 · KOSPI 일봉 예비값(kospi_daily)은 안 기다림 · (실시간 잔고 대기는 Loading 화면 뒤에서 4초 그대로) · 빠진 날 스냅샷 조회를 한 번에. 시험(Supabase 0.6초 지연)에서 숫자가 뜨기까지 2.8초 → 2.1초, 0.25초 지연이면 1.4초
- 11-12 S.Lee: 첫 화면 = Loading 화면 (`#boot`: 검은 바탕 가운데 'Sigma Engine' + 'LOADING', 움직임 없음). 그동안 스크롤 잠금(`boot-lock`) · 터치 · 키 입력 무시. 실시간 잔고까지 받아 대시보드를 다 그리면(최대 4초 대기, `window.bootReady`) LOADING 글자가 하이라이트(흰 바탕 · 검은 글자)되며 'ENTER' 로 바뀌고, 그때부터 누르거나 Enter · Space 로 들어감. 어떤 경우에도 12초 뒤엔 하이라이트. 랜딩 커버 자리를 대신함
- 11-12 S.Lee: 최상단 제목 'Sigma Engine' 글자 없앰 (h1 은 읽기 프로그램용 `sr-only` 로만), 머리글엔 상태 점 줄 · KOSPI 칩만
- 11-12 S.Lee: 누적 수익률 차트 오른쪽 끝의 Sigma ↔ KODEX 200 세로 점선 없앰
- 11-12 S.Lee: PC(641px 이상)는 머리글(상태 점 넷 · KOSPI 칩)을 맨 위 카드의 누적 수익률 차트 바로 위 한 줄로 옮김 (구분선 없음, `</body>` 앞 스크립트가 `header.top` 을 `.hero-chart` 맨 앞으로 옮김). 11-13 S.Lee: 그 줄은 오른쪽 끝 정렬. 폰은 그대로
- 11-12 S.Lee: PC 포트폴리오 카드는 도넛 왼쪽 · 종목 표 오른쪽 (`drawDonut` 이 칸 폭 760px 이상이면 `pf-split`, 도넛 그림 폭을 줄여 두 칸 그리드, 'Table' 이름표 없이 표를 도넛 높이 가운데에). 폰은 위아래 그대로. 표는 폰 · PC 모두 비중 높은 순 (예전 수익률 순)
- 11-12 S.Lee: 기록의 이번 주 · 최대 낙폭 · KODEX 200 · 승률 카드는 그림 없이 숫자만 (`#sp-week` · `#sp-dd` · `#sp-kospi` · `#sp-win` 숨김)
- 11-12 S.Lee: 실시간 갱신 빠르게 — 대시보드 실시간 잔고 · 상태 30초 → 10초, KOSPI · 수급 차트 1분 → 20초. 데스크톱 잔고 업로드 1분 → 30초 (`params.live.snapshot_sec`, 30초 밑으로는 안 내림: 키움 유량 · 대회 이용 제한). KOSPI · 수급 Supabase 수집 1분 → 20초 (`supabase/realtime.sql` 의 `market_tick`, SQL Editor 에서 한 번 실행해야 함)
- 11-13 S.Lee: PC 실시간 판단 행도 누르면 펼침 (`inlineRow` 가 폰 · PC 모두) — 잘린 판단 근거가 전부 보이고, 그 아래 근거 칸에 오늘 수급 · 매수 측 · 매도 측 근거. 결정 문장은 근거 칸과 겹쳐 PC 펼침에선 숨김. Enter · Space 로도 펼침
- 수정 후 데스크톱(1280)·모바일(400) 둘 다 가로 스크롤 없는지 확인

## 보안 (반드시 지킬 것)

- 키움 App Key/Secret, `live/.env`, Supabase `service_role` 키는 절대 커밋 금지
- `supabase/schema.sql`의 비밀문구 자리(`여기에-긴-비밀문구-입력`)는 그대로 둠. 실제 값은 Supabase SQL Editor에서만
- 웹(`docs/`)에는 anon 키와 숫자만. 키움 호출은 로컬 스크립트에서만

## 남은 일

- [x] 사전 계획서 제출 (10-28)
- [x] GitHub Pages 켜기 (https://isopink.github.io/hynix-298f/ 배포 확인)
- [x] Supabase 프로젝트 생성, schema.sql 실행, config.js 채우기
- [x] 기획팀 기준값 회신 → `agent/config/*.json` 반영 (11-03 박문화). 리스크 한도는 제안값 그대로 확정. 매수 확신도 0.60→0.65 · 매도 0.60→0.55 · 1주차 계수 0.5→0.75. RSI 보정·장중 수급 재선별·매일 자동 조정은 유지, 최소 거래 대비책 3단계 안은 하지 않음 (기존 1단계 유지). 기획팀 값도 자동 조정 대상이라 오늘 16:00부터 바뀔 수 있음 → 1주차 보고서에 기록
- [x] KRX 정보데이터시스템 계정 → `agent/.env` KRX_ID/KRX_PW. 11-02 로그인·전 종목·수급 확인 (간편가입 계정은 pykrx 로그인 불가 → 일반 회원). 키움으로 대체하면 판단 1회당 호출 120번+ 늘어나 KRX 유지
- [x] 네이버 검색 API → `agent/.env` NAVER_CLIENT_ID/SECRET. 11-02 DART를 빼고 뉴스로 교체. 2026-07 이후 신규 키는 NAVER API HUB(네이버 클라우드)에서만 발급 → 주소·헤더 교체
- [x] 대회 노션 "AI Agent 연결 가이드" 확인 — 공식 MCP 설치 안내일 뿐. 11-02 운영진 확인: 키움 REST API를 직접 부르는 자체 MCP도 허용
- [x] 대회용 계좌·App Key → `live/.env`. 11-02 `snapshot.py --dry` 통과 (kt00018·ka20001 응답 정상, 총자산 5,000만 원), Supabase 업로드도 확인
- [x] `agent/.env` → 11-02 13:40 `MODE=live`, `GIT_PUSH=1` 전환. mock 기록은 work/ 에서 치움. 저장소 git 작성자(S.Lee) 설정 (에이전트 자동 커밋용)
- [x] live 모드 검증: kt00018(잔고)·ka10001(현재가)는 11-02 확인. kt10000(매수)은 에이전트 첫 주문으로 확인 (11-02 14:35 삼성E&A 45주, 11-03 09:32 셀트리온 16주 체결·기록 정상). 모의 서버는 kt00001을 거절하므로 예수금은 kt00018의 추정예탁자산 − 주식평가
- [x] kt10001(매도) 응답 필드는 에이전트의 첫 매도로 확인 (11-04 12:36 KODEX 인버스 매도 체결·기록 정상)
- 작업을 멈출 때 주의: `Stop-ScheduledTask`는 run.bat만 끄고 python 은 남음 → 감시 루프를 재시작하려면 `run.py monitor` 프로세스도 종료
- [x] 10-29 decide 실행이 25분 시간 초과로 실패 → 11-02 bull/bear의 종목별 WebSearch를 실행당 2번으로 줄임. 11-02 mock 실행 145초·34k 토큰
- [x] 리스크 Hook이 헤드리스 실행에서 PowerShell로 돌아 문법 오류 → 모든 주문 차단되던 문제 수정 (11-02, mock으로 통과·차단 모두 확인)
- [x] 실시간 KOSPI를 Yahoo(20분 지연) → 네이버 증권 1분봉으로 교체 (11-02, `supabase/kospi.sql` 재실행 완료)
- [x] `setup_tasks.ps1`로 작업 스케줄러 등록, `GIT_PUSH=1` (11-02 데스크톱, 작업 10개)
- [x] 에이전트를 데스크톱으로 옮기기 (`agent/MOVE_PC.md`). 11-02 밤 이전, 노트북 작업은 해제. 노트북 push → 데스크톱 반영 확인
- [ ] 장중 push 때 sync 가 monitor 를 실제로 재시작하는지 확인 (임시 저장소로는 확인함). 하루 이상 문제없으면 노트북 `C:\dev\uostock-ai-trader` 삭제
- [ ] 대회 후 README 결과·회고 섹션 채우기

## 커밋

- 작성자: `S.Lee <2sm9908@gmail.com>`
- 기능 단위로 나눠서 커밋 (포트폴리오로 작업 과정이 보이도록)
- 전략 변경을 커밋하면 `reports/week1/changes.tsv` 에 한 줄 추가하고 `reports/changelog_plain.tsv` 에 비전공자용 쉬운 설명(분야 · 무엇을 · 왜) 한 줄, `python reports/make_changelog.py` 로 `CHANGELOG.md`(팀 공유용, 전략만) 갱신
