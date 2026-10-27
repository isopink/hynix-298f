# agent/

트레이딩 에이전트 코드가 들어갈 폴더입니다. 대회 시작(2026.11.02) 전까지 이 구조로 채워 나갑니다.

## 예정 구조

```
agent/
├── .claude/
│   ├── agents/          # 서브에이전트 정의
│   │   ├── regime.md    #   시장 국면
│   │   ├── bull.md      #   매수 측
│   │   ├── bear.md      #   매도 측
│   │   └── review.md    #   주간 회고
│   ├── settings.json    # Hook 등록 (주문 도구 실행 직전 리스크 검사)
│   └── hooks/
│       └── risk_check.py
├── src/
│   ├── data_prep.py     # 시세·수급·공시 수집, 지표 계산, 후보 선별
│   ├── sizing.py        # 확신도 → 수량, 손절·익절·최대 보유일
│   └── logger.py        # 판단·체결 로그 → docs/data/*.json
├── CLAUDE.md            # 총괄 Agent 지침
└── run.bat              # 헤드리스 실행 (작업 스케줄러)
```

> 키움 App Key·Secret, `.env` 파일은 절대 커밋하지 않습니다 (`.gitignore`로 제외).
