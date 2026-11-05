"""
키움 MCP 서버. 에이전트가 쓸 수 있는 도구는 이것뿐입니다 (파일 쓰기·셸 실행 없음).

  get_briefing    데이터 준비 결과 요약 + 오늘 기준값
  get_account     계좌·보유 종목 (손절·익절·보유일 포함)
  set_regime      시장 국면 기록 → 주식 비중 상한
  plan_order      확신도 → 수량 계산 (sizing.py)
  place_order     주문. 실행 직전에 Hook 이 리스크 검사, 서버도 한 번 더 검사
  record_decision 보유·관망 판단 기록
  submit_review   주간 회고 결과 (조정 제안 + 보고서 초안)
  get_tuning_context  기준값 조정용 성과 요약 + 조정 가능한 값·범위 (평일 조정 실행)
  apply_tuning    기준값 조정 제안 → 서버가 규칙(config/tuning.json)으로 검사해 통과분만 params.json 에 반영

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
    import tuning
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
    meta = C.position_meta(acc["holdings"])
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
        f"- 매수 확신도 기준 {C.buy_threshold(p):.2f} (보정 후 {C.probe_floor(p):.2f}~{C.buy_threshold(p):.2f} 는 종목당 {(p['decision'].get('probe') or {}).get('weight', 0):.1%} 소액 매수) · 매도 확신도 기준 {p['decision']['sell_min_confidence']:.2f} · "
        f"확신도 기준이면 종목당 {p['decision']['min_weight']:.0%}, {p['decision']['full_size_confidence']:.2f} 이상이면 {p['decision'].get('max_weight', r['max_weight_per_stock']):.0%} (여러 종목으로 나눠 삼)",
        f"- 국면별 주식 비중 상한: " + " · ".join(f"{k} {v:.0%}" for k, v in p["regime_cap"].items()),
        f"- 종목당 최대 {r['max_weight_per_stock']:.0%} · 최대 {r['max_positions']}종목 · 현금 {r['min_cash_ratio']:.0%} 이상 · "
        f"일일 손실 {r['daily_loss_limit']:.0%} 도달 시 신규 매수 중단",
        f"- 손절 {p['decision']['stop_loss_pct']:.0%} · 익절 {p['decision']['take_profit_pct']:.0%} · 최대 보유 {p['decision']['max_hold_days']}거래일",
        f"- 누적 체결 {C.fill_count()}건 (대회 최소 {p['competition']['min_trades']}건)",
    ]
    if (hv := p.get("high_vol")) and hv.get("enabled"):
        ctx.append(f"- ⚡고변동 종목 (20일 변동성 {p['screen']['max_vol20']:.0%} 초과): 후보에 최대 {hv['max_candidates']}개 따로 포함. "
                   f"종목당 {hv['weight_cap']:.0%} 이하만 (코드가 강제), 손절 {hv['stop_loss_pct']:.0%} · 익절 {hv['take_profit_pct']:+.0%}")
    if (dp := p.get("dip")) and dp.get("enabled"):
        ctx.append(f"- 📉급락 반등 후보: {dp['from']} 이후 회차(15:15)에만 거래대금 상위 {dp['top_value_rank']} 안에서 오늘 {dp['drop']:.0%} 이하로 빠진 종목을 "
                   f"최대 {dp['max_candidates']}개 따로 넣음 (추세·수급 조건 면제). 다음날 반등은 과거 3년 기준 반반이고 계속 빠지면 손실이 큼 → "
                   f"다른 종목과 같은 확신도 기준으로 판단하되, bull 은 급락 원인이 일시적인지(시장 동반 급락·과매도), bear 는 종목 고유 악재·추가 하락 근거를 볼 것. "
                   f"매수 기준을 넘으면 종목당 {dp['weight']:.0%} (코드가 강제), 손절·익절·보유일은 일반 종목과 같음")
    if (inv := p.get("inverse")) and inv.get("enabled"):
        names = ", ".join(f"{n}({c})" for c, n in inv["codes"].items())
        ctx.append(f"- 🔻인버스 {names}: 시장이 내리면 오르는 ETF. 후보에 매일 따로 들어옴. 오늘 국면이 {'·'.join(inv['regimes'])}일 때만 매수 가능, "
                   f"주식 비중 상한과 별도로 {inv['weight_cap']:.0%}까지, 하루 {inv.get('max_buys_per_day', '-')}번만 매수 (코드가 강제). "
                   f"짧게 치고 빠짐: 수수료·세금 뺀 순익 {inv['take_profit_net_pct']:+.1%}(평단 대비 {C.gross_take(inv['take_profit_net_pct'], p, inv.get('sell_tax_rate')):+.2%})에 익절 · 최대 보유 {inv.get('max_hold_days', p['decision']['max_hold_days'])}거래일. "
                   f"보유 중인데 국면이 바뀌면 매도 확신도를 높게 볼 것")
    if (ix := p.get("index")) and ix.get("enabled"):
        names = ", ".join(f"{n}({c})" for c, n in ix["codes"].items())
        ctx.append(f"- 📈지수 {names}: 시장을 그대로 따라가는 ETF (인버스와 짝). 후보에 매일 따로 들어옴. 오늘 국면이 {'·'.join(ix['regimes'])}일 때만 매수 가능, "
                   f"주식 비중 상한·종목 한도 안에서, 하루 {ix.get('max_buys_per_day', '-')}번만 매수 (코드가 강제). "
                   f"인버스와 같이 짧게 치고 빠짐: 순익 {ix['take_profit_net_pct']:+.1%}(평단 대비 {C.gross_take(ix['take_profit_net_pct'], p, ix.get('sell_tax_rate')):+.2%})에 익절 · 최대 보유 {ix.get('max_hold_days', p['decision']['max_hold_days'])}거래일. "
                   f"보유 중인데 국면이 하락으로 바뀌면 매도 확신도를 높게 볼 것")
    if rb := p.get("rsi_boost"):
        buy = [f"{x['name']}({n})" for x in b.get("candidates", []) + b.get("holdings", [])
               for _, n in [C.conf_boost(x["code"], "매수", 0, p, b, regime="")] if n]
        sell = [f"{x['name']}({n})" for x in b.get("holdings", [])
                for _, n in [C.conf_boost(x["code"], "매도", 0, p, b, regime="")] if n]
        live = any(x.get("rsi14_live") is not None for x in b.get("candidates", []) + b.get("holdings", []))
        ctx.append(f"- RSI 보정 (코드가 적용, 확신도는 보정 전 값으로 넘길 것): 매수 RSI {rb['buy_below']} 미만 · "
                   f"매도 RSI {rb['sell_at']} 이상이면 확신도 +{rb['add']:.2f}. "
                   + ("RSI 는 지금 가격을 오늘 종가로 본 장중 값" if live else "RSI 는 전일 종가 기준"))
        ctx.append("  - 매수 보정 대상: " + (", ".join(buy) if buy else "없음"))
        ctx.append("  - 매도 보정 대상(보유): " + (", ".join(sell) if sell else "없음"))
    if mb := p.get("market_boost"):
        ctx.append(f"- 시장 하락 보정 (코드가 적용): set_regime 으로 기록한 국면이 {'·'.join(mb['regimes'])} 이면 "
                   f"신규 매수 확신도 +{mb['add']:.2f} (악재 뉴스 ⚠ 제외). 국면을 이유로 스스로 확신도를 올리거나 내리지 않음")
    b["market"]["live"] = data_prep.live_market(b)   # 장중이면 지금 KOSPI 반영 힌트도 같이
    return data_prep.to_text(b) + "\n".join(ctx) + intraday(b, r) + C.prior_judgments()


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
        adj, note = C.conf_boost(code, side, confidence)
        plan = sizing.plan_buy(code, adj, price, acc)
        plan.update(confidence_raw=confidence, boost=note)
    elif side == "매도":
        adj, note = C.conf_boost(code, side, confidence)
        plan = sizing.plan_sell(code, adj, price, acc)
        plan.update(confidence_raw=confidence, boost=note)
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
    adj, note = C.conf_boost(code, side, confidence)   # 기록은 보정 후 확신도 (사이징·리스크 검사와 같은 값)
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
        sl, tp, md = C.exit_levels(code)   # 고변동 종목은 손절·익절 폭이 넓음
        m.update(stop=round(res["price"] * (1 + sl)), take=round(res["price"] * (1 + tp)), max_days=md)
        meta[code] = m
    elif not held:
        meta.pop(code, None)
    C.write_json(C.POSITIONS, meta)
    C.journal("fill", code=code, name=name, side=side, qty=res["qty"], price=res["price"],
              amount=res["qty"] * res["price"], confidence=adj, confidence_raw=confidence, boost=note, regime=regime,
              bull=bull, bear=bear, decision=decision, order_no=res.get("order_no"),
              filled=res.get("filled", True), rule_exit=rule_exit)
    return {"ok": True, **res, "name": name}


@mcp.tool()
@quiet
def record_decision(code: str, action: str, confidence: float, bull: str, bear: str, decision: str) -> dict:
    """주문하지 않은 판단을 기록합니다. action 은 '보유' | '관망'. 판단 갱신(매매 없는 회차)에서는 '매수 예정' | '매도 예정' 도 씀."""
    side = "매도" if action in ("보유", "매도 예정") else "매수"
    adj, note = C.conf_boost(code, side, confidence)   # 매수였다면 / 매도였다면 코드가 붙였을 보정
    C.journal("decision", code=code, name=name_of(code), action=action, confidence=confidence,
              confidence_adj=adj, boost=note, bull=bull, bear=bear, decision=decision)
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


@mcp.tool()
@quiet
def get_tuning_context() -> dict:
    """기준값 조정용 자료: 대회 진행·계좌 수익률·종목별 매매 결과(확신도 대비)·관망/차단 통계·최근 주간 회고 제안·
    지난 조정 이력, 그리고 조정 가능한 값(tunable: 현재값·허용 범위 min~max·1회 최대 변경폭 step·쿨다운 여부)."""
    return tuning.context()


@mcp.tool()
@quiet
def apply_tuning(changes: list[dict], summary: str) -> dict:
    """기준값 조정 제출 (조정 실행에서 한 번만). changes = [{"key": "decision.buy_min_confidence", "to": 0.55, "reason": "숫자 근거 1~2문장"}],
    바꿀 게 없으면 changes=[] 로 '유지' 를 제출. summary = 이번 판단 요약 1~2문장 (대시보드에 공개).
    서버가 허용 키·범위·변경폭·개수·쿨다운·기준값 일관성을 검사해 통과한 것만 반영하고, 거절 사유를 돌려줍니다."""
    return tuning.apply(changes, summary)


if __name__ == "__main__":
    mcp.run()
