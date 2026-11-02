"""
키움 MCP 서버. 에이전트가 쓸 수 있는 도구는 이것뿐입니다 (파일 쓰기·셸 실행 없음).

  get_briefing    데이터 준비 결과 요약 + 오늘 기준값
  get_account     계좌·보유 종목 (손절·익절·보유일 포함)
  set_regime      시장 국면 기록 → 주식 비중 상한
  plan_order      확신도 → 수량 계산 (sizing.py)
  place_order     주문. 실행 직전에 Hook 이 리스크 검사, 서버도 한 번 더 검사
  record_decision 보유·관망 판단 기록
  submit_review   주간 회고 결과 (조정 제안 + 보고서 초안)

stdout 은 MCP 통신용이라, pykrx 등이 찍는 메시지는 전부 stderr 로 돌립니다.
"""
import contextlib
import functools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

with contextlib.redirect_stdout(sys.stderr):
    import common as C
    C.load_env()
    import broker as B
    import data_prep
    import risk
    import sizing
    from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kiwoom")
_broker = None


def brk():
    global _broker
    if _broker is None:
        with contextlib.redirect_stdout(sys.stderr):
            _broker = B.get()
    return _broker


def quiet(fn):
    @functools.wraps(fn)
    def wrap(*a, **k):
        with contextlib.redirect_stdout(sys.stderr):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001  에이전트가 읽을 수 있게 오류를 결과로 돌려줌
                return {"error": f"{type(e).__name__}: {e}"}
    return wrap


def name_of(code):
    b = C.read_json(C.BRIEFING, {}) or {}
    acc = C.read_json(C.ACCOUNT, {}) or {}
    for r in b.get("candidates", []) + b.get("holdings", []) + acc.get("holdings", []):
        if r["code"] == code:
            return r["name"]
    return code


def positions_view(acc):
    meta = C.read_json(C.POSITIONS, {}) or {}
    out = []
    for h in acc["holdings"]:
        m = meta.get(h["code"], {})
        out.append({**h, "weight": round(h["value"] / acc["total"], 4) if acc["total"] else 0,
                    "stop": m.get("stop"), "take": m.get("take"),
                    "held_days": C.business_days(m["entry_date"], C.today()) if m.get("entry_date") else None,
                    "max_days": m.get("max_days")})
    return out


@mcp.tool()
@quiet
def get_briefing() -> str:
    """오늘 브리핑: 시장 지표, 후보 종목, 보유 종목 지표(숫자 요약)와 오늘 적용되는 기준값. 판단은 반드시 이 숫자에 근거할 것."""
    b = C.read_json(C.BRIEFING)
    if not b:
        return "브리핑이 없습니다. 데이터 준비가 실행되지 않았습니다. 오늘은 관망하세요."
    p, r = C.params(), C.risk_limits()
    ctx = [
        "", "## 오늘 기준값 (코드가 강제함)",
        f"- 실행 종류: {os.environ.get('RUN_MODE', 'decide')} · 대회 {C.competition_week(p=p)}주차 · 주차 비중 계수 ×{C.week_factor(p)}",
        f"- 매수 확신도 기준 {C.buy_threshold(p):.2f} · 매도 확신도 기준 {p['decision']['sell_min_confidence']:.2f} · "
        f"확신도 {p['decision']['full_size_confidence']:.2f} 이상이면 종목 한도까지",
        f"- 국면별 주식 비중 상한: " + " · ".join(f"{k} {v:.0%}" for k, v in p["regime_cap"].items()),
        f"- 종목당 최대 {r['max_weight_per_stock']:.0%} · 최대 {r['max_positions']}종목 · 현금 {r['min_cash_ratio']:.0%} 이상 · "
        f"일일 손실 {r['daily_loss_limit']:.0%} 도달 시 신규 매수 중단",
        f"- 손절 {p['decision']['stop_loss_pct']:.0%} · 익절 {p['decision']['take_profit_pct']:.0%} · 최대 보유 {p['decision']['max_hold_days']}거래일",
        f"- 누적 체결 {C.fill_count()}건 (대회 최소 {p['competition']['min_trades']}건)",
    ]
    b["market"]["live"] = data_prep.live_market(b)   # 장중이면 지금 KOSPI 반영 힌트도 같이
    return data_prep.to_text(b) + "\n".join(ctx) + intraday(b, r)


