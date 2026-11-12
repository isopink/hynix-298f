"""11-12 S.Lee: 토론 라우팅 — 직전 회차와 비교해 '달라진 종목'만 근거 수집 · 매수 측 ⇄ 매도 측 토론으로 보냄.

달라지지 않은 후보는 직전 판단(행동 · 확신도)을 그대로 이어 기록 (총괄이 주문 실행에게 넘김).
보유 종목은 늘 보유 관리 에이전트가 봄 (여기서는 '달라짐' 표시만).

전부 토론하는 회차: 그날 첫 매매 회차, params.routing.full_slots (09:30 · 15:00 · 15:15), 직전 기록이 없을 때.
한 회차 안에서 서브에이전트가 get_briefing 을 다시 불러도 결과가 같도록 RUN_ID 별로 한 번만 계산해 둠.
"""
import os

import common as C

STATE = os.path.join(C.WORK, "route.json")


def _cfg(p):
    d = {"enabled": True, "price_move": 0.015, "flow_flip_min": 5e8, "full_slots": ["09:30", "15:00", "15:15"]}
    d.update((p or C.params()).get("routing") or {})
    return d


def _snap(x):
    news = x.get("news") or []
    return {"price": x.get("price") or x.get("close"), "foreign": x.get("foreign_today"), "inst": x.get("inst_today"),
            "news": sorted(str(n.get("title", ""))[:40] for n in news if isinstance(n, dict))}


def _sign(v, floor):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0
    return 0 if abs(v) < floor else (1 if v > 0 else -1)


def _why(now, before, cfg):
    """달라진 이유 (없으면 None)."""
    if not before:
        return "새 후보"
    try:
        a, b = float(now["price"]), float(before["price"])
        if b and abs(a / b - 1) >= cfg["price_move"]:
            return f"가격 {a / b - 1:+.1%}"
    except (TypeError, ValueError, KeyError):
        return "가격 비교 불가"
    f = cfg["flow_flip_min"]
    for k, nm in (("foreign", "외국인"), ("inst", "기관")):
        s0, s1 = _sign(before.get(k), f), _sign(now.get(k), f)
        if s0 and s1 and s0 != s1:
            return f"{nm} 순매수 방향 바뀜"
    if set(now["news"]) - set(before["news"]):
        return "새 뉴스"
    return None


def last_decided(run, rows=None):
    """오늘 직전 판단 회차(이번 실행 제외)에서 판단 · 체결 기록이 있는 종목 코드."""
    rows = C.read_jsonl(C.JOURNAL) if rows is None else rows
    t = C.today().isoformat()
    runs = [x["run"] for x in rows if x.get("kind") == "regime" and x.get("time", "").startswith(t) and x.get("run") and x["run"] != run]
    if not runs:
        return set()
    last = runs[-1]
    return {x.get("code") for x in rows if x.get("run") == last and x.get("kind") in ("decision", "fill")}


def route(b, p=None, run=None, now=None):
    """{'full': bool, 'why_full': str, 'debate': [(code, name, why)], 'reuse': [(code, name)], 'holdings': [(code, name, why)]}"""
    p = p or C.params()
    cfg = _cfg(p)
    run = os.environ.get("RUN_ID", "") if run is None else run
    st = C.read_json(STATE, {}) or {}
    if run and st.get("run") == run and st.get("result"):
        return st["result"]
    now = now or C.now()
    today, hm = now.date().isoformat(), now.strftime("%H:%M")
    prev = st.get("snap") if st.get("date") == today else None
    slot = next((s for s in cfg["full_slots"] if s <= hm < s[:3] + f"{int(s[3:]) + 15:02d}"), None) if cfg["full_slots"] else None
    full = (not cfg["enabled"]) or not prev or bool(slot)
    why_full = ("라우팅 꺼짐" if not cfg["enabled"] else "오늘 첫 회차" if not prev else f"{slot} 회차는 전부 토론" if slot else "")
    cands, holds = b.get("candidates", []) or [], b.get("holdings", []) or []
    snap = {x["code"]: _snap(x) for x in cands + holds}
    debate, reuse, hl = [], [], []
    prev_dec = last_decided(run) if prev else None
    for x in cands:
        w = "전부 토론" if full else _why(snap[x["code"]], (prev or {}).get(x["code"]), cfg)
        if not w and prev_dec is not None and x["code"] not in prev_dec:
            w = "직전 판단 없음"
        (debate if w else reuse).append([x["code"], x.get("name", x["code"])] + ([w] if w else []))
    for x in holds:
        w = _why(snap[x["code"]], (prev or {}).get(x["code"]), cfg) if prev else "오늘 첫 회차"
        hl.append([x["code"], x.get("name", x["code"]), w or "변화 작음"])
    for c, _ in reuse:   # 이어 쓴 종목은 마지막으로 토론한 때의 값과 계속 비교 (조금씩 쌓인 변화도 잡음)
        if prev and c in prev:
            snap[c] = prev[c]
    res = {"full": full, "why_full": why_full, "debate": debate, "reuse": reuse, "holdings": hl}
    if run:
        C.write_json(STATE, {"run": run, "date": today, "snap": snap, "result": res})
    return res


def to_text(r):
    """get_briefing 끝에 붙는 라우팅 표."""
    out = ["", "", "## 토론 라우팅 (코드가 직전 회차와 비교해 정함, 11-12)"]
    if r["full"]:
        out.append(f"- 이번 회차는 **후보 전부 토론** ({r['why_full']})")
    out.append("- 근거 수집 · 매수 측 ⇄ 매도 측 토론 대상: " + (", ".join(f"{n}({c}) — {w}" for c, n, w in r["debate"]) or "없음"))
    out.append("- 직전 판단 이어 쓰기 (토론 없이 직전 행동 · 확신도 그대로 기록): " + (", ".join(f"{n}({c})" for c, n in r["reuse"]) or "없음"))
    out.append("- 보유 종목 (보유 관리 에이전트가 늘 봄): " + (", ".join(f"{n}({c}) — {w}" for c, n, w in r["holdings"]) or "없음"))
    return "\n".join(out)
