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
        "decisions": dict(Counter(x["action"] for x in rows if x["kind"] == "decision" and x.get("mode") != "view")),   # 판단 갱신(주문 없음) 회차는 뺌
        "decision_confidence": watch_confidence(rows, p),
        "decision_confidence_note": "매매 회차에서 관망한 후보의 확신도. 코드 보정(하락장 · RSI)을 더한 값이라 매수 기준과 바로 비교할 수 있음",
        "buy_threshold_now": C.buy_threshold(p),
        "blocks_by_rule": dict(Counter(x["rule"] for x in rows if x["kind"] == "block")),
        "costs_note": "키움 모의서버 실제 비용은 매수·매도 수수료 각 0.35%, 매도 세금 0.2% (왕복 약 0.9%). 보유 중 return_after_costs 는 이를 반영한 값",
        "last_weekly_review": {"time": review["time"], "suggestion": review["suggestion"]} if review else None,
        "decision_outcomes": outcomes(rows),
        "lessons_now": (C.read_json(LESSONS, {}) or {}).get("lessons", []),
        "tuning_history": history(rows)[-12:],
        "cooldown_keys": cd,
        "max_changes_per_run": rl["max_changes_per_run"],
        "tunable": {k: {**v, "current": get_value(p, k), "cooldown": k in cd} for k, v in rl["keys"].items()},
    }


LESSONS = os.path.join(C.WORK, "lessons.json")   # 11-06 조정 실행이 남긴 '판단 점검 교훈' → 다음 판단 브리핑에 실림


def outcomes(rows):
    """11-06 S.Lee: 지난 판단이 맞았는지 결과로 채점. 판단한 날 종가(체결은 체결가) → 지금 가격.
    관망했는데 +2% 넘게 오름 = 놓침(조정) · 내림 = 관망 맞음(유지) / 보유했는데 −3% 넘게 내림 = 안 판 게 손해(조정)
    매수했는데 오름 = 맞음(유지) · 내림 = 틀림(조정) / 매도했는데 내림 = 맞음(유지) · +2% 넘게 오름 = 너무 일찍 팖(조정).
    오늘 판단은 결과를 볼 시간이 없어 다음 날부터 채점."""
    today = C.today().isoformat()
    q = C.read_json(os.path.join(C.WORK, "quotes.json"), {}) or {}
    prep = {x["code"]: x for x in (C.read_json(os.path.join(C.WORK, "prep_rows.json"), []) or [])}
    b = C.read_json(C.BRIEFING, {}) or {}
    asof = b.get("asof")
    acc = C.read_json(C.ACCOUNT, {}) or {}
    held = {h["code"]: h.get("price") for h in acc.get("holdings", [])}
    cand = {c["code"]: c for c in b.get("candidates", [])}

    def now_px(code):
        x = q.get(code)
        if x and x.get("price") and date.fromtimestamp(x.get("ts", 0)).isoformat() == today:
            return x["price"]
        if held.get(code):
            return held[code]
        if (c := cand.get(code)) and c.get("price"):
            return c["price"]
        r = prep.get(code)
        return (r.get("closes") or [None])[-1] if r else None

    def close_on(code, d):
        r, cl = prep.get(code), (prep.get(code) or {}).get("closes") or []
        if not r or not asof or d > asof:
            return None
        n = C.business_days(d, date.fromisoformat(asof))
        return cl[-1 - n] if 0 <= n < len(cl) else None

    last = {}
    for x in rows:   # 하루 마지막 판단만 (같은 날 15분마다 같은 판단이 반복되므로)
        if x["time"][:10] >= today:
            continue
        if x["kind"] == "decision" and x.get("mode") == "decide" and x.get("action") in ("관망", "보유"):
            last[(x["code"], x["time"][:10], x["action"])] = x
        elif x["kind"] == "fill":
            last[(x["code"], x["time"][:10], x["side"])] = x
    res = []
    for (code, d, act), x in last.items():
        p0 = x.get("price") if act in ("매수", "매도") else (x.get("price") or close_on(code, d))
        p1 = now_px(code)
        if not p0 or not p1:
            continue
        ret = p1 / p0 - 1
        if act == "관망":
            v = "놓침 (조정)" if ret >= .02 else "맞음 (유지)" if ret <= 0 else "중립"
        elif act == "보유":
            v = "안 판 게 손해 (조정)" if ret <= -.03 else "맞음 (유지)"
        elif act == "매수":
            v = "맞음 (유지)" if ret > 0 else "틀림 (조정)"
        else:
            v = "맞음 (유지)" if ret < 0 else "너무 일찍 팖 (조정)" if ret >= .02 else "중립"
        conf = x.get("confidence_adj", x.get("confidence"))
        res.append({"date": d, "code": code, "name": x.get("name"), "action": act, "confidence": conf, "ret_since": round(ret, 4), "verdict": v,
                    "bull": (x.get("bull") or "")[:140], "bear": (x.get("bear") or "")[:140]})
    summary = defaultdict(Counter)
    for r_ in res:
        summary[r_["action"]][r_["verdict"]] += 1
    wrong = sorted([r_ for r_ in res if "조정" in r_["verdict"]], key=lambda r_: -abs(r_["ret_since"]))
    right = sorted([r_ for r_ in res if "유지" in r_["verdict"]], key=lambda r_: -abs(r_["ret_since"]))
    return {"note": "판단한 날 종가(체결은 체결가) → 지금 가격. 오늘 판단은 내일부터 채점. 조정 = 판단을 바꿔야 할 사례, 유지 = 맞은 판단",
            "summary": {k: dict(v) for k, v in summary.items()},
            "adjust": wrong[:10], "keep": right[:6]}


def watch_confidence(rows, p):
    """매매 회차에서 관망한 후보의 보정 후 확신도 (높은 순). 11-04 전 기록은 보정 값이 없어 그 실행의 국면으로 하락장 보정만 더해 추정."""
    mb = p.get("market_boost") or {}
    reg = {x.get("run"): x.get("regime") for x in rows if x["kind"] == "regime"}
    out = []
    for x in rows:
        if x["kind"] != "decision" or x["action"] != "관망" or x.get("mode") == "view":
            continue
        c = x.get("confidence_adj")
        if c is None:
            c = float(x["confidence"]) + (mb.get("add", 0) if reg.get(x.get("run")) in mb.get("regimes", []) else 0)
        out.append(round(float(c), 3))
    return sorted(out, reverse=True)


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
    if d.get("max_weight", 1) < d["min_weight"] - 1e-9:
        errs.append("최대 종목 비중은 최소 종목 비중보다 작을 수 없음")
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
