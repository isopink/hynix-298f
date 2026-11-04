"""
수량 계산·리스크 규칙 테스트 (네트워크 없음).  실행: .venv/Scripts/python tests/test_rules.py
"""
import os
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import common as C  # noqa: E402

tmp = tempfile.mkdtemp()
C.WORK, C.JOURNAL, C.BRIEFING = tmp, os.path.join(tmp, "journal.jsonl"), os.path.join(tmp, "briefing.json")
os.environ.pop("RUN_MODE", None)
os.environ["RUN_ID"] = "test"

import risk  # noqa: E402
import sizing  # noqa: E402

P, R = C.params(), C.risk_limits()
P["competition"]["start"] = C.today().isoformat()   # 1주차
P["week_factor"]["1"] = 1.0                         # 계산을 단순하게 하려고 1.0 으로
P["decision"]["buy_min_confidence"] = 0.60          # 기준값은 자동 조정으로 바뀌므로 테스트에선 고정
P["decision"]["sell_min_confidence"] = 0.60
P["decision"]["min_weight"], P["decision"]["max_weight"] = 0.10, 0.20   # 수량 계산 테스트는 예전 크기(10~20%)로 고정
P["regime_cap"]["하락"] = 0.50                    # 국면 상한 테스트는 하락 50% 기준으로 고정


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
    a = acc(cash=40_000_000, holdings=[pos(str(i), 10, 100_000) for i in range(R["max_positions"])])
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
    assert C.conf_boost("LOW", "매수", 0.57, P, b)[0] == 0.62
    assert C.conf_boost("LOW", "매도", 0.57, P, b) == (0.57, None)      # 과매도는 매도에 안 붙음
    assert C.conf_boost("MID", "매수", 0.57, P, b) == (0.57, None)      # 35 는 해당 없음 (미만만)
    assert C.conf_boost("BAD", "매수", 0.57, P, b)[0] == 0.57           # 악재 뉴스면 제외
    assert C.conf_boost("NONE", "매수", 0.57, P, b) == (0.57, None)     # 브리핑에 없는 종목
    # 매도: RSI 65 이상(과열) 보유 종목 +0.05, 64.9 는 해당 없음, 악재 뉴스여도 적용
    h = {"candidates": [], "holdings": [{"code": "HOT", "rsi14": 65.0, "news": [{"risk": True}]},
                                        {"code": "WARM", "rsi14": 64.9, "news": []}]}
    assert C.conf_boost("HOT", "매도", 0.57, P, h)[0] == 0.62
    assert C.conf_boost("HOT", "매수", 0.57, P, h) == (0.57, None)      # 과열은 매수에 안 붙음
    assert C.conf_boost("WARM", "매도", 0.57, P, h) == (0.57, None)
    C.write_json(C.BRIEFING, h)
    try:
        a = acc(cash=40_000_000, holdings=[pos("HOT", 10, 100_000), pos("WARM", 10, 100_000)])
        assert "확신도" not in rules({"code": "HOT", "side": "매도", "qty": 10, "confidence": 0.57}, a, 100_000)
        assert "확신도" in rules({"code": "WARM", "side": "매도", "qty": 10, "confidence": 0.57}, a, 100_000)
    finally:
        os.remove(C.BRIEFING)
    # 리스크 검사도 같은 보정: 0.57 은 원래 막히지만 RSI 30 종목은 통과
    C.write_json(C.BRIEFING, b)
    try:
        assert "확신도" not in rules({"code": "LOW", "side": "매수", "qty": 10, "confidence": 0.57}, acc(), 100_000)
        assert "확신도" in rules({"code": "MID", "side": "매수", "qty": 10, "confidence": 0.57}, acc(), 100_000)
    finally:
        os.remove(C.BRIEFING)


