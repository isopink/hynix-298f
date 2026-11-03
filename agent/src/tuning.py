"""
기준값 자동 조정 (피드백 루프).

평일 장 마감 뒤 조정 실행(run.py tune)에서 에이전트가
  1) get_tuning_context 로 성과 요약을 보고
  2) apply_tuning 으로 바꿀 값을 제안하면
서버가 config/tuning.json 규칙(허용 키·범위·1회 변경 폭·횟수·쿨다운·일관성)으로 검사해
통과한 것만 config/params.json 에 씁니다. risk_limits.json 은 건드릴 수 없습니다.
"""
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date

import common as C

RULES_PATH = os.path.join(C.CONFIG, "tuning.json")
PARAMS_PATH = os.path.join(C.CONFIG, "params.json")
DAY_NAMES = "월화수목금토일"


def rules():
    return C.read_json(RULES_PATH)


def get_value(p, key):
    sec, leaf = key.split(".", 1)
    return p[sec][leaf]


def history(rows=None):
    rows = C.read_jsonl(C.JOURNAL) if rows is None else rows
    return [r for r in rows if r["kind"] == "tune"]


def cooldown_keys(rows=None, rl=None):
    """최근 n번의 조정 실행에서 바꾼 키는 이번엔 못 바꿈 (값이 왔다 갔다 하지 않도록)."""
    rl = rl or rules()
    n = rl.get("cooldown_runs", 1)
    recent = history(rows)[-n:] if n else []
    return sorted({a["key"] for r in recent for a in r.get("applied", [])})


def allowed_today(rl=None):
    rl = rl or rules()
    return C.today().weekday() in rl["weekdays"]


# ---------------- 성과 요약 ----------------
def trade_results(rows, acc):
    """종목별 매수→매도 결과. 청산 = 가격 기준 실현 수익률, 보유 중 = 키움 수익률(수수료·세금 반영)."""
    held = {h["code"]: h for h in (acc or {}).get("holdings", [])}
    book = defaultdict(lambda: {"qty": 0, "cost": 0.0})
    out = []
    for r in rows:
        if r["kind"] != "fill":
            continue
        b = book[r["code"]]
        if r["side"] == "매수":
            if b["qty"] == 0:
                b.update(entry=r["time"], conf=r.get("confidence"), regime=r.get("regime"), name=r["name"])
            b["qty"] += r["qty"]
            b["cost"] += r["qty"] * r["price"]
        elif b["qty"] > 0:
            avg = b["cost"] / b["qty"]
            out.append({"code": r["code"], "name": b.get("name", r["name"]), "entry": b.get("entry"), "exit": r["time"],
                        "buy_confidence": b.get("conf"), "regime": b.get("regime"), "status": "청산",
                        "exit_reason": "규칙(손절·익절·보유일)" if r.get("rule_exit") else "판단 매도",
                        "return_price": round(r["price"] / avg - 1, 4)})
            b["qty"] = max(0, b["qty"] - r["qty"])
            b["cost"] = avg * b["qty"]
    for code, b in book.items():
        if b["qty"] > 0:
            h = held.get(code, {})
            out.append({"code": code, "name": b.get("name"), "entry": b.get("entry"), "buy_confidence": b.get("conf"),
                        "regime": b.get("regime"), "status": "보유 중",
                        "return_price": round(h["price"] / h["avg_price"] - 1, 4) if h.get("avg_price") else None,
                        "return_after_costs": h.get("pnl_pct")})
    return out


def context():
    rl, p, r = rules(), C.params(), C.risk_limits()
    rows = C.read_jsonl(C.JOURNAL)
    start = p["competition"]["start"]
    rows = [x for x in rows if x["time"][:10] >= start]
    acc = C.read_json(C.ACCOUNT, {}) or {}
    equity = C.read_json(os.path.join(C.DOCS_DATA, "equity.json"), []) or []
    fills = [x for x in rows if x["kind"] == "fill"]
    days_left = C.business_days(C.today().isoformat(), date.fromisoformat(p["competition"]["end"]))
    regimes = {}
    for x in rows:
        if x["kind"] == "regime":
            regimes[x["time"][:10]] = {"regime": x["regime"], "cap": x["cap"]}
    review = next((x for x in reversed(rows) if x["kind"] == "review"), None)
    cd = cooldown_keys(rows, rl)
    return {
        "today": f"{C.today().isoformat()} ({DAY_NAMES[C.today().weekday()]})",
        "apply_allowed_today": allowed_today(rl),
        "competition": {"week": C.competition_week(p=p), "business_days_left": days_left,
                        "fills": len(fills), "min_trades": p["competition"]["min_trades"]},
        "account": {"total": acc.get("total"), "return": round(acc["total"] / r["initial_capital"] - 1, 4) if acc.get("total") else None,
                    "cash": acc.get("cash"), "asof": acc.get("ts")},
        "equity_by_day": [{"date": e["date"], "total": e["total"], "regime": e.get("regime"), "cap": e.get("cap")} for e in equity],
        "regime_by_day": regimes,
        "trades": trade_results(rows, acc),
        "decisions": dict(Counter(x["action"] for x in rows if x["kind"] == "decision")),
        "decision_confidence": [x["confidence"] for x in rows if x["kind"] == "decision" and x["action"] == "관망"],
        "blocks_by_rule": dict(Counter(x["rule"] for x in rows if x["kind"] == "block")),
        "costs_note": "키움 모의서버 실제 비용은 매수·매도 수수료 각 0.35%, 매도 세금 0.2% (왕복 약 0.9%). 보유 중 return_after_costs 는 이를 반영한 값",
        "last_weekly_review": {"time": review["time"], "suggestion": review["suggestion"]} if review else None,
        "tuning_history": history(rows)[-5:],
        "cooldown_keys": cd,
        "max_changes_per_run": rl["max_changes_per_run"],
        "tunable": {k: {**v, "current": get_value(p, k), "cooldown": k in cd} for k, v in rl["keys"].items()},
    }


