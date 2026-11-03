"""
수량 계산: 확신도 → 목표 비중 → 주문 수량, 손절·익절·최대 보유일.

에이전트는 "이 종목을 확신도 0.72로 산다"까지만 정하고, 몇 주를 살지는 여기서 정합니다.
"""
import math

import common as C


def target_weight(conf, p, r):
    """확신도 → 종목 목표 비중. 기준 미만이면 0, full_size 이상이면 종목 한도."""
    d = p["decision"]
    lo, hi = C.buy_threshold(p), d["full_size_confidence"]
    top = r["max_weight_per_stock"]
    if conf < lo:
        return 0.0
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


def plan_buy(code, conf, price, account, p=None, r=None, regime=None):
    p, r = p or C.params(), r or C.risk_limits()
    total, cash = account["total"], account["cash"]
    held = next((h for h in account["holdings"] if h["code"] == code), None)
    held_value = held["qty"] * price if held else 0
    stock_value = sum(h["value"] for h in account["holdings"])
    cap, regime = equity_cap(p, r, account, regime)

    w = target_weight(conf, p, r)
    limits = {
        "확신도 비중": total * w * C.week_factor(p) - held_value,
        "국면 상한 여유": total * cap - stock_value,
        "최소 현금 유지": cash - total * r["min_cash_ratio"],
        "1회 주문 한도": r["max_order_amount"],
        "종목 한도": total * r["max_weight_per_stock"] - held_value,
    }
    hv = C.high_vol(code, p)
    if hv:   # 변동성이 큰 종목은 작게만
        limits["고변동 종목 한도"] = total * hv["weight_cap"] - held_value
    binding = min(limits, key=limits.get)
    budget = max(0.0, limits[binding])
    unit = price * (1 + p["costs"]["fee_rate"])
    qty = math.floor(budget / unit) if price > 0 else 0
    stop_pct, take_pct, max_days = C.exit_levels(code, p)
    return {
        "side": "매수", "code": code, "qty": qty, "price": price, "amount": qty * price,
        "confidence": conf, "target_weight": round(w, 4), "regime": regime, "equity_cap": cap,
        "limited_by": binding if qty else (binding if w else "확신도 기준 미달"),
        "stop": round(price * (1 + stop_pct)),
        "take": round(price * (1 + take_pct)),
        "max_days": max_days,
        "high_vol": bool(hv),
        "buy_threshold": C.buy_threshold(p),
    }


def plan_sell(code, conf, price, account, p=None):
    """매도는 전량. (분할 매도는 아직 안 함)"""
    p = p or C.params()
    held = next((h for h in account["holdings"] if h["code"] == code), None)
    qty = held["qty"] if held else 0
    return {"side": "매도", "code": code, "qty": qty, "price": price, "amount": qty * price,
            "confidence": conf, "limited_by": "보유 수량" if qty else "보유하지 않은 종목"}