def test_market_boost_and_live_rsi():
    b = {"candidates": [{"code": "LOW", "rsi14": 30.2, "news": []},
                        {"code": "BAD", "rsi14": 50.0, "news": [{"risk": True}]},
                        {"code": "UP", "rsi14": 50.0, "rsi14_live": 33.0, "news": []},
                        {"code": "DOWN", "rsi14": 30.0, "rsi14_live": 40.0, "news": []}], "holdings": []}
    assert C.conf_boost("MID", "매수", 0.60, P, b, regime="하락")[0] == 0.65      # 하락 국면 매수 +0.05
    assert C.conf_boost("LOW", "매수", 0.55, P, b, regime="하락")[0] == 0.65      # RSI 과매도와 합산
    assert C.conf_boost("BAD", "매수", 0.60, P, b, regime="하락")[0] == 0.60      # 악재 뉴스면 제외
    assert C.conf_boost("MID", "매수", 0.60, P, b, regime="횡보") == (0.60, None)
    assert C.conf_boost("MID", "매도", 0.60, P, b, regime="하락") == (0.60, None)   # 매도엔 안 붙음
    assert C.conf_boost("UP", "매수", 0.57, P, b, regime="")[0] == 0.62           # 장중 RSI 우선
    assert C.conf_boost("DOWN", "매수", 0.57, P, b, regime="") == (0.57, None)
    C.write_json(C.BRIEFING, b)
    try:   # 리스크 검사는 오늘 기록된 국면을 읽음 (rules() 가 국면을 기록)
        assert "확신도" in rules({"code": "MID", "side": "매수", "qty": 1, "confidence": 0.56}, acc(), 100_000, regime="횡보")
        assert "확신도" not in rules({"code": "MID", "side": "매수", "qty": 1, "confidence": 0.56}, acc(), 100_000, regime="하락")
    finally:
        os.remove(C.BRIEFING)


def test_view_run_blocks_orders():
    os.environ["RUN_MODE"] = "view"   # 판단 갱신 회차: 매수·매도 모두 막힘
    try:
        a = acc(cash=40_000_000, holdings=[pos("A", 10, 100_000)])
        assert "실행 종류" in rules({"code": "005930", "side": "매수", "qty": 1, "confidence": 0.9}, acc(), 100_000)
        assert "실행 종류" in rules({"code": "A", "side": "매도", "qty": 10, "confidence": 0.9}, a, 100_000)
    finally:
        os.environ.pop("RUN_MODE", None)


def test_trade_slot():
    p = {"schedule": {"trade_times": ["09:30", "10:30"]}}
    t = lambda h, m: datetime(2026, 11, 3, h, m, 7, tzinfo=C.KST)  # noqa: E731
    assert C.trade_slot(t(9, 31), p) and not C.trade_slot(t(9, 45), p) and not C.trade_slot(t(9, 15), p)
    assert C.next_trade_time(t(9, 45), p) == "10:30" and C.next_trade_time(t(10, 30), p) is None
    assert C.trade_slot(t(9, 45), {"schedule": {}})   # trade_times 가 없으면 모든 회차가 매매


def test_intraday_screen():
    import intraday
    base = {"ma5": 10_000, "ma20": 9_500, "trading_value_20d": 50_000_000_000, "vol20": 0.4, "ret5": 0.03,
            "limit_up_recent": False}
    rows = [
        {**base, "code": "000010", "name": "활발", "price": 10_500, "chg": 0.03, "value": 40_000_000_000, "foreign_qty": 50_000, "inst_qty": 10_000},
        {**base, "code": "000020", "name": "보통", "price": 10_300, "chg": 0.01, "value": 10_000_000_000, "foreign_qty": 5_000, "inst_qty": 0},
        {**base, "code": "000030", "name": "개인만", "price": 10_300, "chg": 0.01, "value": 30_000_000_000, "foreign_qty": -1, "inst_qty": -1},
        {**base, "code": "000040", "name": "급등", "price": 11_500, "chg": 0.12, "value": 60_000_000_000, "foreign_qty": 9_000, "inst_qty": 0},
        {**base, "code": "000050", "name": "추세이탈", "price": 9_400, "chg": -0.02, "value": 30_000_000_000, "foreign_qty": 9_000, "inst_qty": 0},
        {**base, "code": "000061", "name": "우선주", "price": 10_500, "chg": 0.01, "value": 30_000_000_000, "foreign_qty": 9_000, "inst_qty": 0},
        {**base, "code": "000070", "name": "가나스팩", "price": 10_500, "chg": 0.01, "value": 30_000_000_000, "foreign_qty": 9_000, "inst_qty": 0},
    ]
    out = intraday.screen([dict(r) for r in rows], P, R, frac=0.5)
    assert [c["name"] for c in out] == ["활발", "보통"], [c["name"] for c in out]   # 외국인·기관 매수 없음·+10%·추세 이탈·우선주·스팩 제외
    assert out[0]["score"] == 1.0 and out[0]["activity"] == 1.6                     # 400억 ÷ (500억 × 0.5)
    assert intraday.code6("A005930_AL") == "005930" and intraday.num("+1,234") == 1234
    assert intraday.rank_pct([3, 1, 2, 2]) == [1.0, 0.25, 0.625, 0.625]


