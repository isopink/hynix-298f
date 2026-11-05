# 전략 변경 로그

Sigma Six 트레이딩 에이전트의 **판단·매매 규칙** 변경만 모은 기록입니다 (대시보드·운영 변경 제외). 최신이 위.
사전 계획서(10-28) 이후부터, 시각은 커밋 시각(KST). 기준값 자동 조정(매일 16:00) 결과는 대시보드 Feedback Loop 에 따로 쌓입니다.

## 11/05 (목) · 11건

| 시각 | 변경 내용 | 커밋 |
|:---:|---|:---:|
| 14:02 | KODEX 200 종목당 한도 10→20% (확신도에 따라 5~20%), 급락일 예외 매수 크기 7→15% | [e04a9ea](https://github.com/isopink/hynix-298f/commit/e04a9ea) |
| 13:54 | 급락일 지수 예외: KODEX 200 이 오늘 −3% 이하면 15:00·15:15 회차에 하락 국면이어도 매수 허용 (7%, 최대 5일). 3년 검증 48번 평균 +0.83%·승률 83% | [abaffc1](https://github.com/isopink/hynix-298f/commit/abaffc1) |
| 13:28 | 판단 매도 분할: 보정 후 매도 확신도 0.55~0.65 미만이면 절반, 0.65 이상이면 전량 (손절·익절·보유일 규칙 매도는 항상 전량) | [1de8b31](https://github.com/isopink/hynix-298f/commit/1de8b31) |
| 13:23 | 15:15 회차에 급락 반등 후보(거래대금 상위 30 중 오늘 −5% 이하, 최대 3개) 추가 · 매수는 기존 확신도 기준, 크기 종목당 7% (3년 검증상 규칙 매수는 손해라 판단 재료로만) | [50d6ecd](https://github.com/isopink/hynix-298f/commit/50d6ecd) |
| 13:02 | 모든 판단(15분마다, 하루 24번)을 매매로 · 그날 판 종목은 다시 사지 않음 (팔고 바로 다시 사는 왕복 수수료 방지) | [8609568](https://github.com/isopink/hynix-298f/commit/8609568) |
| 12:55 | 12:30 매매 회차 추가 (하루 7번, 점심 1시간 30분 공백 메움) | [9fb29b2](https://github.com/isopink/hynix-298f/commit/9fb29b2) |
| 11:00 | 회전율 올리기: 소액 매수 구간 0.55~0.62 · 익절 +15→+10% · 최대 보유 10→5일(보유 종목에도 적용) · 하락 국면 후보 추세 조건을 '20일선 위'로 완화 | [6d7f083](https://github.com/isopink/hynix-298f/commit/6d7f083) |
| 10:54 | 1주차 계수 0.75 → 1.0 (남은 1주차 목·금도 국면 상한 60%·종목당 5~10% 그대로) | [b02a377](https://github.com/isopink/hynix-298f/commit/b02a377) |
| 10:09 | 소액 매수 구간: 보정 후 확신도가 매수 기준 바로 아래(0.58~0.62)면 종목당 2.5%로만 매수 (하락장에서 기준을 내리지 않고 매매·분산 확대) | [2826ab9](https://github.com/isopink/hynix-298f/commit/2826ab9) |
| 08:44 | 판단마다 직전 2회 판단(행동·확신도·결정)을 브리핑에 넣고, 근거가 그대로면 확신도를 0.05 넘게 바꾸지 않도록 (매매 회차가 판단 갱신을 이어받음) | [4fede0b](https://github.com/isopink/hynix-298f/commit/4fede0b) |
| 00:07 | 인버스는 종목당 10% 제한의 예외: 확신도에 따라 인버스 한도 20%까지 한 번에 매수 | [86eabd3](https://github.com/isopink/hynix-298f/commit/86eabd3) |

## 11/04 (수) · 14건

| 시각 | 변경 내용 | 커밋 |
|:---:|---|:---:|
| 21:16 | 기획팀 합의: 매수 확신도 0.65→0.62 · 하락 국면 상한 50→60% · 종목당 크기 10~20% → 5~10% (최대 20종목 분산) · 자동 조정이 보정 후 확신도로 관망 판단 | [a62e03d](https://github.com/isopink/hynix-298f/commit/a62e03d) |
| 21:16 | 후보 확대: 08:30 분석 대상을 코스피 45 + 코스닥 25로 따로 · 후보 10→15개 · KODEX 인버스·200 외 ETF·ETN 차단 | [7176a63](https://github.com/isopink/hynix-298f/commit/7176a63) |
| 14:28 | 놓친 매매 회차는 다음 판단 회차가 대신 매매, 매매 회차는 앞 실행을 최대 10분 기다림 | [f2087e3](https://github.com/isopink/hynix-298f/commit/f2087e3) |
| 13:55 | 마지막 매매 15:15, 판단도 15:15 까지 | [71f5011](https://github.com/isopink/hynix-298f/commit/71f5011) |
| 13:53 | 매매 시각을 정각 · 30분을 피해 09:45 · 10:45 · 11:45 · 13:15 · 14:15 로 | [bbac368](https://github.com/isopink/hynix-298f/commit/bbac368) |
| 13:29 | 검토한 후보를 전부 기록하고 판단 카드에 변동성 표시 | [27b333c](https://github.com/isopink/hynix-298f/commit/27b333c) |
| 13:18 | 매매 시각을 09:45 · 10:30 · 11:30 · 13:00 · 14:00 · 15:00 으로 (장 초반 · 점심 회피, 마감 직전 포함) | [b9f6fb3](https://github.com/isopink/hynix-298f/commit/b9f6fb3) |
| 13:14 | 판단 30분 → 15분마다 (하루 23번), 주문은 그대로 매시 30분 | [c741b67](https://github.com/isopink/hynix-298f/commit/c741b67) |
| 12:42 | KODEX 200 을 지수 ETF 후보로 추가 (상승 · 횡보 국면에서만, 인버스와 짝) | [2902ca0](https://github.com/isopink/hynix-298f/commit/2902ca0) |
| 12:16 | 이미 보유한 인버스에도 새 청산 규칙 적용, ETF 매도세 없음 반영 | [9408358](https://github.com/isopink/hynix-298f/commit/9408358) |
| 12:10 | 손절 · 익절 감시 5분 → 1분, 하루 1번 제한 대신 종목별 재시도 | [8dbdc6f](https://github.com/isopink/hynix-298f/commit/8dbdc6f) |
| 12:10 | 인버스: 수수료 · 세금 뺀 순익 +1.5% 익절 · 최대 2일 보유 · 하루 1번 매수 (KOSPI 1분봉 시뮬레이션 근거) | [1e7b609](https://github.com/isopink/hynix-298f/commit/1e7b609) |
| 09:53 | 하락장 KODEX 인버스 매매 허용 (운영진 확인, 주식 상한과 별도 최대 20%), 장중 후보가 적으면 5개까지 채움 | [0ea8f9f](https://github.com/isopink/hynix-298f/commit/0ea8f9f) |
| 08:29 | 손절 · 익절 감시 시작을 09:05 → 08:30 (장 전 매도는 09:00 동시호가) | [0b6c34c](https://github.com/isopink/hynix-298f/commit/0b6c34c) |

## 11/03 (화) · 12건

| 시각 | 변경 내용 | 커밋 |
|:---:|---|:---:|
| 20:44 | 변동성 100% 초과 종목도 ⚡고변동 몫으로 최대 3개 후보 포함 (종목당 5% · 손절 −12% · 익절 +20%) | [e133948](https://github.com/isopink/hynix-298f/commit/e133948) |
| 15:38 | RSI 과열 매도 보정 기준 70 → 65 | [c82cf37](https://github.com/isopink/hynix-298f/commit/c82cf37) |
| 12:53 | 판단 갱신 주기를 15분 → 30분 (사용 한도) | [fea9bfb](https://github.com/isopink/hynix-298f/commit/fea9bfb) |
| 12:42 | 매매는 1시간에 1번, 판단은 15분마다 갱신 | [a84eb26](https://github.com/isopink/hynix-298f/commit/a84eb26) |
| 12:32 | 정기 판단을 15분마다로 (09:15~15:15) | [df92255](https://github.com/isopink/hynix-298f/commit/df92255) |
| 12:07 | 최대 보유 종목 수 6 → 20 | [d445f46](https://github.com/isopink/hynix-298f/commit/d445f46) |
| 12:07 | 하락 국면 신규 매수 확신도 −0.05 → +0.05 로 반전, RSI 를 판단 직전 현재가로 다시 계산 | [80fac33](https://github.com/isopink/hynix-298f/commit/80fac33) |
| 11:48 | 기획팀 기준값 반영: 매수 확신도 0.60→0.65 · 매도 0.60→0.55 · 1주차 계수 0.5→0.75 | [1f65b2b](https://github.com/isopink/hynix-298f/commit/1f65b2b) |
| 10:30 | 정기 판단 직전 장중 수급(키움 거래대금 · 외국인 · 기관 순매수 순위)으로 후보 재선별 | [82d374f](https://github.com/isopink/hynix-298f/commit/82d374f) |
| 10:26 | 기준값 자동 조정을 화 · 수 · 목 → 평일 매일로 | [b06a214](https://github.com/isopink/hynix-298f/commit/b06a214) |
| 10:25 | RSI(14) 70 이상 보유 종목 매도 확신도 +0.05 과열 보정 | [75319f1](https://github.com/isopink/hynix-298f/commit/75319f1) |
| 10:24 | RSI(14) 35 미만 매수 확신도 +0.05 과매도 보정 (코드가 적용, 악재 뉴스 종목 제외) | [cf4fa7c](https://github.com/isopink/hynix-298f/commit/cf4fa7c) |

## 11/02 (월) · 9건

| 시각 | 변경 내용 | 커밋 |
|:---:|---|:---:|
| 16:31 | 모의서버 실제 거래 비용 반영 (수수료 0.35% · 매도세 0.2%, 첫 체결에서 역산) | [c229b4c](https://github.com/isopink/hynix-298f/commit/c229b4c) |
| 16:29 | 기준값 자동 조정 도입 (화 · 수 · 목 장 마감 뒤, 허용 범위 · 변경 폭 · 쿨다운 규칙 안에서만) | [c4d973f](https://github.com/isopink/hynix-298f/commit/c4d973f) |
| 15:03 | 4주 수익률 순위 대회에 맞춘 조정 (11-03부터): 추세 기준 20·60일선 → 5·20일선, 국면 상한 횡보 60→70% · 하락 30→50%, 4주차 계수 0.5→1.0, 변동성 100% 초과 제외, 5일 +20% 급등 감점 | [dd7e039](https://github.com/isopink/hynix-298f/commit/dd7e039) |
| 14:19 | 주문 전 당일 등락 확인, +10% 이상 급등 종목 추격 매수 금지, 키움 초당 1회 호출 준수 | [306c432](https://github.com/isopink/hynix-298f/commit/306c432) |
| 14:06 | 국면 힌트를 장중 실시간 KOSPI 로 다시 계산 | [37f7a64](https://github.com/isopink/hynix-298f/commit/37f7a64) |
| 13:04 | 정기 판단에 11:00 회차 추가 (09:30 · 14:30 → 하루 3번) | [c3e7b75](https://github.com/isopink/hynix-298f/commit/c3e7b75) |
| 11:38 | 서브에이전트(국면 · 매수 측 · 매도 측 · 회고) · 총괄 규칙 · 리스크 검증 Hook 추가 | [e82c2c2](https://github.com/isopink/hynix-298f/commit/e82c2c2) |
| 11:38 | 데이터 준비: 지표 계산 · 후보 선별 · 네이버 뉴스 | [6c60c8b](https://github.com/isopink/hynix-298f/commit/6c60c8b) |
| 11:38 | 에이전트 기준값 · 수량 계산 · 리스크 규칙과 테스트 추가 (초기 전략값) | [41f0adb](https://github.com/isopink/hynix-298f/commit/41f0adb) |
