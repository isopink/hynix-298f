# agent/

The trading agent. **The agent proposes, the rules decide**: Claude Code reads the market and debates each stock; Python code computes indicators and order sizes; a Claude Code hook blocks any order that breaks a risk limit.

## Daily schedule (weekdays, KST)

| Time | Run | LLM |
|---|---|---|
| 08:30 | `prep` — account + data prep → `work/briefing.json` | no |
| 08:30–15:20 | `monitor` — every 5 min, checks stop / take-profit / max holding days; launches an `exit` run when hit | only when triggered |
| 09:30–15:00, every 15 min | `decide` — intraday re-screen → regime → bull ⇄ bear debate → lead agent decides → orders only in `params.schedule.trade_times` (09:45, 10:45, 11:45, 13:15, 14:15, 14:45); other slots run as `view` (same debate, no orders) | yes |
| 15:45 | `close` — record today's equity, publish to dashboard | no |
| 16:00 | `tune` — agent proposes 0–2 threshold changes; `src/tuning.py` applies only those inside `config/tuning.json` and commits | yes |
| Sat 10:00 | `review` — weekly review + report draft | yes |
| always (from logon) | `sync` — every minute, pulls pushed code, checks it, restarts `monitor` / the balance loop if their code changed | no |

Register them with `setup_tasks.ps1` (Windows Task Scheduler). The agent runs on an always-on PC and is edited from a laptop; see [MOVE_PC.md](MOVE_PC.md) (Korean) for moving it between machines.

## Layout

```
agent/
├── CLAUDE.md                 # Lead agent instructions (decide / exit / review runs)
├── .claude/
│   ├── agents/               # Sub-agents: regime, bull, bear, review
│   ├── hooks/risk_check.py   # PreToolUse hook on mcp__kiwoom__place_order
│   └── settings.json         # Hook registration, tool permissions (no Bash / Edit / Write)
├── .mcp.json                 # kiwoom MCP server
├── config/
│   ├── risk_limits.json      # Fixed for the whole competition; enforced by the hook
│   ├── params.json           # Decision thresholds, conviction adjustments, screen settings (auto-tuned daily)
│   └── tuning.json           # What the tuner may change: keys, ranges, step size, cooldown
├── src/
│   ├── data_prep.py          # pykrx + Naver news → GS Quant indicators → candidate screen
│   ├── intraday.py           # Before each decision: Kiwoom rank APIs → re-screen candidates, intraday RSI
│   ├── sizing.py             # Conviction → quantity, stop, take-profit, max holding days
│   ├── risk.py               # Risk rules (shared by the hook and the MCP server)
│   ├── broker.py             # mock account / Kiwoom REST
│   ├── mcp_server.py         # Tools the agent can call
│   ├── logger.py             # work/journal.jsonl → docs/data/*.json
│   ├── monitor.py            # Intraday stop / take-profit watcher
│   ├── tuning.py             # Validates and applies the daily threshold changes
│   └── sync.py               # Pulls pushed code every minute and restarts the loops that changed
├── tests/test_rules.py
├── run.py · run.bat          # Entry point for each run
└── setup_tasks.ps1           # Task Scheduler registration
```

## Setup

```bat
cd agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      :: fill KRX_ID / KRX_PW / NAVER_CLIENT_ID / NAVER_CLIENT_SECRET, MODE
.venv\Scripts\python tests\test_rules.py
.venv\Scripts\python run.py prep
.venv\Scripts\python run.py decide
```

- `MODE=mock` trades a virtual account in `work/mock_account.json`. `MODE=live` uses the Kiwoom mock-trading server with keys from `live/.env`.
- Without `KRX_ID` / `KRX_PW`, data prep falls back to a fixed large-cap list without investor flow data.

> Kiwoom App Key / Secret and any `.env` file are never committed (excluded via `.gitignore`).
