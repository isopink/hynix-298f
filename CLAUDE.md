# CLAUDE.md — Sigma Engine

이 저장소에서 작업할 때 Claude Code가 먼저 읽는 프로젝트 맥락입니다. **지금 규칙만** 적습니다. 날짜별 결정 · 이유 · 사고 기록은 [`reports/decisions.md`](reports/decisions.md) (11-13 까지), 그 뒤 변경은 `reports/changes.tsv` · `CHANGELOG.md`.

사용자(S.Lee, 이석민)는 한국어로 소통하며, 설명은 간단명료하게 · 과정은 단계별로 · 할 일은 개조식으로 정리하는 걸 선호합니다.

## 프로젝트

- 2026 나비스트 AI 자동매매 대회 참가작 (팀 「하이닉스 298층 주민」: 이석민, 박문화). 공개 저장소 = S.Lee 포트폴리오
- 기간 2026-11-02(월) ~ 11-27(금), 국내 주식만, **팀 계좌 1개 · 초기 5,000만 원**, 최소 8회 거래. 동률 시 회전율 → 매매일수 → 보고서 진정성
- AI 에이전트(Claude Code)가 판단과 주문을 스스로 함
  - ❌ 수동 주문, 사람이 AI 주문을 골라 승인 · 거절
  - ✅ 코드 · 프롬프트 · 전략은 대회 중에도 수정 가능
  - ❌ 키움 API 이용 제한 위반 = 부정행위. 모의서버는 **API별 초당 1회** (넘으면 429) → 연속 호출 1.1초 간격 (`broker._call`, `snapshot.py`)
- 보고서: 주간 11-08 · 11-15 · 11-22 (일, AI 판단 근거 포함), 최종 11-29 (고찰 포함). 계획서 대비 바뀐 점과 이유를 주간 보고서에 적음

## 구조

```
agent/      트레이딩 에이전트 (실행법 agent/README.md, 에이전트 지시 agent/CLAUDE.md)
  config/     risk_limits.json (고정, Hook 이 강제) · params.json (판단 기준값, 자동 조정) · tuning.json (조정 규칙)
  src/        data_prep · intraday · routing · sizing · risk · broker · mcp_server · monitor · tuning · logger · benchmark · sync
  .claude/    서브에이전트 · risk_check.py Hook · 도구 권한 (Bash/Edit/Write 금지) · 모델 고정 (Opus 5.5 high)
  run.py      prep / decide / exit / close / tune / review / report / monitor
  work/       실행 산출물 (커밋 안 함). journal.jsonl 이 모든 기록의 원본
live/       snapshot.py — 키움 잔고(kt00018) · KOSPI(ka20001) → Supabase push_snapshot, 30초마다 (params.live.snapshot_sec, 30초 밑 금지)
supabase/   schema.sql (comments · snapshots · push_snapshot) · kospi.sql · flow.sql · realtime.sql (KOSPI · 수급 20초 수집) · heartbeat.sql
docs/       GitHub Pages 대시보드 https://isopink.github.io/hynix-298f/ — index.html 한 파일 (D3 7.9.0, 빌드 없음) · config.js · data/*.json
reports/    보고서 · changes.tsv · changelog_plain.tsv · make_changelog.py · drafts/ (회고 · 보고서 초안) · decisions.md
assets/     README 그림 · diagrams/*.mmd
```

## 실행 PC

- 에이전트는 상시 켜 둔 **데스크톱** `C:\dev\uostock-ai-trader` 에서 돎. 노트북 · 클라우드는 수정 전용
- push → 데스크톱 `sync` (로그온부터 상시)가 1분 안에 pull · 검사 · 반영, 장중이면 감시 · 잔고 루프 재시작, `sync.py` 가 바뀌면 자기 자신도 재시작. 1분마다 heartbeat
- 에이전트도 판단마다 `docs/data` 를 커밋 · push 함 → push 가 거절되면 `git pull --rebase` 후 다시
- 작업을 멈출 때: `Stop-ScheduledTask` 는 run.bat 만 끔 → 감시를 재시작하려면 `run.py monitor` python 도 종료
- 옮기는 순서 `agent/MOVE_PC.md`, 배포 `docs/DEPLOY.md`

## 실행 일정 (평일)

| 시각 | 작업 |
|---|---|
| 08:25 | 잔고 수집 시작 (30초마다) |
| 08:30 | 데이터 준비 (prep) |
| 08:30 ~ 15:20 | 1분 감시: 손절 · 익절 · 보유일이면 매도 전용 실행 (**09:30 전엔 매도 안 함**) |
| 09:30 ~ 15:15 | **15분마다 판단 + 주문** (하루 24번, `params.schedule`). 그날 판 종목은 재매수 금지. 앞 회차를 놓치면 다음 회차가 대신 |
| 15:45 | 마감 기록 (close) |
| 16:00 | 기준값 자동 조정 (tune). 수 · 금은 회고가 끝나길 최대 40분 기다림 |
| 수 · 금 15:50 | 주간 회고 (review) → `reports/drafts/week{n}[-mid].md` |
| 수 · 금 17:00 | 주간 보고서 초안 (report) → `reports/drafts/week{n}[-mid].report.md` |