# ---------------- 검사 · 반영 ----------------
def _num(v, spec):
    v = float(v)
    return int(round(v)) if spec.get("int") else round(v, 4)


def check(changes, p, rl, cd):
    """(통과 목록, 거절 목록). 통과 = {key, label, from, to, reason}."""
    ok, bad, seen = [], [], set()
    for c in changes or []:
        key, reason = str(c.get("key", "")), str(c.get("reason", "")).strip()
        spec = rl["keys"].get(key)
        why = None
        if not spec:
            why = "조정할 수 없는 키 (리스크 한도·비용·일정 등은 고정)"
        elif key in seen:
            why = "같은 키를 두 번 제안"
        elif key in cd:
            why = "직전 조정에서 바꾼 값이라 이번엔 쉼 (쿨다운)"
        elif not reason:
            why = "이유가 없음"
        else:
            try:
                to = _num(c.get("to"), spec)
            except (TypeError, ValueError):
                to, why = None, "to 가 숫자가 아님"
            if why is None:
                cur = get_value(p, key)
                if to == cur:
                    why = "지금 값과 같음"
                elif not spec["min"] - 1e-9 <= to <= spec["max"] + 1e-9:
                    why = f"허용 범위 {spec['min']}~{spec['max']} 밖"
                elif abs(to - cur) > spec["step"] + 1e-9:
                    why = f"한 번에 {spec['step']} 넘게 바꿀 수 없음 (지금 {cur})"
        if why:
            bad.append({"key": key, "to": c.get("to"), "reason": reason, "rejected": why})
            continue
        seen.add(key)
        ok.append({"key": key, "label": spec["label"], "from": get_value(p, key), "to": to, "reason": reason})
    if len(ok) > rl["max_changes_per_run"]:
        for x in ok[rl["max_changes_per_run"]:]:
            bad.append({"key": x["key"], "to": x["to"], "reason": x["reason"], "rejected": f"한 번에 {rl['max_changes_per_run']}개까지"})
        ok = ok[:rl["max_changes_per_run"]]
    return ok, bad


def consistency(p):
    """바꾼 뒤에도 기준값끼리 말이 되는지."""
    d, rc = p["decision"], p["regime_cap"]
    errs = []
    if d["full_size_confidence"] - d["buy_min_confidence"] < 0.10 - 1e-9:
        errs.append("최대 비중 확신도는 매수 기준보다 0.10 이상 높아야 함")
    if not rc["상승"] >= rc["횡보"] >= rc["하락"]:
        errs.append("국면 상한은 상승 ≥ 횡보 ≥ 하락 순서여야 함")
    if d["take_profit_pct"] < -d["stop_loss_pct"]:
        errs.append("익절 폭이 손절 폭보다 작으면 안 됨")
    return errs


def _fmt(v):
    return str(v) if isinstance(v, int) else repr(round(v, 4))


def write_params(ok):
    """params.json 의 해당 숫자만 바꿔 씀 (주석·줄 배치를 지켜 diff 가 작게). 안 되면 통째로 다시 씀."""
    with open(PARAMS_PATH, encoding="utf-8") as f:
        text = f.read()
    new = text
    for x in ok:
        leaf = x["key"].split(".", 1)[1]
        pat = re.compile(r'("' + re.escape(leaf) + r'"\s*:\s*)-?\d+(?:\.\d+)?')
        if len(pat.findall(new)) != 1:
            new = None
            break
        new = pat.sub(lambda m: m.group(1) + _fmt(x["to"]), new)
    want = C.params()
    for x in ok:
        sec, leaf = x["key"].split(".", 1)
        want[sec][leaf] = x["to"]
    if new is None or json.loads(new) != want:
        new = json.dumps(want, ensure_ascii=False, indent=2) + "\n"
    tmp = PARAMS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, PARAMS_PATH)


def apply(changes, summary):
    rl, p = rules(), C.params()
    run = os.environ.get("RUN_ID", "")
    if os.environ.get("RUN_MODE") != "tune":
        return {"ok": False, "error": "기준값 조정은 조정 실행(tune)에서만 할 수 있습니다."}
    if not allowed_today(rl):
        return {"ok": False, "error": "기준값 조정은 평일에만 반영합니다."}
    if run and any(r.get("run") == run for r in history()):
        return {"ok": False, "error": "이번 실행에서 이미 제출했습니다."}
    ok, bad = check(changes, p, rl, cooldown_keys(rl=rl))
    if ok:
        trial = json.loads(json.dumps(p))
        for x in ok:
            sec, leaf = x["key"].split(".", 1)
            trial[sec][leaf] = x["to"]
        errs = consistency(trial)
        if errs:
            bad += [{"key": x["key"], "to": x["to"], "reason": x["reason"], "rejected": " / ".join(errs)} for x in ok]
            ok = []
    if ok:
        write_params(ok)
    C.journal("tune", summary=str(summary).strip()[:300], applied=ok, rejected=bad)
    return {"ok": True, "applied": ok, "rejected": bad,
            "note": "반영된 값은 다음 정기 판단부터 적용됩니다." if ok else "바뀐 값이 없습니다 (유지)."}
