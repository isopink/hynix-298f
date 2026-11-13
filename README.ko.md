<div align="center">

# Sigma Engine

**Claude Code 에이전트가 토론하고, 코드가 결정한다**

2026 나비스트 AI 자동매매 대회 · 팀 「하이닉스 298층 주민」

[**Live Dashboard →**](https://isopink.github.io/hynix-298f/) · [English](README.md)

![Claude Code](https://img.shields.io/badge/Agent-Claude%20Code-d97757?style=flat-square)
![Kiwoom](https://img.shields.io/badge/Broker-Kiwoom%20REST%20API-1f4fa3?style=flat-square)
![Supabase](https://img.shields.io/badge/Realtime-Supabase-3ecf8e?style=flat-square)
![D3](https://img.shields.io/badge/Viz-D3.js-f9a03c?style=flat-square)
![Status](https://img.shields.io/badge/Status-대회%20진행%20중-da291c?style=flat-square)

<img src="assets/dashboard.jpg" alt="Trading Dashboard" width="100%">

</div>

---

## 한눈에 보기

| | |
|---|---|
| **대회** | 국내 주식, 2026.11.02 – 11.27 · 팀 계좌 1개 · 5,000만 원 |
| **규칙** | 판단과 주문은 AI가 직접. 사람의 수동 주문·주문 승인 금지 |
| **접근** | 역할을 나눈 Claude 에이전트 10개가 사실을 모으고 토론해 확신도만 매김. 수량은 Python이 계산하고, Hook이 주문을 막을 수 있음 |
| **비교 기준** | KODEX 200 (11/2 시가 대비) |
| **주기** | 15분마다 판단하고 매번 주문 (09:30 – 15:15, 하루 24번). 그날 판 종목은 다시 사지 않음 |
| **결과** | 🏁 대회 종료 후 (2026.11.29) |

## 왜 이렇게 만들었나

LLM에게 매매를 통째로 맡기면 두 가지가 문제입니다.

1. **숫자 환각** — 가격을 잘못 읽고 그대로 주문
2. **강제력 없음** — 프롬프트의 "−7%면 손절"은 부탁일 뿐 보장이 아님

그래서 원칙은 하나입니다. **에이전트는 제안하고, 규칙이 결정한다.**

- 모델이 보는 숫자는 전부 Python이 먼저 계산합니다.
- 주문 수량은 모델이 아니라 Python이 정합니다.
- 리스크 한도는 주문 도구 직전에 실행되는 Claude Code Hook에 있습니다. 에이전트는 건너뛰지도 고치지도 못합니다.

## 동작 방식

### 전체 흐름

<p align="center"><img src="assets/diagrams/loop.ko.png" alt="전체 흐름" width="560"></p>

### 판단 1회

<p align="center"><img src="assets/diagrams/decision.ko.png" alt="판단 1회" width="520"></p>

매도를 먼저 하고 매수는 그다음입니다. 직전 회차보다 달라진 후보만 근거 수집과 토론을 거치고, 나머지는 직전 판단을 이어 씁니다. 매수 측과 매도 측은 직접 검색하지 않고 근거 수집 에이전트가 만든 같은 사실 표로 토론하며, 근거에 쓴 숫자는 코드가 브리핑과 대조합니다.

손절·익절·최대 보유일은 감시 루프가 1분마다 확인하고, 걸리면 매도 전용 에이전트 실행을 띄웁니다. 그 주문도 감시 루프가 직접 내지 않고 에이전트와 Hook을 거칩니다.

### 에이전트 (11-12 역할 분리)

| 에이전트 | 하는 일 | 언제 | 모델 · effort |
|---|---|---|---|
| 총괄 | 결과를 모아 최종 확신도 · 행동 결정, 서브에이전트 지휘 | 모든 실행 | Opus 5.5 · xhigh |
| 국면 | 지수 추세(5·20일선)와 변동성 → 상승 / 횡보 / 하락 | 15분 판단 | Opus 5.5 · high |
| 보유 관리 | 보유 종목의 매도 · 보유 · 추가 매수 확신도. 오른 종목을 일찍 팔지 않기 | 15분 판단 | Opus 5.5 · xhigh |
| 근거 수집 | 토론 대상 종목의 뉴스 · 공시 · 업종 · 해외 사실 표 (의견 없음, 검색 6번 · 8분 상한) | 15분 판단 | Opus 5.5 · xhigh |
| 매수 측 / 매도 측 | 같은 사실 표로 후보 종목 찬반 토론 | 15분 판단 | Opus 5.5 · high / xhigh |
| 주문 실행 | 결정 목록대로 매도 → 매수 → 기록 | 15분 판단 | Haiku 5.5 |
| 채점 | 판단마다 그 뒤 결과로 채점, 원인 정리 | 평일 16:00 | Opus 5.5 · max |
| 자동 튜닝 | 기준값 0~2개 · 교훈 2~5줄 제출 | 평일 16:00 | Opus 5.5 · max |
| 회고 | 주간 분석, 조정 제안 1개 | 수 · 금 15:50 | Opus 5.5 · max |
| 보고서 작성 | 주간 운용보고서 초안 (매매 루프 밖) | 수 · 금 17:00 | Sonnet 5.5 · medium |

국면 · 보유 관리 · 근거 수집은 동시에 돕니다. 역할마다 모델을 다르게 써서, 확신도에 영향을 주는 에이전트는 Opus로(가장 중요한 판단은 xhigh), 기계적인 주문 처리는 Haiku로 돌립니다.

### 코드가 하는 일

| 역할 | 하는 일 |
|---|---|
| 데이터 준비 | KRX 시세·수급, 네이버 뉴스 → GS Quant 지표 → 후보 선별 (코스피 10 + 코스닥 5, 고변동 몫 따로) |
| 장중 재선별 | 키움 거래대금·외국인·기관 순매수 순위 → 새 후보, 장중 RSI |
| 토론 라우팅 | 직전 회차 대비 가격 ±1.5% · 수급 방향 · 새 뉴스 · 새 후보만 토론. 첫 회차와 09:30 · 15:00 · 15:15 는 전부 |
| 근거 숫자 대조 | 매수 측 · 매도 측 · 보유 관리 근거의 숫자가 브리핑에 있는지 확인 |
| 수량 계산 | 확신도 → 종목당 8~12% (소액 매수 4~8%, 코스닥 · 고변동 5% 이하) → 수량. 손절 −7%, 익절 +10%, 최대 5거래일 |
| 리스크 검증 | Claude Code Hook — 모든 `place_order` 직전 실행, 하나라도 위반하면 차단 |
| 장중 감시 | 1분마다 손절·익절·보유일 → 매도 전용 실행 (09:30 전엔 팔지 않음) |
| 주문 | 자체 MCP 서버가 키움 REST API 직접 호출 (운영진 확인 완료) |

### 리스크 한도 (대회 내내 고정)

| 규칙 | 한도 |
|---|---|
| 종목당 비중 | 총자산의 20% 이하 |
| 보유 종목 수 | 20개 이하 |
| 현금 | 총자산의 10% 이상 |
| 주문 1회 | 1,000만 원 이하 · 실행 1번에 8건 이하 |
| 추격 매수 | 오늘 +10% 이상 오른 종목은 매수 금지 (코스닥 +15%, 팀 합의로 둔 유일한 예외) |
| 일일 손실 | −3%면 그날 신규 매수 중단 |
| 누적 손실 | −10%면 주식 비중 상한 절반 |
| 주식 비중 | 국면 상한 × 주차 계수 |

에이전트는 이 값을 못 바꿉니다. 자동 조정도 판단 기준값만, [`agent/config/tuning.json`](agent/config/tuning.json)에 정한 범위 안에서만 바꿉니다.

### 스스로 조정하되, 울타리 안에서

<p align="center"><img src="assets/diagrams/tuning.ko.png" alt="기준값 자동 조정" width="440"></p>

채점과 조정을 다른 에이전트가 맡아, 조정하는 쪽이 자기 판단을 채점하지 않게 했습니다. 반영 · 거절 내역과 교훈은 모두 대시보드 '자동 조정 기록'에 공개됩니다.

<sub>도식 원본: [`assets/diagrams/*.mmd`](assets/diagrams) → `node assets/diagrams/render.js` 또는 `mmdc` 로 다시 그림</sub>

## 하루 일정 (평일)

| 시각 | 실행 | LLM |
|---|---|---|
| 08:25 → | 잔고 스냅샷 1분마다 → Supabase | – |
| 08:30 | `prep` — 계좌, KRX 데이터, 뉴스 → 브리핑 | – |
| 08:30 – 15:20 | `monitor` — 1분마다 손절·익절·보유일 | 걸릴 때만 |
| **09:30 – 15:15, 15분마다** | `decide` — 재선별 → 라우팅 → 토론 → **주문** (하루 24번) | ✓ |
| 15:45 | `close` — 오늘 자산 · KODEX 200 기록 | – |
| 수 · 금 15:50 | `review` — 주간 회고, 조정 제안 | ✓ |
| 16:00 | `tune` — 채점 → 자동 튜닝 | ✓ |
| 수 · 금 17:00 | `report` — 주간 보고서 초안 | ✓ |
| 상시 | `sync` — 1분마다 push된 코드 반영, 바뀐 루프 재시작, 데스크톱 연결 신호 | – |

에이전트는 계속 켜 두는 데스크톱에서 돌고, 수정은 노트북에서 합니다. push하면 1분 안에 데스크톱에 반영됩니다.

## 대시보드

에이전트가 무엇을, 왜 샀는지 한 페이지에서 봅니다. 한국식 색(수익 · 매수 빨강, 손실 · 매도 파랑), 움직임 없는 평면 화면입니다.

<table>
<tr>
<td width="68%"><img src="assets/dashboard-full.jpg" alt="PC 전체 화면"></td>
<td><img src="assets/mobile.jpg" alt="모바일 화면"></td>
</tr>
<tr>
<td align="center"><sub>PC</sub></td>
<td align="center"><sub>폰</sub></td>
</tr>
</table>

| 영역 | 내용 |
|---|---|
| **누적 수익률** | 대회 시작 이후 수익률 vs KODEX 200, 핵심 숫자 6개(KODEX 200 대비 · 오늘 · 손익 · 최대 낙폭 · 체결 · 회전율), 상태 점(서버 · 모니터링 · 에이전트), 실시간 KOSPI |
| **포트폴리오** | 국면 상한 대비 주식 비중 도넛, 비중 순 종목 표 (수수료·세금 반영 수익률) |
| **실시간 판단** | 최근 회차의 국면 · 비중 상한, 종목별 행동 · 확신도 · 판단 근거, 최근 체결 |
| **기록** | 이번 주, 최대 낙폭, 승률, 리스크 한도 사용률, 일별 초과수익, 수익률 캘린더 (운영 사고일 표시) |
| **자동 조정 기록** | 매일 기준값 조정 · 교훈, 주간 회고 제안 |

**서버 상태 점** — 데스크톱이 1분마다 Supabase에 연결 신호를 보내고, 3분 넘게 끊기면 빨갛게 바뀝니다 (11-11 PC가 꺼져 에이전트가 멈춘 일이 계기).

**데이터 경로** — 키움 키는 데스크톱의 `.env`에만 있습니다. 웹은 두 곳에서 읽습니다. 하나는 에이전트가 push하는 `docs/data/` JSON이고, 다른 하나는 Supabase입니다. Supabase에는 잔고 스냅샷이 비밀문구를 확인하는 RPC로만 들어오고, KOSPI 1분봉(네이버)과 투자자별 수급(다음)은 `pg_cron`이 직접 수집합니다. 방문자는 읽기만 할 수 있습니다.

## 기술 스택

| 분야 | 도구 |
|---|---|
| 에이전트 | Claude Code — 헤드리스 실행, 서브에이전트 (역할별 모델 · effort, 동시 실행), PreToolUse Hook, MCP 서버, 도구 허용 목록 (Bash / Edit / Write 금지) |
| 모델 | Claude Opus 5.5 · Sonnet 5.5 · Haiku 5.5 |
| 증권사 | 키움 REST API — 잔고 `kt00018`, 현재가 `ka10001`, 순위 `ka10032` · `ka10065`, 주문 `kt10000` · `kt10001` |
| 시장 데이터 | KRX 정보데이터시스템 (pykrx), NAVER API HUB 뉴스 검색, Supabase로 받는 네이버·다음 금융 |
| 지표 | GS Quant — 이동평균, RSI, 변동성, 최대 낙폭 |
| 대시보드 | HTML · CSS · D3.js v7, 빌드 없음, GitHub Pages |
| 실시간 | Supabase — PostgreSQL, RLS, RPC, `pg_cron`, `pg_net` |
| 스케줄 | Windows 작업 스케줄러 |

## 저장소 구조

```
hynix-298f/
├── agent/                  # 트레이딩 에이전트 → agent/README.md
│   ├── CLAUDE.md           # 총괄 에이전트 지시문
│   ├── .claude/            # 서브에이전트 9개 (regime · position · research · bull · bear · executor ·
│   │                       #   scorer · tuner · review · writer), 리스크 Hook, 권한
│   ├── config/             # risk_limits.json (고정) · params.json (자동 조정) · tuning.json (조정 규칙)
│   ├── src/                # data_prep · intraday · routing · sizing · risk · broker · mcp_server
│   │                       # monitor · tuning · logger · benchmark · sync
│   ├── tests/test_rules.py
│   ├── run.py              # prep / decide / exit / close / tune / review / report / monitor / sync
│   └── setup_tasks.ps1     # 작업 스케줄러 등록
├── docs/                   # 대시보드 (GitHub Pages)
│   ├── index.html          # 단일 파일
│   ├── config.js           # Supabase 주소 + 공개 anon 키
│   └── data/               # 실행마다 에이전트가 쓰는 JSON
├── live/snapshot.py        # 키움 잔고 + KOSPI → Supabase, 30초마다
├── supabase/               # schema.sql · kospi.sql · flow.sql · heartbeat.sql · realtime.sql
├── reports/                # 계획서, 주간·최종 보고서
└── assets/                 # README 이미지
```

## 실행

배포 가이드: [`docs/DEPLOY.md`](docs/DEPLOY.md) · 에이전트 설치: [`agent/README.md`](agent/README.md)

```bash
# 대시보드 로컬 미리보기
cd docs && python -m http.server 8000          # → http://localhost:8000

# 잔고 연결 확인 (live/.env 작성 후)
cd live && python snapshot.py --dry

# 에이전트 1회 실행 (agent/.env 의 MODE=mock 이면 가상 계좌)
cd agent
.venv\Scripts\python tests\test_rules.py
.venv\Scripts\python run.py prep
.venv\Scripts\python run.py decide
```

## 실험: 온톨로지 그림자 엔진 (SiON)

11-09 ~ 11-12에 온톨로지 버전 ([sigma-six-ontology](https://github.com/kyaa468-ui/sigma-six-ontology), 브랜치 `shadow/ontology`)을 가상 계좌로 Sigma 옆에서 같은 시각에 돌려 비교했습니다. 판단 근거 추적은 자세했지만, 토큰이 약 3.5배 들고 학습 기록(전제 · 사례 · 교훈)은 거의 쌓이지 않았으며, 기록 파일이 커져 데스크톱 메모리를 바닥내는 사고가 있었습니다. 그래서 11-12에 멈추고 대회 뒤 다시 보기로 했습니다. 기록과 브랜치는 남겨 두었습니다.

## 결과와 회고

> 🏁 대회 종료 후 (2026.11.29)
>
> - 최종 수익률, KODEX 200 대비 초과수익, 회전율
> - 확신도가 실제 수익을 예측했는가
> - 리스크 Hook이 막은 주문과 그 영향
> - 자동 조정이 무엇을 바꿨고, 도움이 됐는가
> - 다시 한다면 바꿀 것

## 참고한 저장소

| 저장소 | 가져온 것 |
|---|---|
| [BijectiveLabs/bitra](https://github.com/BijectiveLabs/bitra) | "에이전트는 제안하고 시스템이 결정한다", 판단·거절 기록 |
| [fidetolabs/qanat](https://github.com/fidetolabs/qanat) | MCP로 종목 스크리닝을 조회하는 에이전트 |
| [Kiwoom-Securities/Kiwoom-REST-API](https://github.com/Kiwoom-Securities/Kiwoom-REST-API) | 시세·잔고·순위·모의 주문 |
| [goldmansachs/gs-quant](https://github.com/goldmansachs/gs-quant) | 지표 계산 |

## 팀

**하이닉스 298층 주민** — 이석민 · 박문화

[![Instagram](https://img.shields.io/badge/Instagram-@sl2eee-E4405F?style=flat-square&logo=instagram&logoColor=white)](https://www.instagram.com/sl2eee/)

---

<div align="center">
<sub>Designed by S.Lee &amp; M.Park · 매매 대회용으로 만든 프로젝트입니다. 투자 권유가 아닙니다.</sub>
</div>
