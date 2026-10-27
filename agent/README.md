# agent/

The trading agent lives here. It is being filled in ahead of the competition start (Nov 2, 2026).

## Planned layout

```
agent/
├── .claude/
│   ├── agents/          # Sub-agent definitions
│   │   ├── regime.md    #   market regime
│   │   ├── bull.md      #   bull case
│   │   ├── bear.md      #   bear case
│   │   └── review.md    #   weekly review
│   ├── settings.json    # Hook registration (risk check before the order tool runs)
│   └── hooks/
│       └── risk_check.py
├── src/
│   ├── data_prep.py     # Prices, flows, filings → indicators → candidate screen
│   ├── sizing.py        # Conviction → quantity, stop-loss, take-profit, max holding days
│   └── logger.py        # Decision & fill log → docs/data/*.json
├── CLAUDE.md            # Lead agent instructions
└── run.bat              # Headless run (Task Scheduler)
```

> Kiwoom App Key / Secret and any `.env` file are never committed (excluded via `.gitignore`).
