<div align="center">

# Sigma Engine

**Claude Code 에이전트가 토론하고, 코드가 결정한다**

2026 나비스트 AI 자동매매 대회 · 팀 「하이닉스 298층 주민」

[**Live Dashboard →**](https://isopink.github.io/hynix-298f/) · [English](README.md)

<img src="assets/dashboard.jpg" alt="Sigma Engine 대시보드" width="100%">

</div>

---

4주 동안 국내 주식을 거래하는 자율 매매 에이전트입니다. 팀 계좌 1개 · 5,000만 원, 판단과 주문은 모두 AI가 직접 합니다. 사람의 수동 주문이나 주문 승인은 없습니다.

## 컨셉: 에이전트는 제안하고, 규칙이 결정한다

LLM에게 매매를 통째로 맡기면 두 가지가 문제입니다.

1. **숫자 환각.** 가격을 잘못 읽고 그대로 주문합니다.
2. **강제력 없음.** 프롬프트의 "−7%면 손절"은 부탁일 뿐 보장이 아닙니다.

그래서 일을 나눴습니다. 판단이 필요한 일만 모델이, 정확해야 하는 일은 코드가 합니다.

| LLM 에이전트 | 코드 |
|---|---|
| 사실을 읽고 찬반 토론, **확신도**(0~1) 매기기 | 모델이 보는 숫자를 전부 먼저 계산 |
| 매수 · 보유 · 매도 · 관망 선택 | 확신도를 주문 수량으로 바꿈 |
| 장 마감 뒤 기준값 조정 제안 | 리스크 한도를 어기는 주문 차단 (Claude Code Hook) |
| | 에이전트가 근거로 쓴 숫자를 원본 자료와 대조 |

## 아키텍처

<p align="center"><img src="assets/diagrams/loop.ko.png" alt="전체 흐름" width="560"></p>

15분마다(09:30 – 15:15, 하루 24번) 후보를 다시 뽑고 토론해 주문합니다. 감시 루프가 1분마다 손절 · 익절 · 보유일을 확인하고, 걸리면 매도 전용 에이전트 실행을 띄웁니다. 그 주문도 에이전트와 Hook을 거칩니다.

### 판단 1회

<p align="center"><img src="assets/diagrams/decision.ko.png" alt="판단 1회" width="520"></p>

| 에이전트 | 하는 일 | 모델 |
|---|---|---|
| 총괄 | 최종 확신도 · 행동 결정, 나머지 지휘 | Opus 5.5 · xhigh |
| 국면 | 시장 국면(상승 · 횡보 · 하락) → 주식 비중 상한 | Opus 5.5 |
| 보유 관리 | 보유 종목 매도 · 보유 · 추가 매수 | Opus 5.5 |
| 근거 수집 | 토론 대상 종목의 사실 표 (뉴스 · 공시 · 업종) | Opus 5.5 |
| 매수 측 / 매도 측 | 같은 사실 표로 찬반 토론 | Opus 5.5 |
| 주문 실행 | 매도 먼저, 그다음 매수 | Haiku 5.5 |

- **라우팅.** 직전 회차보다 달라진 후보(가격 ±1.5%, 수급 방향 바뀜, 새 뉴스)만 다시 토론하고, 나머지는 직전 판단을 이어 씁니다.
- **근거 대조.** 매수 측 · 매도 측은 직접 검색하지 않습니다. 근거에 쓴 숫자는 코드가 브리핑 · 사실 표와 대조합니다.
- **역할별 모델.** 확신도에 영향을 주는 일은 Opus, 기계적인 주문 처리는 Haiku.

### 울타리

리스크 Hook은 모든 `place_order` 직전에 실행되고, 에이전트는 건너뛰지도 고치지도 못합니다.

| 규칙 | 한도 |
|---|---|
| 종목 · 보유 수 · 현금 | 20% 이하 · 20종목 이하 · 현금 10% 이상 |
| 주문 1회 | 1,000만 원 이하, 실행 1번에 8건 이하 |
| 추격 매수 | 오늘 +10% 이상 오른 종목 매수 금지 (코스닥 +15%) |
| 손실 | 하루 −3%면 신규 매수 중단 · 누적 −10%면 주식 비중 상한 절반 |

### 스스로 조정

<p align="center"><img src="assets/diagrams/tuning.ko.png" alt="기준값 자동 조정" width="440"></p>

장 마감 뒤 **채점** 에이전트가 판단마다 그 뒤 결과로 채점하고, 다른 **튜닝** 에이전트가 기준값 0~2개를 바꾸고 다음 날 쓸 교훈을 남깁니다. 범위는 [`agent/config/tuning.json`](agent/config/tuning.json)에 고정돼 있고 리스크 한도는 못 바꿉니다. 반영 · 거절 내역은 모두 대시보드에 공개됩니다.

## 기술

Claude Code (헤드리스 실행, 서브에이전트, PreToolUse Hook, 자체 MCP 서버) · 키움 REST API · KRX / 네이버 뉴스 · Python · Supabase (PostgreSQL, `pg_cron`) · D3.js + GitHub Pages · Windows 작업 스케줄러

```
agent/      매매 에이전트: 지시문, 서브에이전트, 리스크 Hook, 설정, 코드, 테스트 → agent/README.md
live/       잔고 스냅샷 → Supabase
supabase/   테이블, RPC, 시장 데이터 예약 수집
docs/       대시보드 (HTML 한 파일) + 에이전트가 올리는 JSON
reports/    계획서, 주간 보고서, 변경 기록
```

## 결과

> 🏁 대회 종료 후 (2026.11.29): KODEX 200 대비 최종 수익률, 확신도가 수익을 예측했는지, Hook이 막은 주문, 자동 조정이 바꾼 것

## 팀

**하이닉스 298층 주민** — 이석민 · 박문화

참고: [bitra](https://github.com/BijectiveLabs/bitra) ("에이전트는 제안하고 시스템이 결정한다"), [qanat](https://github.com/fidetolabs/qanat), [Kiwoom REST API](https://github.com/Kiwoom-Securities/Kiwoom-REST-API), [gs-quant](https://github.com/goldmansachs/gs-quant)

<div align="center">
<sub>매매 대회용으로 만든 프로젝트입니다. 투자 권유가 아닙니다.</sub>
</div>