def test_high_vol_small_and_wide():
    b = {"candidates": [{"code": "HOT", "vol20": 1.6, "news": []}, {"code": "CALM", "vol20": 0.4, "news": []}], "holdings": []}
    C.write_json(C.BRIEFING, b)
    try:
        assert C.high_vol("HOT", P) and C.high_vol("CALM", P) is None
        assert C.exit_levels("HOT", P)[:2] == (P["high_vol"]["stop_loss_pct"], P["high_vol"]["take_profit_pct"])
        C.journal("regime", regime="상승", cap=P["regime_cap"]["상승"])
        plan = sizing.plan_buy("HOT", 0.95, 10_000, acc(), P, R)
        assert plan["qty"] * 10_000 <= 50_000_000 * P["high_vol"]["weight_cap"] and plan["limited_by"] == "고변동 종목 한도"
        assert plan["stop"] == round(10_000 * (1 + P["high_vol"]["stop_loss_pct"]))
        assert "고변동 종목 한도" in rules({"code": "HOT", "side": "매수", "qty": 300, "confidence": 0.95}, acc(), 10_000)   # 6%
        assert "고변동 종목 한도" not in rules({"code": "CALM", "side": "매수", "qty": 300, "confidence": 0.95}, acc(), 10_000)
    finally:
        os.remove(C.BRIEFING)


def test_intraday_keeps_high_vol_separately():
    import intraday
    base = {"ma5": 10_000, "ma20": 9_500, "trading_value_20d": 50_000_000_000, "ret5": 0.03, "limit_up_recent": False,
            "price": 10_500, "chg": 0.02, "value": 30_000_000_000, "foreign_qty": 5_000, "inst_qty": 0}
    rows = [{**base, "code": f"0000{i}0", "name": f"보통{i}", "vol20": 0.4} for i in range(1, 4)]
    rows += [{**base, "code": "000910", "name": "고변동", "vol20": 1.8}, {**base, "code": "000920", "name": "너무큼", "vol20": 3.5}]
    out = intraday.screen([dict(r) for r in rows], P, R, frac=0.5)
    names = [c["name"] for c in out]
    assert "고변동" in names and "너무큼" not in names and names[-1] == "고변동"


def test_reconcile_partial_fill():
    import logger
    old = C.ACCOUNT
    C.ACCOUNT = os.path.join(tmp, "account.json")
    try:
        t = lambda side, qty, code="086280": {"code": code, "side": side, "qty": qty, "price": 201000, "amount": qty * 201000}
        C.write_json(C.ACCOUNT, {"holdings": [{"code": "086280", "qty": 14}]})
        ts = logger.reconcile([t("매수", 3)])                 # 2초 뒤엔 3주만 보였지만 잔고는 14주
        assert ts[0]["qty"] == 14 and ts[0]["amount"] == 14 * 201000, ts
        C.write_json(C.ACCOUNT, {"holdings": []})
        ts = logger.reconcile([t("매수", 10), t("매도", 4)])   # 매도가 일부만 보였지만 이미 다 팔림
        assert ts[1]["qty"] == 10, ts
        C.write_json(C.ACCOUNT, {"holdings": [{"code": "086280", "qty": 14}]})
        ts = logger.reconcile([t("매수", 14)])                # 맞으면 그대로
        assert ts[0]["qty"] == 14, ts
    finally:
        C.ACCOUNT = old

