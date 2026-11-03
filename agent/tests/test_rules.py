"""
수량 계산·리스크 규칙 테스트 (네트워크 없음).  실행: .venv/Scripts/python tests/test_rules.py
"""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import common as C  # noqa: E402

tmp = tempfile.mkdtemp()
C.WORK, C.JOURNAL, C.BRIEFING = tmp, os.path.join(tmp, "journal.jsonl"), os.path.join(tmp, "briefing.json")
os.environ.pop("RUN_MODE", None)
os.environ["RUN_ID"] = "test"

import risk  # noqa: E402
import sizing  # noqa: E402

P, R = C.params(), C.risk_limits()
P["competition"]["start"] = C.today().isoformat()   # 1주차 → 비중 계수 0.5
P["week_factor"]["1"] = 1.0                         # 계산을 단순하게 하려고 1.0 으로


def acc(cash=50_000_000, holdings=()):
    hs = [dict(h) for h in holdings]
    return {"total": cash + sum(h["value"] for h in hs), "cash": cash, "holdings": hs}


def pos(code, qty, price):
    return {"code": code, "name": code, "qty": qty, "avg_price": price, "price": price, "value": qty * price}


def rules(order, a, price, regime="상승"):
    C.journal("regime", regime=regime, cap=P["regime_cap"][regime])
    return [r for r, _ in risk.check(order, a, price, P, R)]


def test_weight_curve():
    assert sizing.target_weight(0.59, P, R) == 0
    assert sizing.target_weight(0.60, P, R) == P["decision"]["min_weight"]
    assert sizing.target_weight(0.90, P, R) == R["max_weight_per_stock"]


def test_plan_buy_respects_order_cap():
    a = acc()
    C.journal("regime", regime="상승", cap=0.9)
    plan = sizing.plan_buy("005930", 0.85, 100_000, a, P, R, "상승")
    # 확신도 최대 → 종목 한도 20% = 1,000만 원 = 1회 주문 한도와 같음
    assert plan["qty"] == 99, plan
    assert rules({"code": "005930", "side": "매수", "qty": plan["qty"], "confidence": 0.85}, a, 100_000) == []


def test_low_confidence_blocked():
    assert "확신도" in rules({"code": "005930", "side": "매수", "qty": 10, "confidence": 0.5}, acc(), 100_000)


def test_over_plan_qty_blocked():
    r = rules({"code": "005930", "side": "매수", "qty": 150, "confidence": 0.85}, acc(), 100_000)
    assert "수량 계산 초과" in r and "1회 주문 한도" in r and "종목 한도" in r


def test_regime_cap():
    a = acc(cash=25_000_000, holdings=[pos("A", 100, 125_000), pos("B", 100, 125_000)])   # 주식 50%
    r = rules({"code": "005930", "side": "매수", "qty": 50, "confidence": 0.85}, a, 100_000, regime="하락")
    assert "국면 비중 상한" in r


def test_max_positions():
    a = acc(cash=40_000_000, holdings=[pos(str(i), 10, 100_000) for i in range(6)])
    assert "보유 종목 수" in rules({"code": "X", "side": "매수", "qty": 1, "confidence": 0.9}, a, 100_000)


def test_daily_loss_stops_buys():
    C.write_json(os.path.join(C.WORK, "day_start.json"), {"date": C.today().isoformat(), "total": 52_000_000})
    try:
        assert "일일 손실 한도" in rules({"code": "X", "side": "매수", "qty": 1, "confidence": 0.9}, acc(), 100_000)
    finally:
        os.remove(os.path.join(C.WORK, "day_start.json"))


def test_no_short_and_exit_mode():
    a = acc(holdings=[pos("A", 10, 100_000)])
    assert "보유 수량" in rules({"code": "A", "side": "매도", "qty": 11, "confidence": 0.9}, a, 100_000)
    assert rules({"code": "A", "side": "매도", "qty": 10, "confidence": 0.9}, a, 100_000) == []
    os.environ["RUN_MODE"] = "exit"
    try:
        assert "실행 종류" in rules({"code": "B", "side": "매수", "qty": 1, "confidence": 0.9}, a, 100_000)
        assert rules({"code": "A", "side": "매도", "qty": 10, "confidence": 0.0}, a, 100_000) == []
    finally:
        os.environ.pop("RUN_MODE")


def test_business_days():
    assert C.business_days("2026-11-06", date(2026, 11, 9)) == 1   # 금 → 월
    assert C.business_days("2026-11-02", date(2026, 11, 16)) == 10


def test_rsi_boost():
    b = {"candidates": [{"code": "LOW", "rsi14": 30.2, "news": []},
                        {"code": "BAD", "rsi14": 28.0, "news": [{"risk": True}]},
                        {"code": "MID", "rsi14": 35.0, "news": []}], "holdings": []}
    assert C.rsi_boost("LOW", "매수", 0.57, P, b)[0] == 0.62
    assert C.rsi_boost("LOW", "매도", 0.57, P, b) == (0.57, None)      # 매도엔 안 붙음
    assert C.rsi_boost("MID", "매수", 0.57, P, b) == (0.57, None)      # 35 는 해당 없음 (미만만)
    assert C.rsi_boost("BAD", "매수", 0.57, P, b)[0] == 0.57           # 악재 뉴스면 제외
    assert C.rsi_boost("NONE", "매수", 0.57, P, b) == (0.57, None)     # 브리핑에 없는 종목
    # 리스크 검사도 같은 보정: 0.57 은 원래 막히지만 RSI 30 종목은 통과
    C.write_json(C.BRIEFING, b)
    try:
        assert "확신도" not in rules({"code": "LOW", "side": "매수", "qty": 10, "confidence": 0.57}, acc(), 100_000)
        assert "확신도" in rules({"code": "MID", "side": "매수", "qty": 10, "confidence": 0.57}, acc(), 100_000)
    finally:
        os.remove(C.BRIEFING)


if __name__ == "__main__":
    fails = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f()
                print("ok  ", n)
            except AssertionError as e:
                fails += 1
                print("FAIL", n, e)
    sys.exit(1 if fails else 0)