def intraday(b, r):
    """후보·보유 종목의 지금 가격과 오늘 등락률. 지표는 전일 종가 기준이라 오늘 급등·급락을 여기서 봄."""
    rows, seen = [], set()
    for x in b.get("candidates", []) + (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", []):
        if x["code"] in seen:
            continue
        seen.add(x["code"])
        try:
            q = brk().quote_info(x["code"])
        except Exception:  # noqa: BLE001  조회 실패는 표에서만 빠짐
            continue
        chg = q["change"]
        rows.append(f"| {x['code']} | {x['name']} | {q['price']:,} | {'—' if chg is None else f'{chg:+.1%}'} |")
    if not rows:
        return ""
    lim = r.get("max_buy_day_change", 0.10)
    return "\n".join(["", "", f"## 오늘 장중 ({C.now().strftime('%H:%M')} 현재가, 전일 종가 대비)",
                      f"위 지표는 전일 종가 기준입니다. 오늘 +{lim:.0%} 이상 오른 종목은 리스크 규칙상 매수할 수 없습니다 (추격 매수 금지).",
                      "", "| 코드 | 종목 | 현재가 | 오늘 등락 |", "|---|---|---|---|", *rows])


@mcp.tool()
@quiet
def get_account() -> dict:
    """계좌 총자산·현금·보유 종목(평단, 현재가, 수익률, 비중, 손절가, 익절가, 보유일)과 오늘 손익, 지금 주식 비중 상한."""
    acc = brk().account()
    cap, regime = sizing.equity_cap(C.params(), C.risk_limits(), acc)
    return {"mode": brk().name, "total": acc["total"], "cash": acc["cash"], "stock_value": acc["stock_value"],
            "daily_pnl": round(risk.daily_pnl(acc), 4), "regime": regime, "equity_cap": cap,
            "holdings": positions_view(acc)}


@mcp.tool()
@quiet
def set_regime(regime: str, reason: str) -> dict:
    """시장 국면을 기록합니다. regime 은 '상승' | '횡보' | '하락'. 이후 매수 수량은 이 국면의 비중 상한을 따릅니다."""
    p = C.params()
    if regime not in p["regime_cap"]:
        return {"error": "regime 은 상승 / 횡보 / 하락 중 하나"}
    cap = round(p["regime_cap"][regime] * C.week_factor(p), 4)
    C.journal("regime", regime=regime, cap=cap, reason=reason)
    return {"regime": regime, "equity_cap": cap}


@mcp.tool()
@quiet
def plan_order(code: str, side: str, confidence: float) -> dict:
    """확신도로 주문 수량을 계산합니다 (주문은 하지 않음). side 는 '매수' | '매도'.
    qty 가 0 이면 limited_by 에 이유가 있습니다. place_order 에는 여기서 나온 qty 이하만 쓸 수 있습니다."""
    acc = brk().account()
    qi = brk().quote_info(code)
    price = qi["price"]
    if side == "매수":
        plan = sizing.plan_buy(code, confidence, price, acc)
    elif side == "매도":
        plan = sizing.plan_sell(code, confidence, price, acc)
    else:
        return {"error": "side 는 매수 / 매도"}
    plan["name"] = name_of(code)
    plan["today_change"] = qi["change"]   # 오늘 등락률. +10% 이상이면 매수는 리스크 규칙에 막힘
    return plan


@mcp.tool()
@quiet
def place_order(code: str, side: str, qty: int, confidence: float, bull: str, bear: str, decision: str,
                rule_exit: bool = False) -> dict:
    """시장가 주문. bull = 매수 측 핵심 근거, bear = 매도 측 핵심 근거, decision = 총괄 판단 이유 (각 1~2문장, 대시보드에 공개).
    rule_exit = 손절·익절·최대 보유일 규칙에 따른 매도이면 true. 리스크 규칙 위반이면 주문되지 않습니다."""
    acc = C.read_json(C.ACCOUNT) or brk().account()
    qi = brk().quote_info(code)
    price = qi["price"]
    order = {"code": code, "side": side, "qty": qty, "confidence": confidence, "rule_exit": rule_exit,
             "today_change": qi["change"]}
    bad = risk.check(order, acc, price)
    name = name_of(code)
    if bad:
        for rule, detail in bad:
            C.journal("block", code=code, name=name, side=side, rule=rule, detail=detail, by="server")
        return {"ok": False, "blocked": [f"{a}: {b}" for a, b in bad]}

    res = brk().order(code, name, side, qty)
    if not res.get("ok"):
        return res
    regime = (C.latest_regime() or {}).get("regime")
    meta = C.read_json(C.POSITIONS, {}) or {}
    held = next((h for h in (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", []) if h["code"] == code), None)   # order() 가 방금 갱신한 잔고 (키움 재조회 안 함)
    if side == "매수":
        d = C.params()["decision"]
        m = meta.get(code) or {"name": name, "entry_date": C.today().isoformat()}
        m.update(stop=round(res["price"] * (1 + d["stop_loss_pct"])), take=round(res["price"] * (1 + d["take_profit_pct"])),
                 max_days=d["max_hold_days"])
        meta[code] = m
    elif not held:
        meta.pop(code, None)
    C.write_json(C.POSITIONS, meta)
    C.journal("fill", code=code, name=name, side=side, qty=res["qty"], price=res["price"],
              amount=res["qty"] * res["price"], confidence=confidence, regime=regime,
              bull=bull, bear=bear, decision=decision, order_no=res.get("order_no"),
              filled=res.get("filled", True), rule_exit=rule_exit)
    return {"ok": True, **res, "name": name}


@mcp.tool()
@quiet
def record_decision(code: str, action: str, confidence: float, bull: str, bear: str, decision: str) -> dict:
    """주문하지 않은 판단(보유 / 관망)을 기록합니다. action 은 '보유' | '관망'."""
    C.journal("decision", code=code, name=name_of(code), action=action, confidence=confidence,
              bull=bull, bear=bear, decision=decision)
    return {"ok": True}


@mcp.tool()
@quiet
def submit_review(week: int, period: str, suggestion: str, report_markdown: str) -> dict:
    """주간 회고 결과. suggestion = 기준값 조정 제안 한 줄 (리스크 한도는 제안 불가), report_markdown = 주간 보고서 초안."""
    path = os.path.join(C.ROOT, "reports", "drafts", f"week{week}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_markdown)
    C.journal("review", week=week, period=period, suggestion=suggestion, draft=os.path.relpath(path, C.ROOT))
    return {"ok": True, "draft": path}


if __name__ == "__main__":
    mcp.run()