손절 주문도 코드가 직접 내지 않고 에이전트 + Hook 을 거침 (AI 주문 규정).

## 에이전트 (11-12 분리, `params.agents.split=false` 면 예전 단일 흐름)

| 단계 | 에이전트 | 하는 일 | 모델 · effort |
|---|---|---|---|
| 15분 판단 | 총괄 | 최종 확신도 · 행동, 지휘 | Opus 5.5 xhigh |
| | regime | 국면 (상승 · 횡보 · 하락) | Opus high |
| | position | 보유 종목 매도 · 보유 · 추가 매수 확신도 | Opus xhigh |
| | research | 토론 대상 종목 사실 표 (검색 6번 · 8분) | Opus xhigh |
| | bull · bear | 같은 사실 표로 후보 토론 (직접 검색 안 함) | Opus high · xhigh |
| | executor | 결정대로 매도 → 매수 → 기록 | Haiku 5.5 medium |
| 손절 · 익절 | 총괄 | 조건 확인 후 직접 주문 | Opus high |
| 16:00 조정 | scorer → tuner | 채점 → 기준값 0~2개 · 교훈 (`apply_tuning`) | Opus max |
| 수 · 금 | review · writer | 회고 분석 · 보고서 초안 | Opus max · Sonnet 5.5 medium |

- 순서: regime · position · research 동시 → bull → bear → `verify_claims` (근거 숫자를 브리핑 · 계좌 · 사실 표와 대조) → 총괄 → executor
- **라우팅** (`src/routing.py`): 직전 회차 대비 가격 ±1.5% · 외국인/기관 순매수 방향 바뀜(5억 이상) · 새 뉴스 · 새 후보만 토론, 나머지는 직전 판단 이어 쓰기. 그날 첫 회차 · 09:30 · 15:00 · 15:15 는 전부 토론
- effort 는 `params.effort` (run.py 가 `--effort`), 서브에이전트는 각 파일 frontmatter. 전부 토론 회차가 12분 넘으면 bear 를 high 로

## 전략 (값의 원본은 `agent/config/params.json`, 자동 조정으로 바뀜)

"에이전트는 제안하고, 규칙이 결정한다"
1. 데이터 준비 (Python): KRX(pykrx) · 네이버 뉴스 · 키움 → 지표 → 후보. LLM 엔 숫자 요약만
2. 장중 재선별: 키움 순위로 코스피 · 코스닥 따로, 일반 후보 15 = 코스피 10 + 코스닥 5, ⚡고변동 몫 별도. 5 · 20일선 추세
3. 국면 → 주식 비중 상한 (상승 90 · 횡보 70 · 하락 60%)
4. 확신도 → 매수 (8~12%, 기준 바로 아래 0.07 구간은 소액 4~8%) · 판단 매도 (기준 이상 절반, 0.65 이상 전량, 절반이 총자산 1% 미만이면 안 팖) · 보유 종목은 이익 중일 때만 추가 매수
5. 코드 보정: 하락 국면 신규 매수 +0.05, RSI 35 미만 매수 +0.05, RSI 65 이상 보유 매도 +0.05 (장중 RSI)
6. 손절 · 익절 · 최대 보유일 (일반 −7% · +10% · 5일, 코스닥 · ⚡고변동은 종목당 5% · −12% · +20%)
7. 🔻KODEX 인버스: 10:00 이후, 10~20% 별도, 하루 1번, 순익 +1.5% · 손절 −3% · 2일, +4% 오른 날 추격 금지
8. 📈KODEX 200: 15:00 · 15:15 회차만, 하루 1번, 손절가 없음, 순익 +2% · 3일, 종목당 최대 20%. 그 밖의 ETF · ETN 차단
9. 리스크 Hook (PreToolUse, 주문 직전): 현금 · 종목 한도 · 일일 손실 · 당일 상승률 (코스피 +10% · 코스닥 +15%) → 위반 시 차단. `risk_limits.json` 은 에이전트 · 회고 · 조정이 못 바꿈
10. 자동 조정: 판단을 결과로 채점 → `tuning.json` 범위 · 1회 폭 · 쿨다운 안에서 기준값 0~2개 + 교훈(`work/lessons.json` → 다음 브리핑). 사람 검토 없이 반영되므로 보고서에 기록

## 대시보드 데이터 형식 (에이전트 logger 가 맞춰 씀)

