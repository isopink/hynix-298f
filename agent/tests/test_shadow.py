"""그림자 운영 (src/shadow.py · broker.ShadowBroker): 실제 계좌로 시작, 실제 시스템의 순위·현재가 재사용, 실제 파일은 안 건드림."""
import hashlib
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))
import common as C  # noqa: E402


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _digest(root):
    h = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            h[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return h


def _real(tmp):
    real = os.path.join(tmp, "real")
    w = os.path.join(real, "agent", "work")
    _w(os.path.join(w, "account.json"), {"total": 49_000_000, "cash": 30_000_000, "holdings": [
        {"code": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100_000, "price": 101_000, "value": 1_010_000}]})
    _w(os.path.join(w, "positions.json"), {"005930": {"name": "삼성전자", "entry_date": "2026-11-05", "stop": 93_000, "take": 110_000, "max_days": 5}})
    _w(os.path.join(w, "quotes.json"), {"005930": {"price": 102_000, "ts": time.time(), "change": 0.01}})
    body = {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}
    _w(os.path.join(w, "rank_raw", "value.json"), {"time": C.stamp(), "api": "ka10032", "body": body, "response": {"trde_prica_upper": [{"stk_cd": "005930"}]}})
    return real, body


def test_shadow_seed_quotes_rank_and_isolation():
    tmp = tempfile.mkdtemp()
    real, body = _real(tmp)
    before = _digest(real)
    old = {k: os.environ.get(k) for k in ("MODE", "SHADOW_OF")}
    old_work = (C.WORK, C.POSITIONS)
    try:
        os.environ.update(MODE="mock", SHADOW_OF=real)
        import broker
        import shadow
        own = os.path.join(tmp, "own")
        os.makedirs(own)
        C.WORK, C.POSITIONS = own, os.path.join(own, "positions.json")
        broker.MOCK_ACCOUNT, broker.QUOTES = os.path.join(own, "mock_account.json"), os.path.join(own, "quotes.json")
        C.JOURNAL = os.path.join(own, "journal.jsonl")
        assert shadow.active()
        b = broker.get()
        assert isinstance(b, broker.ShadowBroker) and b.replays_rank
        st = C.read_json(broker.MOCK_ACCOUNT)
        assert st["cash"] == 30_000_000 and st["positions"]["005930"]["qty"] == 10 and st["seed_total"] == 49_000_000
        assert C.read_json(C.POSITIONS)["005930"]["stop"] == 93_000   # 손절·익절 기록도 복사
        assert b.quote("005930") == 102_000                           # 실제 시스템이 본 현재가
        assert b._call("/x", "ka10032", body) == {"trde_prica_upper": [{"stk_cd": "005930"}]}
        try:
            b._call("/x", "ka10065", {"trde_tp": "1"})
            raise AssertionError("없는 순위 원문은 오류여야 함")
        except RuntimeError:
            pass
        r = b._order_once("005930", "삼성전자", "매도", 5, "shadow-test-1")  # 주문 권한 장부(plan_order) 없이 가상 체결만 확인                 # 가상 계좌만 바뀜
        assert r["ok"] and C.read_json(broker.MOCK_ACCOUNT)["positions"]["005930"]["qty"] == 5
        broker.get()                                                  # 두 번째부터는 다시 복사하지 않음
        assert C.read_json(broker.MOCK_ACCOUNT)["positions"]["005930"]["qty"] == 5
        assert _digest(real) == before                                # 실제 저장소 파일은 그대로
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        C.WORK, C.POSITIONS = old_work


def test_shadow_off_without_env():
    old = {k: os.environ.get(k) for k in ("MODE", "SHADOW_OF")}
    try:
        os.environ["MODE"] = "mock"
        os.environ.pop("SHADOW_OF", None)
        import shadow
        assert not shadow.active()
        os.environ.update(MODE="live", SHADOW_OF=tempfile.mkdtemp())
        assert not shadow.active()   # live 모드에선 절대 켜지지 않음
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_shadow_yields_after_real_failure():
    tmp = tempfile.mkdtemp()
    real, _ = _real(tmp)
    old = {k: os.environ.get(k) for k in ("MODE", "SHADOW_OF")}
    try:
        os.environ.update(MODE="mock", SHADOW_OF=real)
        import shadow
        runs = os.path.join(real, "agent", "work", "runs.jsonl")
        with open(runs, "w", encoding="utf-8") as f:
            f.write(json.dumps({"time": C.stamp(), "kind": "decide", "ok": True}) + "\n")
        assert shadow.real_struggling() is None
        with open(runs, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": C.stamp(), "kind": "decide", "ok": False, "note": "usage limit"}) + "\n")
        assert "실패" in shadow.real_struggling()
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
