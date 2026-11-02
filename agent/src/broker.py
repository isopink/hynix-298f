"""
계좌 조회·현재가·주문. MODE 에 따라 둘 중 하나를 씁니다.

- mock : work/mock_account.json 가상 계좌. 가격은 pykrx 최근 시세, 주문은 즉시 체결로 가정
- live : 키움 REST API (모의투자 서버). 토큰·잔고 조회는 live/snapshot.py 코드를 그대로 씀

키움 호출은 한 프로세스에서 최소 0.5초 간격 (잔고 루프와 합쳐도 초당 4회 이하).
"""
import os
import sys
import time

import common as C

MOCK_ACCOUNT = os.path.join(C.WORK, "mock_account.json")
QUOTES = os.path.join(C.WORK, "quotes.json")   # 최근 현재가 (Hook이 키움을 다시 부르지 않도록)


def save_account(acc):
    acc["ts"] = C.stamp()
    C.write_json(C.ACCOUNT, acc)
    ds = os.path.join(C.WORK, "day_start.json")
    if (C.read_json(ds, {}) or {}).get("date") != C.today().isoformat():
        C.write_json(ds, {"date": C.today().isoformat(), "total": acc["total"]})
    return acc


def cache_quote(code, price, change=None):
    q = C.read_json(QUOTES, {}) or {}
    q[code] = {"price": price, "ts": time.time(), "change": change}   # change = 오늘 등락률 (전일 종가 대비, 0.05 = +5%)
    C.write_json(QUOTES, q)


def cached_quote(code, max_age=600):
    q = (C.read_json(QUOTES, {}) or {}).get(code)
    return q["price"] if q and time.time() - q["ts"] < max_age else None


def cached_change(code, max_age=600):
    q = (C.read_json(QUOTES, {}) or {}).get(code)
    return q.get("change") if q and time.time() - q["ts"] < max_age else None


def build_account(cash, holdings):
    stock = sum(h["value"] for h in holdings)
    return {"total": round(cash + stock), "cash": round(cash), "stock_value": round(stock), "holdings": holdings}


