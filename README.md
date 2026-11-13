<div align="center">

# Sigma Engine

**Claude Code agents argue. Code decides.**

Team *Hynix 298F* · 2026 Navist AI Auto-Trading Competition (University of Seoul)

[**Live Dashboard →**](https://isopink.github.io/hynix-298f/) · [한국어](README.ko.md)

<img src="assets/dashboard.jpg" alt="Sigma Engine dashboard" width="100%">

</div>

---

An autonomous trading agent for a four-week competition on Korean equities: one team account, ₩50M, and every decision and order must come from the AI. No manual orders and no human approval.

## Concept: agents propose, rules decide

Give an LLM the whole trading loop and two things go wrong:

1. **Hallucinated numbers.** It misreads a price and trades on it.
2. **No hard limits.** "Cut losses at −7%" in a prompt is a wish, not a guarantee.

So the work is split. The model only does what needs judgement, and code does everything that needs to be exact:

| LLM agents | Code |
|---|---|
| Read the facts, argue both sides, score **conviction** (0–1) | Compute every number the model sees |
| Choose buy / hold / sell / watch | Turn conviction into order size |
| Suggest threshold changes after the close | Block any order that breaks a risk limit (Claude Code Hook) |
| | Check every number an agent cites against the source data |

## Architecture

<p align="center"><img src="assets/diagrams/loop.en.png" alt="The whole loop" width="560"></p>

Every 15 minutes (09:30 – 15:15, 24 runs a day) the agent re-screens candidates, debates and places orders. A watcher checks stop-loss, take-profit and holding days every minute; when one hits, it starts a sell-only agent run, so even those orders go through the agent and the Hook.

### One decision run

<p align="center"><img src="assets/diagrams/decision.en.png" alt="One decision run" width="520"></p>

| Agent | Job |
|---|---|
| Lead | Final conviction and action, directs the rest |
| Regime | Market regime (bull / sideways / bear) → stock-exposure cap |
| Position | Sell / hold / add for current holdings |
| Research | Fact sheet for the stocks under debate (news, filings, sector) |
| Bull / Bear | Argue for and against from the same fact sheet |
| Executor | Places the orders: sells first, then buys |

- **Routing.** Only candidates that changed since the last run (price ±1.5%, flow flipped, new news) are debated again; the rest carry their previous call forward.
- **Claim check.** Bull and Bear never search on their own. Code checks every number they cite against the briefing and the fact sheet.

### Guardrails

The risk Hook runs before every `place_order` and the agent cannot skip or edit it.

| Rule | Limit |
|---|---|
| Per stock / holdings / cash | ≤ 20% · ≤ 20 stocks · ≥ 10% cash |
| Per order | ≤ ₩10M, ≤ 8 orders per run |
| Chasing | No buy if already up ≥ 10% today (KOSDAQ ≥ 15%) |
| Losses | −3% in a day → no new buys · −10% total → stock cap halved |

### Self-tuning

<p align="center"><img src="assets/diagrams/tuning.en.png" alt="Self-tuning loop" width="440"></p>

After the close, a **Scorer** grades every decision by what happened next and a separate **Tuner** changes 0–2 thresholds and writes lessons for the next day. Changes stay inside ranges fixed in [`agent/config/tuning.json`](agent/config/tuning.json), and risk limits are off-limits. Every change and rejection is published on the dashboard.

## Stack

Claude Code (headless runs, sub-agents, PreToolUse Hook, own MCP server) · Kiwoom REST API · KRX / Naver news · Python · Supabase (PostgreSQL, `pg_cron`) · D3.js on GitHub Pages · Windows Task Scheduler

```
agent/      trading agent: prompts, sub-agents, risk Hook, config, src, tests → agent/README.md
live/       balance snapshots → Supabase
supabase/   tables, RPC and scheduled market-data collection
docs/       dashboard (single HTML file) + JSON the agent publishes
reports/    plan, weekly reports, change log
```

## Results

> 🏁 After the competition (Nov 29, 2026): final return vs. KODEX 200, whether conviction predicted returns, what the Hook blocked, and what self-tuning changed.

## Team

**Hynix 298F** — Seokmin Lee · Munhwa Park

Thanks to [bitra](https://github.com/BijectiveLabs/bitra) ("agents propose, the system decides"), [qanat](https://github.com/fidetolabs/qanat), [Kiwoom REST API](https://github.com/Kiwoom-Securities/Kiwoom-REST-API) and [gs-quant](https://github.com/goldmansachs/gs-quant).

<div align="center">
<sub>Built for a trading competition. Not investment advice.</sub>
</div>
