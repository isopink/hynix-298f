<div align="center">

# UOStock AI Trader

**Claude Code agents argue. Code decides.**

Team *Hynix 298F* · 2026 Navist UOStock AI Auto-Trading Mock Investment Competition (University of Seoul)

[**Live Dashboard →**](https://isopink.github.io/hynix-298f/) · [한국어](README.ko.md)

![Claude Code](https://img.shields.io/badge/Agent-Claude%20Code-d97757?style=flat-square)
![Kiwoom](https://img.shields.io/badge/Broker-Kiwoom%20REST%20API-1f4fa3?style=flat-square)
![Supabase](https://img.shields.io/badge/Realtime-Supabase-3ecf8e?style=flat-square)
![D3](https://img.shields.io/badge/Viz-D3.js-f9a03c?style=flat-square)
![Status](https://img.shields.io/badge/Status-Competition%20live-da291c?style=flat-square)

<img src="assets/dashboard.jpg" alt="Trading Dashboard" width="100%">

</div>

---

## At a glance

| | |
|---|---|
| **Competition** | Korean equities mock trading, Nov 2 – 27, 2026 · one team account · ₩50M |
| **Rule** | The AI must make every decision and place every order itself. No manual orders, no human approval of orders |
| **Approach** | LLMs debate and score conviction. Python sizes the order, a Hook can veto it |
| **Cadence** | A decision every 15 min (09:30 – 15:00), orders only on the half hour |
| **Result** | 🏁 After the competition (Nov 29, 2026) |

## Why this design

Give an LLM the whole trading loop and two things go wrong:

1. **Hallucinated numbers** — it misreads a price and trades on it.
2. **No hard limits** — "cut losses at −7%" in a prompt is a wish, not a guarantee.

So one rule runs through everything: **agents propose, rules decide.**

- Every number the model sees is computed in Python first.
- Order size is computed in Python, not by the model.
- Risk limits live in a Claude Code Hook that fires before the order tool. The agent cannot skip it or edit it.

## How it works

### The whole loop

<p align="center"><img src="assets/diagrams/loop.en.png" alt="The whole loop" width="560"></p>

### One decision run

<p align="center"><img src="assets/diagrams/decision.en.png" alt="One decision run" width="520"></p>

Sells go first, then buys. Stop-loss, take-profit and max holding days are checked every 5 minutes by a watcher. When one hits, it starts a sell-only agent run. The agent and the Hook still place that order, never the watcher itself.

### Who does what

| Role | Runs as | Job |
|---|---|---|
| Lead agent | Claude Code (headless) | Weighs both sides, scores conviction, places orders through MCP tools |
| Regime | Sub-agent | Reads index trend (5/20-day MAs) and volatility → bull / sideways / bear |
| Bull / Bear | Sub-agents | Argue for and against each stock using only briefing numbers and news |
| Review | Sub-agent | Weekly: reads the log, drafts the weekly report, suggests threshold changes |
| Data prep | Python | KRX prices and flows, Naver news → GS Quant indicators → candidate screen |
| Intraday re-screen | Python | Kiwoom trading-value and foreign/institution net-buy ranks → fresh candidates and live RSI |
| Sizing | Python | Conviction → target weight → quantity; stop −7%, target +15%, max 10 days |
| Risk check | Claude Code Hook | Runs before every `place_order`; any violation blocks the order |
| Tuning | Python + agent | Daily: agent proposes 0–2 threshold changes, code accepts only those inside fixed rules |
| Watcher | Python | Every 5 min: stop / target / holding days → sell-only run |
| Order execution | Own MCP server | Calls the Kiwoom REST API directly (cleared with the organisers) |

### Risk limits (fixed for the whole competition)

| Rule | Limit |
|---|---|
| Per stock | ≤ 20% of equity |
| Holdings | ≤ 20 stocks |
| Cash | ≥ 10% of equity |
| Per order | ≤ ₩10M · ≤ 8 orders per run |
| Chasing | No buy if the stock is already up ≥ 10% today |
| Daily loss | −3% → no new buys today |
| Total loss | −10% → stock cap halved |
| Exposure | Regime cap × week factor |

The agent cannot change these. The tuner only touches decision thresholds, and only inside ranges set in [`agent/config/tuning.json`](agent/config/tuning.json).

### Self-tuning, with guardrails

<p align="center"><img src="assets/diagrams/tuning.en.png" alt="Self-tuning loop" width="440"></p>

Every change and rejection shows up on the dashboard (Feedback Loop).

<sub>Diagram sources: [`assets/diagrams/*.mmd`](assets/diagrams) → `node assets/diagrams/render.js`</sub>

## Daily schedule (weekdays, KST)

| Time | Run | LLM |
|---|---|---|
| 08:30 | `prep` — account, KRX data, news → briefing | – |
| 08:55 → | Balance snapshot every minute → Supabase | – |
| 09:05 – 15:20 | `monitor` — stop / target / holding days every 5 min | only when hit |
| **09:30, 10:30 … 14:30** | `decide` — re-screen → debate → **orders** | ✓ |
| 09:45, 10:00, 10:15 … 15:00 (every 15 min, except :30 slots) | `view` — same debate, **no orders**, refreshes the dashboard | ✓ |
| 15:45 | `close` — record today's equity | – |
| 16:00 | `tune` — threshold self-tuning | ✓ |
| Sat 10:00 | `review` — weekly review and report draft | ✓ |
| always | `sync` — pulls pushed code every minute, restarts loops whose code changed | – |

The agent runs on an always-on desktop and is edited from a laptop. A push reaches the desktop within a minute.

## Dashboard

One page that shows what the agent traded, and why.

<table>
<tr>
<td width="62%"><img src="assets/timeline-tooltip.jpg" alt="Trade timeline"></td>
<td><img src="assets/mobile.jpg" alt="Phone view"></td>
</tr>
<tr>
<td align="center"><sub>Desktop — tap a trade to read the bull case, bear case and final call</sub></td>
<td align="center"><sub>Phone — a short promo view</sub></td>
</tr>
</table>

| Section | What's in it |
|---|---|
| **Hero** | Cumulative return vs. KOSPI since the start, current equity, agent on/off |
| **Live decision** | Latest run: regime, stock cap, each stock's action and conviction (reasons on hover/tap) |
| **Live KOSPI** | 1-minute bars vs. previous close, volume, RSI, investor net buying |
| **Portfolio** | Holdings vs. regime cap, per-stock P&L before / after fees and tax |
| **Record** | This week, max drawdown, win rate, risk-limit usage, daily excess return, return calendar |
| **Agent Black Box** | Trade timeline with debate, Hook blocks, conviction vs. return, token usage, Feedback Loop, full decision log |
| **Cheer board** | Anonymous comments, no login, flood-protected |

The phone shows only the hero, buy/sell calls, holdings P&L, KOSPI and the calendar. The full view is on desktop.

**Data paths** — Kiwoom keys live only in a `.env` on the desktop. The site reads two sources: JSON the agent pushes to `docs/data/`, and Supabase. In Supabase, balance snapshots arrive through a secret-checked RPC, and `pg_cron` collects KOSPI 1-minute bars (Naver) and investor flows (Daum). Visitors are read-only.

## Tech stack

| Area | Tools |
|---|---|
| Agents | Claude Code — headless runs, sub-agents, PreToolUse Hook, MCP server, tool allow-list (no Bash / Edit / Write) |
| Broker | Kiwoom REST API — balance `kt00018`, quote `ka10001`, ranks `ka10032` · `ka10065`, orders `kt10000` · `kt10001` |
| Market data | KRX Data Marketplace (pykrx), NAVER API HUB news search, Naver / Daum Finance via Supabase |
| Indicators | GS Quant — moving averages, RSI, volatility, max drawdown |
| Dashboard | Plain HTML · CSS · D3.js v7, no build step, GitHub Pages |
| Realtime | Supabase — PostgreSQL, RLS, RPC, `pg_cron`, `pg_net` |
| Scheduling | Windows Task Scheduler |

## Repository layout

```
hynix-298f/
├── agent/                  # Trading agent → agent/README.md
│   ├── CLAUDE.md           # Lead agent instructions
│   ├── .claude/            # Sub-agents (regime · bull · bear · review), risk Hook, permissions
│   ├── config/             # risk_limits.json (fixed) · params.json (tuned) · tuning.json (tuning rules)
│   ├── src/                # data_prep · intraday · sizing · risk · broker · mcp_server
│   │                       # monitor · tuning · logger · sync
│   ├── tests/test_rules.py
│   ├── run.py              # prep / decide / exit / close / tune / review / monitor / sync
│   └── setup_tasks.ps1     # Task Scheduler registration
├── docs/                   # Dashboard (GitHub Pages)
│   ├── index.html          # Single file
│   ├── config.js           # Supabase URL + public anon key
│   └── data/               # JSON the agent publishes after each run
├── live/snapshot.py        # Kiwoom balance + KOSPI → Supabase, every minute
├── supabase/               # schema.sql · kospi.sql · flow.sql · ewy.sql
├── reports/                # Plan, weekly and final reports
└── assets/                 # README images
```

## Running it

Deployment guide: [`docs/DEPLOY.md`](docs/DEPLOY.md) · agent setup: [`agent/README.md`](agent/README.md) (both partly Korean).

```bash
# Dashboard locally
cd docs && python -m http.server 8000          # → http://localhost:8000

# Balance connection (after filling live/.env)
cd live && python snapshot.py --dry

# Agent, one run (MODE=mock in agent/.env trades a virtual account)
cd agent
.venv\Scripts\python tests\test_rules.py
.venv\Scripts\python run.py prep
.venv\Scripts\python run.py decide
```

## Results & retrospective

> 🏁 After the competition (Nov 29, 2026)
>
> - Final return, excess return over KOSPI, turnover
> - Did conviction predict returns?
> - What the risk Hook blocked, and what that cost or saved
> - What self-tuning changed, and whether it helped
> - What I'd do differently

## Acknowledgements

| Repository | What I borrowed |
|---|---|
| [BijectiveLabs/bitra](https://github.com/BijectiveLabs/bitra) | "Agents propose, the system decides"; logging decisions and rejections |
| [fidetolabs/qanat](https://github.com/fidetolabs/qanat) | Agents querying stock screens through MCP |
| [Kiwoom-Securities/Kiwoom-REST-API](https://github.com/Kiwoom-Securities/Kiwoom-REST-API) | Quotes, balance, ranks and mock orders |
| [goldmansachs/gs-quant](https://github.com/goldmansachs/gs-quant) | Indicator computation |

## Team

**Hynix 298F** — Seokmin Lee · Munhwa Park

[![Instagram](https://img.shields.io/badge/Instagram-@sl2eee-E4405F?style=flat-square&logo=instagram&logoColor=white)](https://www.instagram.com/sl2eee/)

---

<div align="center">
<sub>Designed by S.Lee &amp; M.Park · Built for a mock-trading competition. Not investment advice.</sub>
</div>
