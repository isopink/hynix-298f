# CLAUDE.md — UOStock AI Trader

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

평일 08:30 준비 · 09:05~15:20 5분 감시(손절·익절 걸리면 매도 전용 실행) · **09:30·11:00·14:30 정기 판단** (11-02 하루 2번 → 3번) · 15:45 마감 기록 · **평일 16:00 기준값 자동 조정** (11-02 화·수·목 추가 → 11-03 매일). 토 10:00 주간 회고.
계획서의 "장 시작 전 1회"에서 바꾼 것이므로 첫 주간 보고서에 변경 이유를 적을 것.
손절 주문도 코드가 직접 내지 않고 에이전트 + Hook을 거침 (AI 주문 규정).

### 실행 PC와 수정 (11-02 결정)

에이전트는 계속 켜두는 데스크톱에서 돌고, 노트북은 수정 전용. 노트북에서 push → 데스크톱 `sync`(로그온부터 상시)가 1분 안에 검사·반영, 장중이면 감시·잔고 루프 재시작. 옮기는 순서는 `agent/MOVE_PC.md`.

### 에이전트 설계 (사전 계획서 기준)

"에이전트는 제안하고, 규칙이 결정한다"
1. 데이터 준비 (Python): pykrx·네이버 뉴스·키움 → GS Quant 지표 → 후보 선별, LLM엔 숫자 요약만
2. 시장 국면 서브에이전트: 상승/횡보/하락 → 투자 비중 상한 (상승 90% · 횡보 70% · 하락 50%, 1주차만 ×0.5)
   - 11-03부터 수익률 순위 대회(4주)에 맞춰 변경: 국면·종목 추세 기준을 20·60일선 → **5·20일선**, 상한 하락 30→50 · 횡보 60→70, 4주차 계수 0.5→1.0, 후보에서 변동성 100% 초과 제외, 5일 +20% 넘게 오른 종목 감점. 1주차 운용보고서(11-08)에 근거 기록
3. 매수 ⇄ 매도 서브에이전트 토론
4. 총괄 Agent: 확신도 산출 → 매수/보유/매도 (기준 미달 시 관망)
5. 수량 계산 (Python): 확신도 → 수량, 손절·익절·최대 보유일
6. 리스크 검증 Hook (PreToolUse, 주문 도구 직전): 현금·종목 한도·일일 손실 → 위반 시 차단
7. 주문 실행 (키움 REST API / MCP) → 판단 근거·체결 결과 기록 → `docs/data/*.json`
8. 주간 회고 서브에이전트: 기준값 조정 제안 + 주간 보고서 초안 (리스크 한도는 수정 불가)
9. 기준값 자동 조정 (평일 매일, `run.py tune`, 11-02 추가 · 11-03 화·수·목 → 매일): 에이전트가 `get_tuning_context`로 성과를 보고 `apply_tuning`으로 0~2개 제안 → `src/tuning.py`가 `config/tuning.json` 규칙(허용 키·범위·1회 변경폭·쿨다운·일관성)으로 검사해 통과분만 `params.json`에 쓰고 커밋. 이력은 `docs/data/tuning.json` → 대시보드 Feedback Loop. 사람 검토 없이 반영되므로 계획서 대비 변경점으로 1주차 보고서에 기록

### 대시보드 데이터 형식 (에이전트가 맞춰서 써야 함)

- `equity.json`: `[{date, total, kospi, regime, cap}]` — 실시간 스냅샷이 있으면 자산은 그쪽 우선, regime/cap은 여기서 날짜로 매칭
- `holdings.json`: `[{code, name, qty, avg_price, price, value, pnl_pct, weight, stop, take, held_days, max_days}]`
- `trades.json`: `[{id, time "YYYY-MM-DD HH:MM", code, name, side "매수"|"매도", qty, price, amount, confidence 0~1, regime, bull, bear, decision}]`
- `risk.json`: `[{id, time, name, side, rule, detail}]`
- `system.json`: `[{date, runs, failures, tokens_k}]`
- `reviews.json`: `[{week, period, suggestion, status "반영"|"검토 중"}]`
- `status.json`: `{last_run "YYYY-MM-DD HH:MM", last_ok, next_run "YYYY-MM-DD HH:MM", runs_today, failures_today, note}` — 에이전트가 실행할 때마다 덮어씀. next_run을 30분 넘기면 대시보드에 "지연" 표시 (시각은 화면에 안 보이고 상태 판정에만 씀)
- `decision.json`: `{time, regime, cap, reason, items: [{code, name, action "매수"|"매도"|"관망"|"보유", qty?, price?, confidence, bull, bear, decision, blocked?}]}` — 가장 최근 정기 판단 1회분. 대시보드 상단 "현재 판단" 카드
- `briefing.json`: `{created, asof, universe, source, market {close, ma20, ma60, ret5, ret20, rsi14, rule_hint}, candidates [{code, name, close, ret5, ret20, rsi14, vol20, foreign_net, inst_net, score, news}]}` — 08:30 데이터 준비 직후 push. 오늘 판단이 아직 없으면 같은 카드에 "오늘의 시장 자료"로 표시
- KOSPI 수익률 기준은 `docs/config.js`의 `kospiStart` (대회 시작일 11-02 09:00 1분봉 5,645.52)