def test_inverse_only_in_falling_market():
    inv = "114800"
    assert C.inverse(inv, P) and not C.inverse("005930", P)
    a = acc()
    C.journal("regime", regime="횡보", cap=P["regime_cap"]["횡보"])
    plan = sizing.plan_buy(inv, 0.80, 5_000, a, P, R)
    assert plan["qty"] == 0 and "국면만" in plan["limited_by"], plan
    assert "인버스 국면" in rules({"code": inv, "side": "매수", "qty": 100, "confidence": 0.80}, a, 5_000, regime="횡보")
    C.journal("regime", regime="하락", cap=P["regime_cap"]["하락"])
    plan = sizing.plan_buy(inv, 0.80, 5_000, a, P, R)
    assert plan["qty"] > 0 and plan["inverse"], plan
    assert plan["qty"] * 5_000 <= a["total"] * P["inverse"]["weight_cap"], plan
    assert not rules({"code": inv, "side": "매수", "qty": plan["qty"], "confidence": 0.80}, a, 5_000, regime="하락")
    held = acc(40_000_000, [pos(inv, 1_800, 5_000)])   # 이미 18% 보유 → 1,000주(+10%) 더 사면 인버스 한도 20% 초과
    assert "인버스 한도" in rules({"code": inv, "side": "매수", "qty": 1_000, "confidence": 0.80}, held, 5_000, regime="하락")


def test_inverse_outside_equity_cap():
    """인버스 보유분은 주식 비중 상한에 들어가지 않음."""
    C.journal("regime", regime="하락", cap=P["regime_cap"]["하락"])
    big = [pos("000660", 200, 100_000)]   # 주식 2,000만 (40%) → 국면 상한까지 여유가 확신도 비중보다 작음
    a = acc(25_000_000, big + [pos("114800", 1_000, 5_000)])   # + 인버스 500만 (10%)
    b = acc(30_000_000, big)
    assert C.stock_value(a["holdings"], P) == 20_000_000
    with_inv = sizing.plan_buy("005930", 0.80, 100_000, a, P, R)
    without = sizing.plan_buy("005930", 0.80, 100_000, b, P, R)
    assert with_inv["qty"] == without["qty"] and with_inv["limited_by"] == "국면 상한 여유", (with_inv, without)
    assert "국면 비중 상한" not in rules({"code": "005930", "side": "매수", "qty": with_inv["qty"], "confidence": 0.80}, a, 100_000, regime="하락")


def test_fill_up_from_prep():
    import intraday
    prep = [{"code": c} for c in ("A", "B", "C", "D", "E", "F")] + [{"code": "114800", "inverse": True}]
    out = intraday.fill_up([{"code": "X"}, {"code": "B"}], prep, held={"A"}, n=5)
    codes = [c["code"] for c in out]
    assert codes == ["X", "B", "C", "D", "E", "114800"], codes
    assert [c.get("from_prep") for c in out[:5]] == [None, None, True, True, True]
    out = intraday.fill_up([{"code": c} for c in "VWXYZ"], prep, held=set(), n=5)
    assert [c["code"] for c in out] == list("VWXYZ") + ["114800"]

def test_every_run_kind_has_a_work_check():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import run
    assert set(run.PROMPTS) <= set(run.EXPECT), set(run.PROMPTS) - set(run.EXPECT)   # 11-04 view 가 빠져 KeyError 로 실패
    assert run.summary_line("판단 갱신 / 하락 / 매수 예정 1건 / 매도 예정 0건 / 관망 3건") == "판단 갱신 / 하락 / 매수 예정 1건 / 매도 예정 0건 / 관망 3건"
    assert run.summary_line("하락 / 매수 0건 / 매도 0건 / 관망 2건") == "하락 / 매수 0건 / 매도 0건 / 관망 2건"

def test_inverse_quick_exit_and_one_buy_a_day():
    """인버스: 수수료·세금 뺀 순익 +1.5% 에 익절, 최대 2일, 하루 1번만 매수."""
    inv = "114800"
    sl, tp, md = C.exit_levels(inv, P)
    c = P["costs"]
    net = (1 + tp) * (1 - c["fee_rate"] - P["inverse"]["sell_tax_rate"]) / (1 + c["fee_rate"]) - 1   # ETF 는 매도 세금 없음
    assert abs(net - P["inverse"]["take_profit_net_pct"]) < 1e-4 and md == P["inverse"]["max_hold_days"], (tp, net, md)
    assert C.exit_levels("005930", P)[1] == P["decision"]["take_profit_pct"]   # 다른 종목은 그대로
    old = C.POSITIONS
    try:   # 예전 규칙(+15% · 10일)으로 기록된 보유분도 평단 기준 지금 규칙으로 (11-04 10:33 매수분)
        C.POSITIONS = os.path.join(tmp, "positions.json")
        C.write_json(C.POSITIONS, {inv: {"entry_date": "2026-11-04", "stop": 1129, "take": 1396, "max_days": 10}, "005930": {"take": 9}})
        m = C.position_meta([{"code": inv, "avg_price": 1214}, {"code": "005930", "avg_price": 100}], P)
        assert m[inv]["take"] == 1241 and m[inv]["max_days"] == 2 and m["005930"]["take"] == 9, m
    finally:
        C.POSITIONS = old
    open(C.JOURNAL, "w").close()
    C.journal("regime", regime="하락", cap=P["regime_cap"]["하락"])
    a = acc()
    assert sizing.plan_buy(inv, 0.80, 5_000, a, P, R)["qty"] > 0
    C.journal("fill", code=inv, side="매수", qty=100, price=5_000)
    C.journal("fill", code=inv, side="매도", qty=100, price=5_100)
    plan = sizing.plan_buy(inv, 0.80, 5_000, a, P, R)
    assert plan["qty"] == 0 and "하루" in plan["limited_by"], plan
    assert "인버스 하루 매수" in rules({"code": inv, "side": "매수", "qty": 100, "confidence": 0.80}, a, 5_000, regime="하락")
    assert "인버스 하루 매수" not in rules({"code": "005930", "side": "매수", "qty": 10, "confidence": 0.80}, a, 100_000, regime="하락")


