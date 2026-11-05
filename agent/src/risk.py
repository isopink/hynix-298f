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
        if conf < C.probe_floor(p) - 1e-9 and not C.index_dip(code, order.get("today_change"), p):   # 소액 매수 구간까지 허용. 급락일 지수 예외는 확신도 기준 없음 (크기만 비례)
            bad.append(("확신도", f"{conf:.2f} < 매수 기준 {C.buy_threshold(p):.2f} (소액 매수 {C.probe_floor(p):.2f})"))
        chg, lim = order.get("today_change"), r.get("max_buy_day_change", 0.10)
        if chg is not None and chg >= lim:
            bad.append(("추격 매수", f"오늘 {chg:+.1%} ≥ +{lim:.0%}, 급등한 날은 매수 금지"))
        amount = qty * price
        xd = C.index_dip(code, order.get("today_change"), p) if side == "매수" else None   # 급락일 지수 예외: 종목·1회 주문 한도를 그 비중까지
        if amount > max(r["max_order_amount"], total * xd["weight"] * 1.001 if xd else 0):
            bad.append(("1회 주문 한도", f"{amount:,.0f}원 > {r['max_order_amount']:,}원"))
        pos_after = (held["qty"] if held else 0) * price + amount
        if pos_after > total * max(r["max_weight_per_stock"], xd["weight"] if xd else 0) * 1.001:
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
        etf, label = C.market_etf(code, p)
        if etf:   # 시장 ETF(인버스·지수): 정해진 국면에서만, 하루 정해진 횟수만
            if regime not in etf["regimes"] and not C.index_dip(code, order.get("today_change"), p):   # 급락일 지수 예외는 국면 무관
                bad.append((f"{label} 국면", f"오늘 국면 {regime} · {label}는 {'·'.join(etf['regimes'])} 국면에서만 매수"))
            if (n := C.buys_today(code)) >= etf.get("max_buys_per_day", 99):
                bad.append((f"{label} 하루 매수", f"오늘 이미 {n}번 매수 · {label}는 하루 {etf['max_buys_per_day']}번만"))
        if p["decision"].get("no_rebuy_same_day") and C.sold_today(code):
            bad.append(("당일 재매수", "오늘 판 종목은 그날 다시 사지 않음"))
        if held:   # 보유 종목 추가 매수 (11-05): 손실 중 물타기 금지, 소액 매수 구간으로는 추가 안 함
            if not (p["decision"].get("add_on") or {}).get("enabled"):
                bad.append(("추가 매수", "보유 종목 추가 매수가 꺼져 있음"))
            elif held.get("avg_price") and price < held["avg_price"]:
                bad.append(("추가 매수", f"현재가 {price:,.0f}원 < 평단 {held['avg_price']:,.0f}원, 손실 중 물타기 금지"))
            elif conf < C.buy_threshold(p) - 1e-9 and not xd:
                bad.append(("추가 매수", f"확신도 {conf:.2f} < 매수 기준 {C.buy_threshold(p):.2f}, 소액 매수 구간으로는 추가 매수 안 함"))
        inv = C.inverse(code, p)
        if inv:   # 인버스: 주식 상한 대신 인버스 한도
            inv_after = sum(h["value"] for h in account["holdings"] if C.inverse(h["code"], p) and h["code"] != code) + pos_after
            if inv_after > total * inv["weight_cap"] * 1.001:
                bad.append(("인버스 한도", f"매수 후 인버스 {inv_after / total:.1%} > {inv['weight_cap']:.0%}"))
        else:
            stock_after = C.stock_value(account["holdings"], p) + amount
            if stock_after > total * cap * 1.001:
                bad.append(("국면 비중 상한", f"매수 후 주식 {stock_after / total:.1%} > {regime} 상한 {cap:.0%}"))
        plan = sizing.plan_buy(code, conf, price, account, p, r, today_change=order.get("today_change"))
        if qty > plan["qty"] * 1.03 + 1:   # 계산 시점과 검사 시점의 가격 차이만큼 여유
            bad.append(("수량 계산 초과", f"{qty}주 > 계산값 {plan['qty']}주"))
    elif side == "매도":
        have = held["qty"] if held else 0
        if qty > have:
            bad.append(("보유 수량", f"매도 {qty}주 > 보유 {have}주 (공매도 불가)"))
        if run_mode != "exit" and conf < p["decision"]["sell_min_confidence"] and not order.get("rule_exit"):
            bad.append(("확신도", f"{conf:.2f} < 매도 기준 {p['decision']['sell_min_confidence']:.2f}"))
        if run_mode != "exit" and not order.get("rule_exit") and C.dip_held(code):   # 11-06 급락일 예외 매수분은 판단 매도 금지
            bad.append(("급락일 예외 보유", "급락일 예외로 산 지수 ETF 는 익절·손절·보유일 규칙 매도만"))
        cap_q, part = sizing.sell_qty(have, conf, p, order.get("rule_exit") or run_mode == "exit")
        if part and C.sold_today(code):
            bad.append(("분할 매도", f"오늘 이미 분할 매도한 종목 · 확신도 {conf:.2f} < 전량 기준 {p['decision']['partial_sell']['full_at']:.2f}이면 하루 1번만"))
        elif part and qty > cap_q:
            bad.append(("분할 매도", f"확신도 {conf:.2f} < 전량 기준 {p['decision']['partial_sell']['full_at']:.2f} → 최대 {cap_q}주 (요청 {qty}주)"))
    else:
        bad.append(("주문 방향", f"알 수 없는 side: {side}"))
    return bad