## 디자인 규칙 (대시보드)

- 글꼴은 전부 Noto Serif KR (고딕으로 바꾸지 말 것)
- 다크 캔버스 + 유리 질감 카드(반투명, blur, 16px radius) + 은은한 빨강/파랑 그라데이션 배경
- 빨강 `#da291c`/`#ff5a4a` = 수익·강조, 파랑 `#4aa3d4` = 손실 (국내 증시 관례), 나머지는 무채색
- 흐린 글씨는 `#8c8c8c` 이상 (대비 4.5:1 유지), 축 글씨 11px 이상
- 글은 최소화, 상세는 툴팁(마우스 오버 + 터치 시 고정)
- 하단: GitHub 로고(아이콘만), 다음 줄에 `Designed by S.Lee & M.Park`
- 수정 후 데스크톱(1280)·모바일(400) 둘 다 가로 스크롤 없는지 확인

## 보안 (반드시 지킬 것)

- 키움 App Key/Secret, `live/.env`, Supabase `service_role` 키는 절대 커밋 금지
- `supabase/schema.sql`의 비밀문구 자리(`여기에-긴-비밀문구-입력`)는 그대로 둠. 실제 값은 Supabase SQL Editor에서만
- 웹(`docs/`)에는 anon 키와 숫자만. 키움 호출은 로컬 스크립트에서만

## 남은 일

- [x] 사전 계획서 제출 (10-28)
- [x] GitHub Pages 켜기 (https://isopink.github.io/hynix-298f/ 배포 확인)
- [x] Supabase 프로젝트 생성, schema.sql 실행, config.js 채우기
- [ ] 기획팀 기준값 회신 → `agent/config/*.json` 반영 (지금은 제안값. A 리스크 한도는 10-31까지)
- [x] KRX 정보데이터시스템 계정 → `agent/.env` KRX_ID/KRX_PW. 11-02 로그인·전 종목·수급 확인 (간편가입 계정은 pykrx 로그인 불가 → 일반 회원). 키움으로 대체하면 판단 1회당 호출 120번+ 늘어나 KRX 유지
- [x] 네이버 검색 API → `agent/.env` NAVER_CLIENT_ID/SECRET. 11-02 DART를 빼고 뉴스로 교체. 2026-07 이후 신규 키는 NAVER API HUB(네이버 클라우드)에서만 발급 → 주소·헤더 교체
- [x] 대회 노션 "AI Agent 연결 가이드" 확인 — 공식 MCP 설치 안내일 뿐. 11-02 운영진 확인: 키움 REST API를 직접 부르는 자체 MCP도 허용
- [x] 대회용 계좌·App Key → `live/.env`. 11-02 `snapshot.py --dry` 통과 (kt00018·ka20001 응답 정상, 총자산 5,000만 원), Supabase 업로드도 확인
- [x] `agent/.env` → 11-02 13:40 `MODE=live`, `GIT_PUSH=1` 전환. mock 기록은 work/ 에서 치움. 저장소 git 작성자(S.Lee) 설정 (에이전트 자동 커밋용)
- [x] live 모드 검증: kt00018(잔고)·ka10001(현재가)는 11-02 확인. kt10000(매수)은 에이전트 첫 주문으로 확인 (11-02 14:35 삼성E&A 45주, 11-03 09:32 셀트리온 16주 체결·기록 정상). 모의 서버는 kt00001을 거절하므로 예수금은 kt00018의 추정예탁자산 − 주식평가
- [ ] kt10001(매도) 응답 필드는 에이전트의 첫 매도로 확인 (사람이 테스트 주문을 내면 규정 위반)
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