def test_monitor_retries_same_position_after_cooldown():
    """감시: 같은 매수 건은 실행 뒤 10분 안엔 다시 안 띄움, 지나면 다시 (하루 1번 제한 없음). 장 전엔 한 번만."""
    import monitor
    old = (C.POSITIONS, monitor.STATE, monitor.holdings, monitor.subprocess.run, monitor.time.time, C.now)
    calls, clock = [], {"t": 1_000_000.0, "now": datetime(2026, 11, 4, 10, 0, tzinfo=C.KST)}
    try:
        C.POSITIONS, monitor.STATE = os.path.join(tmp, "positions.json"), os.path.join(tmp, "monitor_state.json")
        C.write_json(C.POSITIONS, {"114800": {"name": "인버스", "entry_date": "2026-11-04", "stop": 4_650, "take": 5_121, "max_days": 2}})
        hs = [{"code": "114800", "name": "인버스", "price": 5_130}]
        monitor.holdings = lambda: hs
        monitor.subprocess.run = lambda *a, **k: calls.append(a) or type("R", (), {"returncode": 0})()
        monitor.time.time = lambda: clock["t"]
        C.now = lambda: clock["now"]
        if os.path.exists(monitor.STATE):
            os.remove(monitor.STATE)
        monitor.check_once(); assert len(calls) == 1
        clock["t"] += 60; monitor.check_once(); assert len(calls) == 1          # 1분 뒤: 아직 매도 체결 대기 → 다시 안 띄움
        clock["t"] += 10 * 60; monitor.check_once(); assert len(calls) == 2     # 10분 지나도 남아 있으면 다시
        C.write_json(C.POSITIONS, {"114800": {"name": "인버스", "entry_date": "2026-11-04", "stop": 4_700, "take": 5_125, "max_days": 2}})
        clock["t"] += 60; monitor.check_once(); assert len(calls) == 3          # 다시 산 새 건은 바로
        os.remove(monitor.STATE); calls.clear()
        clock["now"] = datetime(2026, 11, 4, 8, 40, tzinfo=C.KST)
        monitor.check_once(); clock["t"] += 15 * 60; monitor.check_once()
        assert len(calls) == 1                                                 # 장 전엔 한 번만
        clock["now"] = datetime(2026, 11, 4, 9, 6, tzinfo=C.KST)
        monitor.check_once(); assert len(calls) == 2                           # 09:05 뒤 남아 있으면 다시
    finally:
        C.POSITIONS, monitor.STATE, monitor.holdings, monitor.subprocess.run, monitor.time.time, C.now = old


