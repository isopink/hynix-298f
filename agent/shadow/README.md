# 그림자 운영 (11-08)

온톨로지 버전([sigma-six-ontology](https://github.com/kyaa468-ui/sigma-six-ontology))을 실제 매매 옆에서 **가상 계좌로** 나란히 돌려, 지금 방식과 비교합니다. 이 브랜치(`shadow/ontology`)는 실제 매매에 쓰지 않습니다.

## 설치 (데스크톱, 한 번)

```powershell
cd C:\dev\uostock-ai-trader
git fetch origin shadow/ontology
git show origin/shadow/ontology:agent/shadow/setup_shadow.ps1 > $env:TEMP\setup_shadow.ps1
powershell -ExecutionPolicy Bypass -File $env:TEMP\setup_shadow.ps1
```

`C:\dev\hynix-shadow` 에 이 브랜치를 받고, 따로 파이썬 환경을 만든 뒤 작업 6개(`Hynix298S-*`)를 등록합니다.

## 어떻게 도는지

| 시각 | 실제 | 그림자 |
|---|---|---|
| 08:30 / 08:35 | 준비 · 감시 | 준비 · 감시 (첫날 가상 계좌를 실제 계좌로 시작) |
| 09:30~15:15 / 09:33~15:18 | 15분마다 판단·주문 | 15분마다 판단·**가상** 주문 (3분 늦게) |
| 15:45 / 15:48 | 마감 기록 | 마감 기록 |
| 15:50·16:00 / 16:40·16:50 | 회고(수·금) · 조정 | 회고(수·금) · 조정 |

- **키움을 새로 부르지 않음**: 장중 순위 원문은 실제 시스템이 방금 받은 `work/rank_raw/`, 현재가는 실제 `work/quotes.json`·브리핑·잔고 스냅샷을 읽습니다. 없으면 pykrx.
- **실제 매매에 양보**: 실제 시스템이 최근 1시간 안에 실패했으면(사용 한도 등) 그림자 판단은 쉽니다.
- **아무것도 올리지 않음**: `GIT_PUSH=0`, 실제 저장소 파일은 읽기만 합니다.

## 비교

```powershell
C:\dev\hynix-shadow\agent\.venv\Scripts\python.exe C:\dev\hynix-shadow\agent\shadow\compare.py
```

날짜별 자산·수익률 차·체결·관망·판단 1회 평균 시간·토큰·실패를 나란히 보여 줍니다.

## 끄기

```powershell
powershell -ExecutionPolicy Bypass -File C:\dev\hynix-shadow\agent\shadow\setup_shadow.ps1 -Remove
```
