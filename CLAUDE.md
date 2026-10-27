# CLAUDE.md — UOStock AI Trader

이 저장소에서 작업할 때 Claude Code가 먼저 읽는 프로젝트 맥락입니다. 사용자(S.Lee, 이석민)는 한국어로 소통하며, 설명은 간단명료하게·과정은 단계별로·할 일은 개조식으로 정리하는 걸 선호합니다.

## 프로젝트

- 2026 나비스트 UOStock AI 자동매매 모의주식투자대회 참가작 (팀 「하이닉스 298층 주민」: 이석민, 박문화)
- 대회 기간 2026-11-02(월) ~ 11-27(금), 국내 주식만, **팀 계좌 1개 · 초기 자산 5,000만 원**
- AI 에이전트(Claude Code)가 투자 판단과 주문을 자동 수행해야 함
  - ❌ 수동 주문, 사람이 AI 주문을 골라 승인·거절하는 것 금지
  - ✅ 코드·프롬프트·전략은 대회 중에도 수정 가능
  - ❌ 키움 API 이용 제한 위반 = 부정행위 → 호출 빈도 보수적으로
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
live/       snapshot.py — 키움 kt00018 잔고 + ka20001 KOSPI를 5분마다 조회 → Supabase RPC push_snapshot
supabase/   schema.sql — comments(익명 게시판), snapshots, app_secret, push_snapshot()
agent/      트레이딩 에이전트 (아직 비어 있음, 예정 구조는 agent/README.md)
reports/    보고서 PDF
```

### 에이전트 설계 (사전 계획서 기준, 구현 예정)

"에이전트는 제안하고, 규칙이 결정한다"
1. 데이터 준비 (Python): pykrx·OpenDartReader·키움 → GS Quant 지표 → 후보 선별, LLM엔 숫자 요약만
2. 시장 국면 서브에이전트: 상승/횡보/하락 → 투자 비중 상한 (상승 90% · 횡보 60% · 하락 30%)
3. 매수 ⇄ 매도 서브에이전트 토론
4. 총괄 Agent: 확신도 산출 → 매수/보유/매도 (기준 미달 시 관망)
5. 수량 계산 (Python): 확신도 → 수량, 손절·익절·최대 보유일
6. 리스크 검증 Hook (PreToolUse, 주문 도구 직전): 현금·종목 한도·일일 손실 → 위반 시 차단
7. 주문 실행 (키움 REST API / MCP) → 판단 근거·체결 결과 기록 → `docs/data/*.json`
8. 주간 회고 서브에이전트: 기준값 조정 제안 + 주간 보고서 초안 (리스크 한도는 수정 불가)

### 대시보드 데이터 형식 (에이전트가 맞춰서 써야 함)

- `equity.json`: `[{date, total, kospi, regime, cap}]` — 실시간 스냅샷이 있으면 자산은 그쪽 우선, regime/cap은 여기서 날짜로 매칭
- `holdings.json`: `[{code, name, qty, avg_price, price, value, pnl_pct, weight, stop, take, held_days, max_days}]`
- `trades.json`: `[{id, time "YYYY-MM-DD HH:MM", code, name, side "매수"|"매도", qty, price, amount, confidence 0~1, regime, bull, bear, decision}]`
- `risk.json`: `[{id, time, name, side, rule, detail}]`
- `system.json`: `[{date, runs, failures, tokens_k}]`
- `reviews.json`: `[{week, period, suggestion, status "반영"|"검토 중"}]`

## 디자인 규칙 (대시보드)

- 다크 캔버스 + 유리 질감 카드(반투명, blur, 16px radius) + 은은한 빨강/파랑 그라데이션 배경
- 빨강 `#da291c`/`#ff5a4a` = 수익·강조, 파랑 `#4aa3d4` = 손실 (국내 증시 관례), 나머지는 무채색
- 흐린 글씨는 `#8c8c8c` 이상 (대비 4.5:1 유지), 축 글씨 11px 이상
- 글은 최소화, 상세는 툴팁(마우스 오버 + 터치 시 고정)
- 하단: GitHub · Instagram 로고(아이콘만), 다음 줄에 `Designed by S.Lee & M.Park`
- 수정 후 데스크톱(1280)·모바일(400) 둘 다 가로 스크롤 없는지 확인

## 보안 (반드시 지킬 것)

- 키움 App Key/Secret, `live/.env`, Supabase `service_role` 키는 절대 커밋 금지
- `supabase/schema.sql`의 비밀문구 자리(`여기에-긴-비밀문구-입력`)는 그대로 둠. 실제 값은 Supabase SQL Editor에서만
- 웹(`docs/`)에는 anon 키와 숫자만. 키움 호출은 로컬 스크립트에서만

## 남은 일

- [ ] 사전 계획서 "1. 투자 전략" 섹션 작성 → PDF 제출 (10-28)
- [ ] GitHub Pages 켜기 (Settings → Pages → main / `/docs`)
- [ ] Supabase 프로젝트 생성, schema.sql 실행, config.js 채우기
- [ ] 10-31 이후 대회용 계좌·App Key → `python live/snapshot.py --dry`로 실제 응답 확인 (kt00018 필드명, ka20001은 미검증)
- [ ] `agent/` 구현 (서브에이전트, Hook, data_prep/sizing/logger, 헤드리스 실행 + 작업 스케줄러)
- [ ] 로그를 `docs/data/*.json` 형식으로 쓰고 git push 자동화
- [ ] 대회 후 README 결과·회고 섹션 채우기

## 커밋

- 작성자: `S.Lee <2sm9908@gmail.com>`
- 기능 단위로 나눠서 커밋 (포트폴리오로 작업 과정이 보이도록)