def test_index_etf_only_in_rising_or_sideways():
    ix = "069500"
    assert C.index_etf(ix, P) and C.market_etf(ix, P)[1] == "지수" and C.market_etf("114800", P)[1] == "인버스"
    assert C.market_etf("005930", P) == (None, None)
    a = acc()
    C.journal("regime", regime="하락", cap=P["regime_cap"]["하락"])
    plan = sizing.plan_buy(ix, 0.80, 40_000, a, P, R)
    assert plan["qty"] == 0 and "지수는" in plan["limited_by"], plan
    assert "지수 국면" in rules({"code": ix, "side": "매수", "qty": 10, "confidence": 0.80}, a, 40_000, regime="하락")
    C.journal("regime", regime="횡보", cap=P["regime_cap"]["횡보"])
    plan = sizing.plan_buy(ix, 0.80, 40_000, a, P, R)
    assert plan["qty"] > 0 and plan["index"], plan
    assert not rules({"code": ix, "side": "매수", "qty": plan["qty"], "confidence": 0.80}, a, 40_000, regime="횡보")
    # 지수는 주식 상한 안에서 (인버스처럼 빠지지 않음)
    assert C.stock_value([pos(ix, 100, 40_000)], P) == 4_000_000
    sl, tp, md = C.exit_levels(ix, P)
    assert md == P["index"]["max_hold_days"] and abs(tp - C.gross_take(P["index"]["take_profit_net_pct"], P, 0.0)) < 1e-9


def test_index_once_a_day():
    ix = "069500"
    C.journal("fill", code=ix, name="KODEX 200", side="매수", qty=10, price=40_000, amount=400_000)
    C.journal("regime", regime="상승", cap=P["regime_cap"]["상승"])
    plan = sizing.plan_buy(ix, 0.80, 40_000, acc(), P, R)
    assert plan["qty"] == 0 and "하루" in plan["limited_by"], plan
    assert "지수 하루 매수" in rules({"code": ix, "side": "매수", "qty": 10, "confidence": 0.80}, acc(), 40_000, regime="상승")


def test_fill_up_keeps_both_etfs():
    import intraday
    prep = [{"code": "A"}, {"code": "114800", "inverse": True}, {"code": "069500", "index": True}]
    out = intraday.fill_up([{"code": "X"}], prep, held=set(), n=5)
    assert [c["code"] for c in out] == ["X", "A", "114800", "069500"], out

def test_missed_trade_catch_up():
    p = {"schedule": {"trade_times": ["09:45", "10:45"]}}
    t = lambda h, m: datetime(2026, 11, 4, h, m, 7, tzinfo=C.KST)  # noqa: E731
    reg = lambda hm, mode: {"kind": "regime", "time": f"2026-11-04 {hm}", "mode": mode}  # noqa: E731
    assert C.missed_trade(t(9, 30), p, []) is None                       # 아직 매매 시각 전
    assert C.missed_trade(t(10, 0), p, []) == "09:45"                     # 09:45 매매 실행이 없었음 → 10:00 이 대신
    assert C.missed_trade(t(10, 0), p, [reg("09:47", "decide")]) is None  # 09:45 매매 실행 있었음
    assert C.missed_trade(t(10, 0), p, [reg("09:47", "view")]) == "09:45" # 판단 갱신은 매매로 안 침
    assert C.missed_trade(t(10, 0), p, [reg("09:31", "decide")]) == "09:45"   # 매매 시각 전 기록은 안 침
    assert C.missed_trade(t(11, 0), p, [reg("09:47", "decide")]) == "10:45"   # 가장 최근 매매 시각 기준
    assert C.missed_trade(t(10, 0), p, [{**reg("09:47", "decide"), "time": "2026-11-03 09:47"}]) == "09:45"   # 어제 기록은 안 침


def test_last_trade_summary():
    import logger
    t = C.today().isoformat()
    base = {"bull": "", "bear": "", "decision": ""}
    rows = [
        {"kind": "regime", "run": "r1", "time": f"{t} 10:31", "regime": "하락", "cap": .38},
        {"kind": "fill", "run": "r1", "code": "A", "name": "KT&G", "side": "매수", "qty": 10, "price": 1, "confidence": .67, **base},
        {"kind": "decision", "run": "r1", "code": "B", "name": "삼성화재", "action": "관망", "confidence": .5, **base},
        {"kind": "decision", "run": "r1", "code": "C", "name": "안랩", "action": "관망", "confidence": .6, **base},
        {"kind": "block", "run": "r1", "code": "C", "name": "안랩", "side": "매수", "rule": "고변동 종목 한도", "detail": "6%"},
        {"kind": "decision", "run": "r1", "code": "D", "name": "HMM", "action": "보유", "confidence": .3, **base},
        {"kind": "regime", "run": "r2", "time": f"{t} 10:46", "regime": "하락", "cap": .38, "mode": "view"},   # 판단 갱신은 무시
    ]
    lt = logger.last_trade(rows, {})
    assert lt["time"] == "10:31" and lt["bought"] == [{"name": "KT&G", "qty": 10}] and lt["sold"] == []
    assert lt["blocked"] == [{"name": "안랩", "rule": "고변동 종목 한도"}] and lt["watch"] == 2 and lt["hold"] == 1
    assert logger.last_trade(rows[-1:], {}) is None   # 오늘 매매 회차가 없으면 표시 안 함


