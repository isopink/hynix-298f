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
    return [{"id": i + 1, "time": r["time"], "code": r["code"], "name": r["name"], "side": r["side"],
             "qty": r["qty"], "price": r["price"], "amount": r["amount"], "confidence": r["confidence"],
             "regime": r.get("regime"), "bull": r["bull"], "bear": r["bear"], "decision": r["decision"]}
            for i, r in enumerate(x for x in rows if x["kind"] == "fill")]


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
    meta = C.read_json(C.POSITIONS, {}) or {}
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
    res = {}
    for r in rows:
        if r["kind"] == "review":
            res[r["week"]] = {"week": r["week"], "period": r["period"], "suggestion": r["suggestion"],
                              "status": r.get("status", "검토 중")}
    old = {x["week"]: x for x in (C.read_json(os.path.join(C.DOCS_DATA, "reviews.json"), []) or [])}
    for w, x in res.items():   # 사람이 "반영"으로 바꿔 둔 상태는 유지
        if w in old and old[w].get("status") == "반영":
            x["status"] = "반영"
    return [res[w] for w in sorted(res)]


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
            "failures_today": sum(1 for r in todays if not r.get("ok")), "note": note or (last or {}).get("note", "")}


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
    out("status", status(note))


if __name__ == "__main__":
    if "--close" in sys.argv:
        equity_close()
    write_all()
    print("docs/data 갱신:", datetime.now(C.KST).strftime("%H:%M:%S"))
