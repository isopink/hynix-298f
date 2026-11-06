"""
기록 → 대시보드 데이터. work/journal.jsonl · runs.jsonl · account.json 을 읽어 docs/data/*.json 을 다시 씁니다.

  python src/logger.py           # 실행이 끝날 때마다 (trades, risk, holdings, system, reviews, status)
  python src/logger.py --close   # 장 마감 후 하루 한 번 (equity 에 오늘 행 추가)

형식은 루트 CLAUDE.md 의 "대시보드 데이터 형식"을 따릅니다.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def out(name, data):
    C.write_json(os.path.join(C.DOCS_DATA, name + ".json"), data)


def names():
    """코드 → 종목명 (Hook 차단 기록에는 이름이 없어서 여기서 채움)."""
    m = {}
    b = C.read_json(C.BRIEFING, {}) or {}
    for r in b.get("candidates", []) + b.get("holdings", []) + (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", []):
        m[r["code"]] = r["name"]
    for r in C.read_jsonl(C.JOURNAL):
        if r.get("name") and r["name"] != r.get("code"):
            m[r["code"]] = r["name"]
    return m


def trades(rows):
    out_ = [{"id": i + 1, "time": r["time"], "code": r["code"], "name": r["name"], "side": r["side"],
             "qty": r["qty"], "price": r["price"], "amount": r["amount"], "confidence": r["confidence"],
             "regime": r.get("regime"), "bull": r["bull"], "bear": r["bear"], "decision": r["decision"],
             "ordered": r.get("ordered") or FIXES.get(f'{r["time"][:16]}|{r["code"]}')}
            for i, r in enumerate(x for x in rows if x["kind"] == "fill")]
    return reconcile(out_)


FIXES = {k: v for k, v in (C.read_json(os.path.join(C.AGENT, "config", "fill_fixes.json"), {}) or {}).items() if not k.startswith("_")}


def reconcile(ts):
    """체결 기록의 순수량(매수 − 매도)이 실제 잔고와 다르면 그 종목의 마지막 체결 수량을 잔고에 맞춤.
    주문 직후 확인 때 일부만 체결돼 있던 경우를 바로잡음 (journal 은 그대로 두고 대시보드 값만 고침)."""
    acc = C.read_json(C.ACCOUNT, {}) or {}
    if not acc.get("holdings") and not ts:
        return ts
    held = {h["code"]: h["qty"] for h in acc.get("holdings", [])}
    for code in {t["code"] for t in ts}:
        mine = [t for t in ts if t["code"] == code]
        diff = held.get(code, 0) - sum(t["qty"] if t["side"] == "매수" else -t["qty"] for t in mine)
        # 11-05: 덜 체결된 채 기록된 주문(qty < ordered)부터 채움. 예전엔 마지막 체결에 몰아 붙여 HMM 15:21 매도가 76주로 보였음
        for t in mine:
            if not diff or not t.get("ordered") or t["qty"] >= t["ordered"]:
                continue
            sign = 1 if t["side"] == "매수" else -1
            add = min(t["ordered"] - t["qty"], diff * sign) if diff * sign > 0 else 0
            if add:
                t["qty"] += add
                t["amount"] = t["qty"] * t["price"]
                diff -= add * sign
        last = mine[-1]
        q = last["qty"] + (diff if last["side"] == "매수" else -diff)
        if diff and q > 0:
            last["qty"], last["amount"] = q, q * last["price"]
    for t in ts:
        t.pop("ordered", None)
    return ts


def risks(rows, nm):
    seen, res = set(), []
    for r in rows:
        if r["kind"] != "block":
            continue
        key = (r["run"], r["code"], r["side"], r["rule"])   # Hook·서버가 같은 주문을 두 번 막은 건 하나로
        if key in seen:
            continue
        seen.add(key)
        res.append({"id": len(res) + 1, "time": r["time"], "name": nm.get(r["code"], r["code"]),
                    "side": r["side"], "rule": r["rule"], "detail": r["detail"]})
    return res


def holdings():
    acc = C.read_json(C.ACCOUNT)
    if not acc:
        return []
    meta = C.position_meta(acc["holdings"])
    res = []
    for h in acc["holdings"]:
        m = meta.get(h["code"], {})
        res.append({**{k: h[k] for k in ("code", "name", "qty", "avg_price", "price", "value", "pnl_pct")},
                    "weight": round(h["value"] / acc["total"], 4) if acc["total"] else 0,
                    "stop": m.get("stop"), "take": m.get("take"),
                    "held_days": C.business_days(m["entry_date"], C.today()) if m.get("entry_date") else None,
                    "max_days": m.get("max_days")})
    return res


def system():
    by = {}
    for r in C.read_jsonl(C.RUNS):
        d = by.setdefault(r["time"][:10], {"date": r["time"][:10], "runs": 0, "failures": 0, "tokens_k": 0.0})
        d["runs"] += 1
        d["failures"] += 0 if r.get("ok") else 1
        d["tokens_k"] = round(d["tokens_k"] + r.get("tokens", 0) / 1000, 1)
    return sorted(by.values(), key=lambda x: x["date"])


def reviews(rows):
    key = lambda x: (x["week"], bool(x.get("mid")))   # 11-06 수요일 중간 회고 · 토요일 주간 회고를 따로
    res = {}
    for r in rows:
        if r["kind"] == "review":
            res[key(r)] = {"week": r["week"], "mid": bool(r.get("mid")), "period": r["period"], "suggestion": r["suggestion"],
                           "status": r.get("status", "검토 중")}
    old = {key(x): x for x in (C.read_json(os.path.join(C.DOCS_DATA, "reviews.json"), []) or [])}
    times = {key(r): r["time"] for r in rows if r["kind"] == "review"}
    for w, x in res.items():
        # 회고 뒤 조정 실행에서 값이 하나라도 바뀌었으면 반영. 사람이 "반영"으로 바꿔 둔 상태도 유지
        if any(r["kind"] == "tune" and r["time"] > times[w] and r.get("applied") for r in rows) or \
                (w in old and old[w].get("status") == "반영"):
            x["status"] = "반영"
    return [res[w] for w in sorted(res, key=lambda k: (k[0], not k[1]))]   # 같은 주는 수요일 중간 회고가 먼저


def tuning(rows):
    """기준값 자동 조정 이력 (평일). 대시보드 Feedback Loop 카드용."""
    return [{"time": r["time"], "summary": r.get("summary", ""),
             "applied": [{k: a[k] for k in ("key", "label", "from", "to", "reason")} for a in r.get("applied", [])],
             "rejected": [{"key": b["key"], "to": b.get("to"), "rejected": b["rejected"]} for b in r.get("rejected", [])]}
            for r in rows if r["kind"] == "tune"]


def next_run(now=None):
    now = now or C.now()
    times = C.params()["schedule"]["decide_times"]
    d = now
    for _ in range(8):
        if d.weekday() < 5:
            for t in times:
                hh, mm = map(int, t.split(":"))
                cand = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if cand > now:
                    return C.stamp(cand)
        d = (d + timedelta(days=1)).replace(hour=0, minute=0)
    return None


def status(note=""):
    runs = C.read_jsonl(C.RUNS)
    t = C.today().isoformat()
    todays = [r for r in runs if r["time"].startswith(t)]
    last = runs[-1] if runs else None
    return {"last_run": last["time"] if last else None, "last_ok": bool(last and last.get("ok")),
            "next_run": next_run(), "runs_today": len(todays),
            "failures_today": sum(1 for r in todays if not r.get("ok")), "note": note or (last or {}).get("note", ""),
            "sync": C.read_json(os.path.join(C.WORK, "sync_state.json"))}   # 코드 자동 동기화 상태 (src/sync.py)


def briefing():
    """08:30 데이터 준비 결과 요약 (시장 지표 + 후보 종목). 판단 전에 '현재 판단' 카드에 보여줌."""
    b = C.read_json(C.BRIEFING, {}) or {}
    if not b:
        return {}
    m = b.get("market", {})
    keep = ("code", "name", "close", "ret5", "ret20", "rsi14", "vol20", "foreign_net", "inst_net", "score", "news")
    mk = C.read_json(C.MARKETS, {}) or {}
    live = ("price", "chg", "activity", "foreign_today", "inst_today")   # 장중 재선별(intraday.py)이 채운 값
    return {"created": b["created"], "asof": b["asof"], "universe": b.get("universe_size"), "source": b.get("source"),
            "market": {k: m.get(k) for k in ("source", "close", "ma20", "ma60", "ret5", "ret20", "rsi14", "rule_hint", "closes")},
            "intraday": b.get("intraday"),
            "candidates": [{**{k: c.get(k) for k in keep + live if k in keep or c.get(k) is not None},
                            "exchange": C.market_of(c["code"], markets=mk)} for c in b.get("candidates", [])]}   # KOSPI · KOSDAQ · ETF


def run_items(run, nm):
    """한 실행의 종목별 결정 (체결이 있으면 결정보다 우선, Hook 차단 사유 붙임)."""
    items = {}
    for r in run:
        if r["kind"] == "decision":
            items[r["code"]] = {"code": r["code"], "name": nm.get(r["code"], r.get("name")), "action": r["action"],
                                "confidence": r["confidence"], "bull": r["bull"], "bear": r["bear"], "decision": r["decision"]}
        elif r["kind"] == "fill":
            items[r["code"]] = {"code": r["code"], "name": r["name"], "action": r["side"], "qty": r["qty"], "price": r["price"],
                                "confidence": r["confidence"], "bull": r["bull"], "bear": r["bear"], "decision": r["decision"]}
    for r in run:
        if r["kind"] == "block" and r["code"] in items and "blocked" not in items[r["code"]]:
            items[r["code"]]["blocked"] = f'{r["rule"]}: {r["detail"]}'
    order = {"매수": 0, "매수 예정": 0, "매도": 1, "매도 예정": 1}
    return sorted(items.values(), key=lambda x: (order.get(x["action"], 2), -float(x["confidence"] or 0)))


def decision(rows, nm):
    """가장 최근 정기 판단 1회분 (국면 + 종목별 결정). 대시보드 상단 '현재 판단' 카드용."""
    reg = next((r for r in reversed(rows) if r["kind"] == "regime"), None)
    if not reg:
        return {}
    items = run_items([r for r in rows if r.get("run") == reg["run"]], nm)
    b = C.read_json(C.BRIEFING, {}) or {}
    mk = C.read_json(C.MARKETS, {}) or {}
    for it in items:   # 20일 변동성 (연율화) · 시장. 대시보드가 종목명 옆·아래에 표시
        row = C.briefing_row(it["code"], b) or {}
        if row.get("vol20") is not None:
            it["vol20"] = row["vol20"]
        it["exchange"] = C.market_of(it["code"], markets=mk)
    return {"time": reg["time"], "regime": reg["regime"], "cap": reg["cap"], "reason": reg.get("reason", ""),
            "mode": "view" if reg.get("mode") == "view" else "trade", "next_trade": C.next_trade_time(),
            "items": items, "last_trade": last_trade(rows, nm)}


def last_trade(rows, nm):
    """오늘 마지막 매매 회차의 결과 요약 (샀다 / 팔았다 / 막혔다 / 관망·보유 몇 종목). 판단 카드 위 한 줄용. 오늘 매매 회차가 없으면 None."""
    t = C.today().isoformat()
    reg = next((r for r in reversed(rows) if r["kind"] == "regime" and r.get("mode") != "view"
                and r["time"].startswith(t) and r.get("run")), None)
    if not reg:
        return None
    items = run_items([r for r in rows if r.get("run") == reg["run"]], nm)
    pick = lambda a: [{"name": i["name"], "qty": i.get("qty")} for i in items if i["action"] == a]   # noqa: E731
    return {"time": reg["time"][11:16], "regime": reg["regime"], "bought": pick("매수"), "sold": pick("매도"),
            "blocked": [{"name": i["name"], "rule": i["blocked"].split(":")[0]} for i in items
                        if i.get("blocked") and i["action"] not in ("매수", "매도")],
            "watch": sum(i["action"] == "관망" for i in items), "hold": sum(i["action"] == "보유" for i in items)}


def debates(rows, nm, keep=120):
    """정기 판단마다 매수 측(bull) ⇄ 매도 측(bear) 토론과 총괄 결정. 최신 순, keep 회차까지. Agent Black Box 의 토론 기록용."""
    regs = {}
    for r in rows:
        if r["kind"] == "regime" and r.get("run"):
            regs[r["run"]] = r   # 같은 실행에 여러 번이면 마지막 국면
    by_run = {}
    for r in rows:
        if r.get("run") in regs and r["kind"] in ("decision", "fill", "block"):
            by_run.setdefault(r["run"], []).append(r)
    out_ = []
    for run, reg in sorted(regs.items(), key=lambda x: x[1]["time"], reverse=True)[:keep]:
        items = run_items(by_run.get(run, []), nm)
        if items:
            out_.append({"time": reg["time"], "regime": reg["regime"], "cap": reg["cap"], "reason": reg.get("reason", ""),
                         "mode": "view" if reg.get("mode") == "view" else "trade", "items": items})
    return out_


def equity_close():
    """오늘 종가 기준 한 줄을 equity.json 에 넣음 (같은 날짜면 덮어씀)."""
    acc = C.read_json(C.ACCOUNT)
    if not acc:
        return
    path = os.path.join(C.DOCS_DATA, "equity.json")
    rows = [r for r in (C.read_json(path, []) or []) if r["date"] != C.today().isoformat()]
    b = C.read_json(C.BRIEFING, {}) or {}
    m = b.get("market", {})
    reg = C.latest_regime() or {}
    rows.append({"date": C.today().isoformat(), "total": acc["total"],
                 "kospi": m.get("close") if m.get("source") == "KOSPI" and b.get("asof") == C.today().isoformat() else None,
                 "regime": reg.get("regime"), "cap": reg.get("cap")})
    out("equity", sorted(rows, key=lambda r: r["date"]))


def write_all(note=""):
    rows = C.read_jsonl(C.JOURNAL)
    nm = names()
    out("trades", trades(rows))
    out("risk", risks(rows, nm))
    out("holdings", holdings())
    out("system", system())
    out("reviews", reviews(rows))
    out("tuning", tuning(rows))
    out("decision", decision(rows, nm))
    out("debates", debates(rows, nm))
    out("briefing", briefing())
    out("status", status(note))


if __name__ == "__main__":
    if "--close" in sys.argv:
        equity_close()
    write_all()
    print("docs/data 갱신:", datetime.now(C.KST).strftime("%H:%M:%S"))