def test_max_weight_splits_positions():
    p = {**P, "decision": {**P["decision"], "min_weight": 0.05, "max_weight": 0.10}}
    assert sizing.target_weight(0.60, p, R) == 0.05
    assert sizing.target_weight(0.95, p, R) == 0.10            # 확신도 최대여도 종목당 10% (리스크 한도 20% 보다 작게)
    C.journal("regime", regime="상승", cap=P["regime_cap"]["상승"])
    plan = sizing.plan_buy("005930", 0.95, 10_000, acc(), p, R)
    assert plan["qty"] * 10_000 <= 50_000_000 * 0.10 + 10_000


def test_inverse_buys_up_to_its_own_cap():
    """종목당 최대 10% 로 나눠 사도, 인버스는 확신도 최대면 인버스 한도 20% 까지 한 번에."""
    p = {**P, "decision": {**P["decision"], "min_weight": 0.05, "max_weight": 0.10}}
    C.journal("regime", regime="하락", cap=P["regime_cap"]["하락"])
    stock = sizing.plan_buy("005930", 0.95, 10_000, acc(), p, R)
    inv = sizing.plan_buy("114800", 0.95, 5_000, acc(), p, R)
    assert stock["target_weight"] == 0.10 and inv["target_weight"] == 0.20, (stock, inv)
    assert sizing.target_weight(0.95, p, R, top=P["inverse"]["weight_cap"]) == 0.20


def test_other_etf_names_blocked():
    assert C.other_etf("TIGER 반도체", P) and C.other_etf("KODEX 레버리지", P) and C.other_etf("신한 인버스 2X 원유선물 ETN", P)
    assert not C.other_etf("SK하이닉스", P) and not C.other_etf("한화비전", P)


def test_tuning_sees_boosted_watch_confidence():
    import tuning
    rows = [{"kind": "regime", "run": "a", "regime": "하락"},
            {"kind": "decision", "run": "a", "action": "관망", "confidence": 0.57, "mode": "decide"},           # 옛 기록 → +0.05 추정
            {"kind": "decision", "run": "a", "action": "관망", "confidence": 0.55, "confidence_adj": 0.65, "mode": "decide"},
            {"kind": "decision", "run": "a", "action": "관망", "confidence": 0.70, "mode": "view"}]            # 판단 갱신은 뺌
    assert tuning.watch_confidence(rows, P) == [0.65, 0.62]
    bad = {**P, "decision": {**P["decision"], "min_weight": 0.15, "max_weight": 0.10}}
    assert any("최대 종목 비중" in e for e in tuning.consistency(bad))


def test_prior_judgments_in_briefing():
    t = C.today().isoformat()
    rows = [
        {"kind": "regime", "run": "r1", "time": f"{t} 13:46", "regime": "하락", "mode": "view"},
        {"kind": "decision", "run": "r1", "code": "114800", "name": "KODEX 인버스", "action": "관망", "confidence": 0.6, "decision": "a|b"},
        {"kind": "regime", "run": "r2", "time": f"{t} 14:01", "regime": "하락", "mode": "view"},
        {"kind": "decision", "run": "r2", "code": "114800", "name": "KODEX 인버스", "action": "매수 예정", "confidence": 0.68, "decision": "x"},
        {"kind": "regime", "run": "r3", "time": f"{t} 14:16", "regime": "하락", "mode": "decide"},   # 이번 실행 → 빠짐
        {"kind": "regime", "run": "old", "time": "2026-01-01 10:00", "regime": "상승"},              # 오늘 아님 → 빠짐
    ]
    txt = C.prior_judgments(rows=rows, run="r3")
    assert "## 직전 판단" in txt and txt.index("14:01 판단 갱신") < txt.index("13:46 판단 갱신")   # 최근 것부터
    assert "| KODEX 인버스 | 매수 예정 | 0.68 |" in txt and "a/b" in txt and "14:16" not in txt
    assert C.prior_judgments(rows=rows[-2:], run="r3") == ""


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
