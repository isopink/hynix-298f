"""11-09 박문화 코스닥 확대안: 시장별 몫 · 코스닥 고변동 규칙 · 코스닥 당일 +15% 매수 허용."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))
import common as C  # noqa: E402

P, R = C.params(), C.risk_limits()


def _markets(m):
    path = os.path.join(tempfile.mkdtemp(), "markets.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)
    old, C.MARKETS = C.MARKETS, path
    return old


def test_config_values():
    assert P["screen"]["market_quota"]["KOSDAQ"] == 5 and P["screen"]["max_candidates"] == 15
    assert P["high_vol"]["max_candidates"] == 5 and P["high_vol"]["kosdaq_all"]
    assert P["screen"]["prefilter_by_market"]["KOSPI"] == 40 and P["screen"]["prefilter_by_market"]["KOSDAQ"] == 35
    assert R["max_buy_day_change"] == 0.10 and R["max_buy_day_change_kosdaq"] == 0.15


def test_market_quota_10_plus_5_and_fill():
    rows = [{"code": f"1{i:04d}0", "market": "KOSPI"} for i in range(20)] + [{"code": f"2{i:04d}0", "market": "KOSDAQ"} for i in range(8)]
    out = C.market_quota(rows, P)
    assert len(out) == 15 and sum(x["market"] == "KOSDAQ" for x in out) == 5
    few = [{"code": f"1{i:04d}0", "market": "KOSPI"} for i in range(20)] + [{"code": "200000", "market": "KOSDAQ"}]
    out = C.market_quota(few, P)                       # 코스닥이 1개뿐이면 코스피로 채움
    assert len(out) == 15 and sum(x["market"] == "KOSDAQ" for x in out) == 1


def test_kosdaq_gets_high_vol_rules_and_15pct():
    old = _markets({"035720": "KOSPI", "247540": "KOSDAQ"})
    try:
        assert C.high_vol("247540", P, {"candidates": [{"code": "247540", "vol20": 0.3}]}) is P["high_vol"]
        assert C.high_vol("035720", P, {"candidates": [{"code": "035720", "vol20": 0.3}]}) is None
        assert C.exit_levels("247540", P, {"candidates": []})[:2] == (-0.12, 0.2)
        assert C.buy_day_limit("247540", R, P) == 0.15 and C.buy_day_limit("035720", R, P) == 0.10
    finally:
        C.MARKETS = old


def test_intraday_fetch_six_calls_by_market():
    import intraday
    calls = []

    class B:
        def _call(self, path, api, body):
            calls.append((api, body["mrkt_tp"]))
            cd = "005930" if body["mrkt_tp"] == "001" else "247540"
            if api == "ka10032":
                return {"trde_prica_upper": [{"stk_cd": cd, "stk_nm": "x", "cur_prc": "1000", "now_trde_qty": "10", "flu_rt": "+12.0"}]}
            return {"opmr_invsr_trde_upper": [{"stk_cd": cd, "stk_nm": "x", "netslmt": "5"}]}
    old = C.WORK
    C.WORK = tempfile.mkdtemp()
    try:
        pool, sizes = intraday.fetch(B(), intraday.num)
    finally:
        C.WORK = old
    assert sorted(set(m for _, m in calls)) == ["001", "101"] and len(calls) == 6
    assert pool["247540"]["market"] == "KOSDAQ" and pool["247540"]["foreign_qty"] == 5 and pool["005930"]["market"] == "KOSPI"
    assert sizes == {"value": 2, "foreign": 2, "inst": 2}