# ---------------- 가상 계좌 ----------------
class MockBroker:
    name = "mock"

    def __init__(self):
        from pykrx import stock  # 무거워서 mock 일 때만 불러옴
        self.stock = stock
        self.state = C.read_json(MOCK_ACCOUNT) or {"cash": C.risk_limits()["initial_capital"], "positions": {}}

    def _save(self):
        C.write_json(MOCK_ACCOUNT, self.state)

    def quote(self, code):
        p = cached_quote(code, 60)
        if p:
            return p
        end = C.today()
        from datetime import timedelta
        df = self.stock.get_market_ohlcv((end - timedelta(days=14)).strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        p = int(df["종가"].iloc[-1]) if len(df) else 0
        chg = round(p / float(df["종가"].iloc[-2]) - 1, 4) if len(df) > 1 and df["종가"].iloc[-2] else None
        cache_quote(code, p, chg)
        return p

    def quote_info(self, code):
        p = self.quote(code)
        return {"price": p, "change": cached_change(code)}

    def account(self):
        hs = []
        for code, pos in self.state["positions"].items():
            px = self.quote(code)
            hs.append({"code": code, "name": pos["name"], "qty": pos["qty"], "avg_price": round(pos["avg_price"]),
                       "price": px, "value": px * pos["qty"], "pnl_pct": round(px / pos["avg_price"] - 1, 4)})
        return save_account(build_account(self.state["cash"], hs))

    def order(self, code, name, side, qty):
        p = C.params()["costs"]
        px = self.quote(code)
        pos = self.state["positions"].get(code)
        if side == "매수":
            cost = px * qty * (1 + p["fee_rate"])
            if cost > self.state["cash"]:
                return {"ok": False, "msg": "가상 계좌 현금 부족"}
            self.state["cash"] -= cost
            if pos:
                pos["avg_price"] = (pos["avg_price"] * pos["qty"] + px * qty) / (pos["qty"] + qty)
                pos["qty"] += qty
            else:
                self.state["positions"][code] = {"name": name, "qty": qty, "avg_price": px}
        else:
            if not pos or pos["qty"] < qty:
                return {"ok": False, "msg": "보유 수량 부족"}
            self.state["cash"] += px * qty * (1 - p["fee_rate"] - p["sell_tax_rate"])
            pos["qty"] -= qty
            if pos["qty"] == 0:
                del self.state["positions"][code]
        self._save()
        return {"ok": True, "price": px, "qty": qty, "order_no": f"MOCK-{int(time.time())}", "filled": True}


# ---------------- 키움 REST ----------------
class KiwoomBroker:
    """주의: 주문(kt10000/kt10001)·현재가(ka10001) 필드는 대회 계좌 발급 후 실제 응답으로 확인 필요."""
    name = "live"

    def __init__(self):
        sys.path.insert(0, C.LIVE)
        import snapshot as S  # live/snapshot.py: load_env, get_token, post_json, get_balance, num
        self.S = S
        self.env = S.load_env(os.path.join(C.LIVE, ".env"))
        self.base = self.env["KIWOOM_BASE"]
        self._last = 0.0

    def _call(self, path, api_id, body):
        # 모의서버는 API마다 초당 1회 ("유량=1"). 넘기면 429이고, 대회에서는 이용 제한 위반이라 1.1초 간격을 지킴
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        token = self.S.get_token(self.env)
        hdr = {"api-id": api_id, "authorization": "Bearer " + token}
        try:
            res, _ = self.S.post_json(self.base + path, body, hdr)
        except RuntimeError as e:   # 잔고 루프 등 다른 프로세스와 같은 초에 겹치면 429 → 한 번만 쉬었다 재시도
            if "HTTP 429" not in str(e):
                raise
            time.sleep(2)
            self._last = time.time()
            res, _ = self.S.post_json(self.base + path, body, hdr)
        if res.get("return_code", 0) not in (0, "0"):
            raise RuntimeError(f"{api_id} 실패: {res.get('return_msg')}")
        return res

    def quote(self, code):
        p = cached_quote(code, 30)
        if p:
            return p
        res = self._call("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})
        p = abs(self.S.num(res.get("cur_prc")))
        cache_quote(code, p, round(float(res.get("flu_rt") or 0) / 100, 4))   # flu_rt = 등락률 %
        return p

    def quote_info(self, code):
        """현재가 + 오늘 등락률. 잔고 조회로 캐시된 가격엔 등락률이 없으므로 그땐 새로 조회."""
        q = (C.read_json(QUOTES, {}) or {}).get(code) or {}
        if q.get("change") is None or time.time() - q.get("ts", 0) > 30:
            q = {**q, "ts": 0}
            C.write_json(QUOTES, {**(C.read_json(QUOTES, {}) or {}), code: q})
        p = self.quote(code)
        return {"price": p, "change": cached_change(code)}

    def _balance(self):
        """kt00018 잔고. _call 을 거치지 않으므로 여기서도 1.1초 간격과 429 한 번 재시도를 지킴."""
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        try:
            return self.S.get_balance(self.env, self.S.get_token(self.env))
        except RuntimeError as e:   # 잔고 루프(snapshot.py)도 kt00018 을 부르므로 같은 초에 겹칠 수 있음
            if "HTTP 429" not in str(e):
                raise
            time.sleep(2)
            self._last = time.time()
            return self.S.get_balance(self.env, self.S.get_token(self.env))

    def account(self):
        snap = self._balance()
        cash = snap["total"] - snap["stock_eval"]  # 추정예탁자산 − 주식평가
        if "mockapi" not in self.base:  # 모의투자 서버는 주문가능금액 조회(kt00001)를 거절함 (키움 SETUP-MCP.md)
            try:
                res = self._call("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
                cash = self.S.num(res.get("ord_alow_amt"))
            except Exception:  # noqa: BLE001  실패하면 위 추정값 사용
                pass
        hs = [{k: h[k] for k in ("code", "name", "qty", "avg_price", "price", "value", "pnl_pct")} for h in snap["holdings"]]
        for h in hs:
            cache_quote(h["code"], h["price"])
        return save_account(build_account(cash, hs))

    def order(self, code, name, side, qty):
        api = "kt10000" if side == "매수" else "kt10001"
        before = next((h["qty"] for h in (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", []) if h["code"] == code), 0)
        res = self._call("/api/dostk/ordr", api, {
            "dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(qty),
            "ord_uv": "", "trde_tp": "3", "cond_uv": "",   # 3 = 시장가
        })
        time.sleep(2)
        try:
            acc = self.account()
        except Exception:  # noqa: BLE001  주문은 이미 나갔으므로 확인 조회가 실패해도 체결로 기록 (다음 조회 때 바로잡힘)
            return {"ok": True, "order_no": res.get("ord_no", ""), "price": self.quote(code), "qty": qty, "filled": None}
        after = next((h for h in acc["holdings"] if h["code"] == code), None)
        moved = abs((after["qty"] if after else 0) - before)
        px = after["avg_price"] if side == "매수" and after and not before else (after["price"] if after else self.quote(code))
        return {"ok": True, "order_no": res.get("ord_no", ""), "price": px, "qty": moved or qty, "filled": moved > 0}


def get():
    return KiwoomBroker() if C.mode() == "live" else MockBroker()
