"""
수량 계산: 확신도 → 목표 비중 → 주문 수량, 손절·익절·최대 보유일.

에이전트는 "이 종목을 확신도 0.72로 산다"까지만 정하고, 몇 주를 살지는 여기서 정합니다.
"""
import math

import common as C


def target_weight(conf, p, r, top=None):
    """확신도 → 종목 목표 비중. 기준 미만이면 0, 기준이면 min_weight, full_size 이상이면 max_weight.
    max_weight(11-04 10%)는 리스크 한도 종목당 비중(20%)보다 작게 잡아 여러 종목으로 나눠 삼.
    top 을 주면 그 값이 최대 (인버스는 inverse.weight_cap 20%까지 한 번에 살 수 있게 예외)."""
    d = p["decision"]
    lo, hi = C.buy_threshold(p), d["full_size_confidence"]
    top = min(top if top is not None else d.get("max_weight", r["max_weight_per_stock"]), r["max_weight_per_stock"])
    if conf < lo:   # 매수 기준 바로 아래(소액 매수 구간)면 작게만, 그보다 낮으면 0
        pr = d.get("probe") or {}
        return min(pr["weight"], top) if pr.get("enabled") and conf >= C.probe_floor(p) - 1e-9 else 0.0
    if conf >= hi:
        return top
    return d["min_weight"] + (conf - lo) / (hi - lo) * (top - d["min_weight"])


def equity_cap(p, r, account, regime=None):
    """지금 주식에 쓸 수 있는 총 비중 = 국면 상한 × 주차 계수 (누적 손실 한도를 넘었으면 더 줄임)."""
    regime = regime or (C.latest_regime() or {}).get("regime") or "횡보"
    cap = p["regime_cap"][regime] * C.week_factor(p)
    if account["total"] / r["initial_capital"] - 1 <= r["total_loss_limit"]:
        cap *= r["total_loss_cap_factor"]
    return round(cap, 4), regime


def plan_buy(code, conf, price, account, p=None, r=None, regime=None, today_change=None):
    p, r = p or C.params(), r or C.risk_limits()
    total, cash = account["total"], account["cash"]
    held = next((h for h in account["holdings"] if h["code"] == code), None)
    held_value = held["qty"] * price if held else 0
    stock_value = C.stock_value(account["holdings"], p)
    cap, regime = equity_cap(p, r, account, regime)
    inv = C.inverse(code, p)

    ix = C.index_etf(code, p)
    top = inv["weight_cap"] if inv else ix.get("weight_cap") if ix else None   # 인버스·지수(11-05)는 종목당 10% 대신 자기 한도 20%까지
    w = target_weight(conf, p, r, top=top)
    dp = C.dip(code, p)
    xd = C.index_dip(code, today_change, p)   # 급락일 지수 예외: 국면과 상관없이, 하락 폭별 크기 (종목당 20% 예외)
    if xd and conf >= C.buy_threshold(p) - 1e-9:
        w = xd["weight"]
    if dp and conf >= C.buy_threshold(p) - 1e-9:   # 📉급락 반등 후보: 매수 기준을 넘으면 정해진 크기(7%)로 (소액 매수 구간은 그대로 작게)
        w = min(dp["weight"], r["max_weight_per_stock"])
    limits = {
        "확신도 비중": total * w * C.week_factor(p) - held_value,
        "국면 상한 여유": total * cap - stock_value,
        "최소 현금 유지": cash - total * r["min_cash_ratio"],
        "1회 주문 한도": max(r["max_order_amount"], total * xd["weight"]) if xd else r["max_order_amount"],   # 급락일 지수 예외는 한 번에 비중만큼
        "종목 한도": total * max(r["max_weight_per_stock"], xd["weight"] if xd else 0) - held_value,
    }
    if inv:   # 인버스는 주식 상한 대신 자기 한도. 정해진 국면이 아니면 0
        del limits["국면 상한 여유"]
        inv_held = sum(h["qty"] * price if h["code"] == code else h["value"]
                       for h in account["holdings"] if C.inverse(h["code"], p))
        limits["인버스 한도"] = total * inv["weight_cap"] - inv_held
    etf, label = C.market_etf(code, p)
    if etf:   # 시장 ETF(인버스·지수): 정해진 국면에서만, 하루 정해진 횟수만
        if regime not in etf["regimes"] and not xd:
            limits[f"{label}는 " + "·".join(etf["regimes"]) + " 국면만"] = 0
        if C.buys_today(code) >= etf.get("max_buys_per_day", 99):
            limits[f"{label}는 하루 {etf['max_buys_per_day']}번만"] = 0
    if p["decision"].get("no_rebuy_same_day") and C.sold_today(code):   # 15분마다 매매하면서 팔고 바로 다시 사는 왕복(수수료 0.9%) 방지
        limits["오늘 판 종목은 재매수 안 함"] = 0
    hv = C.high_vol(code, p)
    if hv:   # 변동성이 큰 종목은 작게만
        limits["고변동 종목 한도"] = total * hv["weight_cap"] - held_value
    binding = min(limits, key=limits.get)
    budget = max(0.0, limits[binding])
    unit = price * (1 + p["costs"]["fee_rate"])
    qty = math.floor(budget / unit) if price > 0 else 0
    stop_pct, take_pct, max_days = C.exit_levels(code, p)
    max_days = xd["max_hold_days"] if xd else max_days
    return {
        "side": "매수", "code": code, "qty": qty, "price": price, "amount": qty * price,
        "confidence": conf, "target_weight": round(w, 4), "regime": regime, "equity_cap": cap,
        "limited_by": binding if qty else (binding if w else "확신도 기준 미달"),
        "stop": round(price * (1 + stop_pct)),
        "take": round(price * (1 + take_pct)),
        "max_days": max_days,
        "high_vol": bool(hv), "dip": bool(dp), "index_dip": bool(xd), "inverse": bool(inv), "index": bool(C.index_etf(code, p)),
        "buy_threshold": C.buy_threshold(p),
        "probe": C.probe_floor(p) - 1e-9 <= conf < C.buy_threshold(p),   # 소액 매수 구간이면 True
    }


def sell_qty(have, conf, p, rule_exit=False):
    """판단 매도 분할 (11-05): 보정 후 확신도가 매도 기준 ~ full_at 이면 fraction 만(올림), 그 이상·규칙 매도면 전량."""
    ps = p["decision"].get("partial_sell") or {}
    if rule_exit or not ps.get("enabled") or conf >= ps["full_at"] - 1e-9 or have <= 1:
        return have, False
    return min(have, math.ceil(have * ps["fraction"])), True


def plan_sell(code, conf, price, account, p=None, rule_exit=False):
    """판단 매도는 확신도에 따라 일부 또는 전량, 손절·익절·보유일 규칙 매도(rule_exit)는 전량."""
    p = p or C.params()
    held = next((h for h in account["holdings"] if h["code"] == code), None)
    have = held["qty"] if held else 0
    qty, part = sell_qty(have, conf, p, rule_exit)
    return {"side": "매도", "code": code, "qty": qty, "price": price, "amount": qty * price, "held_qty": have,
            "confidence": conf, "partial": part, "rule_exit": rule_exit,
            "limited_by": ("분할 매도 (확신도 %.2f < 전량 기준 %.2f)" % (conf, p["decision"]["partial_sell"]["full_at"]) if part
                           else "보유 수량" if have else "보유하지 않은 종목")}