- `equity.json`: `[{date, total, kospi, regime, cap}]` — 실시간 스냅샷이 있으면 자산은 그쪽 우선
- `holdings.json`: `[{code, name, qty, avg_price, price, value, pnl_pct, weight, stop, take, held_days, max_days}]`
- `trades.json`: `[{id, time "YYYY-MM-DD HH:MM", code, name, side "매수"|"매도", qty, price, amount, confidence, regime, bull, bear, decision}]`
- `risk.json`: `[{id, time, name, side, rule, detail}]` · `system.json`: `[{date, runs, failures, tokens_k}]` · `reviews.json`: `[{week, period, suggestion, status}]`
- `status.json`: `{last_run, last_ok, next_run, runs_today, failures_today, note}` — 실행마다 덮어씀
- `decision.json`: `{time, regime, cap, reason, items: [{code, name, action, qty?, price?, confidence, bull, bear, decision, blocked?}]}` — 최근 판단 1회
- `debates.json`: 회차별 decision 목록 (최신 120회) · `briefing.json`: 08:30 준비 · 장중 재선별 결과 · `tuning.json`: 조정 이력 · `exchange.json`: 종목 시장
- `kodex200.json`: 일봉 시가 · 종가 (수익률 비교 기준, 마감 때 `src/benchmark.py`)

## 대시보드 규칙 (`docs/index.html`)

- 화면 = VOLT 블록 (예전 화면 `?theme=classic` 은 남아 있음). 평면: 바탕 `#101010`, 카드 `#161616` + 1px `#2a2a2a` + 8px 모서리, 그림자 · 유리 · 그라데이션 · 투명도 없음
- 색: **수익 · 매수 = 빨강 `#ff5a65`, 손실 · 매도 = 파랑 `#4e94ff`** (`C.up` · `C.down`, `.up` · `.down`). 나머지는 검정 · 흰 · 회색. 초록 `#34c759` 은 상태 점(작동)에만, 빨강 점 = 오류, 회색 = 꺼짐 · 장 밖. 새 색은 `voltColor` 표(`HEX` · `RGB`)에 넣음
- 글꼴 Noto Serif KR (숫자 tabular-nums). 글자는 한글 (Sigma Engine · KOSPI · KODEX 200 같은 이름만 영어). 괄호와 그 안 글자는 화면에서 지움 (`noParen`)
- 움직임 없음 (`no-motion`). 상태 점 깜빡임(실행 중 · 오류)만. `:hover` 규칙 · 말풍선 없음
- 첫 화면 = Loading → 준비되면 ENTER (`#boot`). 머리글 상태 점 넷: 서버 · 모니터링 · 에이전트 (+ KOSPI 칩). PC 는 그 줄을 맨 위 카드 차트 위 오른쪽 끝으로
- 맨 위 카드: 누적 수익률 + 핵심 숫자 6개 | 누적 수익률 차트 (Sigma 흰 실선 · KODEX 200 회색 점선, 11/2 ~ 최신일). 그 아래 포트폴리오 (PC 도넛 왼쪽 · 표 오른쪽, 비중 순) → 실시간 판단 (행을 누르면 근거 펼침) → 최근 체결 → 접는 칸 (실시간 KOSPI · 기록 · 자동 조정 기록)
- 수익률 = 키움 모의 잔고 그대로 (보정 없음). 비교 기준 KODEX 200 (`kodex200.json`, 장중은 KOSPI 등락으로 추정). KOSPI 기준값 `config.js` `kospiStart`
- 갱신: 잔고 · 상태 10초, KOSPI · 수급 20초. 서버 점 = heartbeat 3분 넘게 없으면 빨강
- 캘린더 운영 사고 표시 `CAL_NOTE` (11-11 · 11-12 시스템 오류)
- 흐린 글씨 `#8c8c8c` 이상, 축 글씨 11px 이상. 이모지 아이콘 · 가운뎃점 나열 쓰지 않기. 하단 `Designed by S.Lee & M.Park`
- 아이콘 `icon.svg` (흰 Σ 신경망 + 빨간 점), 아이폰용 `icon-ios.svg` → `apple-touch-icon.png`. 링크 미리보기 `og.jpg`
- **수정 후 1280 · 400 폭 둘 다 가로 스크롤 없는지 확인**

## 보안 (반드시 지킬 것)

- 키움 App Key/Secret, `live/.env`, `agent/.env`, Supabase `service_role` 키는 절대 커밋 금지
- `supabase/schema.sql` 의 비밀문구 자리(`여기에-긴-비밀문구-입력`)는 그대로 둠. 실제 값은 Supabase SQL Editor 에서만
- 웹(`docs/`)에는 anon 키와 숫자만. 키움 호출은 로컬 스크립트에서만

## 남은 일

- [ ] 장중 push 때 sync 가 monitor 를 실제로 재시작하는지 확인. 문제없으면 노트북 `C:\dev\uostock-ai-trader` 삭제
- [ ] Supabase SQL Editor 에서 `supabase/realtime.sql` 실행 (KOSPI · 수급 20초 수집)
- [ ] 대회 후 README 결과 · 회고 섹션 채우기

## 커밋

- 작성자: `S.Lee <2sm9908@gmail.com>`. 기능 단위로 나눠 커밋 (포트폴리오로 과정이 보이도록)
- 전략 · 운영 변경을 커밋하면 `reports/changes.tsv` 에 한 줄 (커밋 · 분야 · 내용), 전략이면 `reports/changelog_plain.tsv` 에도 쉬운 설명 (분야 · 무엇을 · 왜) 한 줄 → `python reports/make_changelog.py` 로 `CHANGELOG.md` 갱신
- 커밋 전 `python agent/tests/test_rules.py`
