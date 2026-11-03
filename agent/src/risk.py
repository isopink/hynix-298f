"""
리스크 규칙. 주문 직전에 Hook(.claude/hooks/risk_check.py)과 MCP 서버가 둘 다 이 함수로 검사합니다.

규칙을 어기면 주문은 나가지 않고, 어떤 규칙에 걸렸는지 기록에 남습니다.
에이전트는 이 파일이나 config/risk_limits.json 을 고칠 수 없습니다 (도구 권한에서 막음).
"""
import os

import common as C
import sizing


def daily_pnl(account):
    start = (C.read_json(os.path.join(C.WORK, "day_start.json"), {}) or {})
    if start.get("date") != C.today().isoformat() or not start.get("total"):
        return 0.0
    return account["total"] / start["total"] - 1


def orders_this_run():
    run = os.environ.get("RUN_ID")
    if not run:
        return 0
    return sum(1 for x in C.read_jsonl(C.JOURNAL) if x["kind"] == "fill" and x.get("run") == run)


def check(order, account, price, p=None, r=None):
    """order: {code, side, qty, confidence}. 위반한 규칙 목록을 [(rule, detail)] 로 돌려줌. 빈 목록 = 통과."""
    p, r = p or C.params(), r or C.risk_limits()
    code, side = order["code"], order["side"]
    qty, conf = int(order.get("qty") or 0), float(order.get("confidence") or 0)
    conf, _ = C.conf_boost(code, side, conf, p)   # RSI 과매도·과열 + 시장 하락 보정 (plan_order 와 같은 계산)
    total = account["total"]
    held = next((h for h in account["holdings"] if h["code"] == code), None)
    bad = []

    if qty <= 0:
        bad.append(("수량", "주문 수량이 0 이하"))
    if price <= 0:
        bad.append(("가격", "현재가를 확인하지 못함"))
    if orders_this_run() >= r["max_orders_per_run"]:
        bad.append(("주문 횟수", f"한 번 실행에 최대 {r['max_orders_per_run']}건"))

    run_mode = os.environ.get("RUN_MODE", "decide")
    if run_mode == "view":
        bad.append(("실행 종류", "판단 갱신 회차(매매 없음)라 주문하지 않음"))
    if side == "매수":
        if run_mode == "exit":
            bad.append(("실행 종류", "손절·익절 실행에서는 매수 금지"))
        if conf < C.buy_threshold(p):
            bad.append(("확신도", f"{conf:.2f} < 매수 기준 {C.buy_threshold(p):.2f}"))
        chg, lim = order.get("today_change"), r.get("max_buy_day_change", 0.10)
        if chg is not None and chg >= lim:
            bad.append(("추격 매수", f"오늘 {chg:+.1%} ≥ +{lim:.0%}, 급등한 날은 매수 금지"))
        amount = qty * price
        if amount > r["max_order_amount"]:
            bad.append(("1회 주문 한도", f"{amount:,.0f}원 > {r['max_order_amount']:,}원"))
        pos_after = (held["qty"] if held else 0) * price + amount
        if pos_after > total * r["max_weight_per_stock"] * 1.001:
            bad.append(("종목 한도", f"매수 후 비중 {pos_after / total:.1%} > {r['max_weight_per_stock']:.0%}"))
        hv = C.high_vol(code, p)
        if hv and pos_after > total * hv["weight_cap"] * 1.001:
            bad.append(("고변동 종목 한도", f"매수 후 비중 {pos_after / total:.1%} > 고변동 종목 {hv['weight_cap']:.0%}"))
        if not held and len(account["holdings"]) >= r["max_positions"]:
            bad.append(("보유 종목 수", f"이미 {len(account['holdings'])}종목 (최대 {r['max_positions']})"))
        cash_after = account["cash"] - amount * (1 + p["costs"]["fee_rate"])
        if cash_after < total * r["min_cash_ratio"]:
            bad.append(("최소 현금", f"매수 후 현금 {cash_after / total:.1%} < {r['min_cash_ratio']:.0%}"))
        dp = daily_pnl(account)
        if dp <= r["daily_loss_limit"]:
            bad.append(("일일 손실 한도", f"오늘 {dp:.1%} ≤ {r['daily_loss_limit']:.0%}, 신규 매수 중단"))
        cap, regime = sizing.equity_cap(p, r, account)
        stock_after = sum(h["value"] for h in account["holdings"]) + amount
        if stock_after > total * cap * 1.001:
            bad.append(("국면 비중 상한", f"매수 후 주식 {stock_after / total:.1%} > {regime} 상한 {cap:.0%}"))
        plan = sizing.plan_buy(code, conf, price, account, p, r)
        if qty > plan["qty"] * 1.03 + 1:   # 계산 시점과 검사 시점의 가격 차이만큼 여유
            bad.append(("수량 계산 초과", f"{qty}주 > 계산값 {plan['qty']}주"))
    elif side == "매도":
        have = held["qty"] if held else 0
        if qty > have:
            bad.append(("보유 수량", f"매도 {qty}주 > 보유 {have}주 (공매도 불가)"))
        if run_mode != "exit" and conf < p["decision"]["sell_min_confidence"] and not order.get("rule_exit"):
            bad.append(("확신도", f"{conf:.2f} < 매도 기준 {p['decision']['sell_min_confidence']:.2f}"))
    else:
        bad.append(("주문 방향", f"알 수 없는 side: {side}"))
    return bad
