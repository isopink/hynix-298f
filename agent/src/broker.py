"""
계좌 조회·현재가·주문. MODE 에 따라 둘 중 하나를 씁니다.

- mock : work/mock_account.json 가상 계좌. 가격은 pykrx 최근 시세, 주문은 즉시 체결로 가정
- live : 키움 REST API (모의투자 서버). 토큰·잔고 조회는 live/snapshot.py 코드를 그대로 씀

키움 호출은 한 프로세스에서 최소 0.5초 간격 (잔고 루프와 합쳐도 초당 4회 이하).
"""
import copy
import contextvars
import math
import os
import sys
import time

import common as C
import execution_trace as E

_ORDER_ATTEMPT = contextvars.ContextVar("broker_order_attempt", default=None)


def _audit(kind, **fields):
    try:
        return E.record(kind, **fields)
    except Exception as exc:
        try:
            import judgment_coverage as JC
            JC.recording_error("broker:" + kind, exc)
        except Exception:
            pass
        return {"recording_status": "recording_error"}


def _with_execution_quality(result):
    result.setdefault("execution_quality", {
        "balance_inference": "balance_delta_inference", "simulated": "simulated",
    }.get(result.get("execution_confirmation"), "unknown"))
    return result


MOCK_ACCOUNT = os.path.join(C.WORK, "mock_account.json")
QUOTES = os.path.join(C.WORK, "quotes.json")   # 최근 현재가 (Hook이 키움을 다시 부르지 않도록)


def save_account(acc):
    acc["ts"] = C.stamp()
    C.write_json(C.ACCOUNT, acc)
    ds = os.path.join(C.WORK, "day_start.json")
    if (C.read_json(ds, {}) or {}).get("date") != C.today().isoformat():
        C.write_json(ds, {"date": C.today().isoformat(), "total": acc["total"]})
    return acc


def cache_quote(code, price, change=None, source="broker:unspecified", observed_at=None, capture_metadata=None):
    q = C.read_json(QUOTES, {}) or {}
    q[code] = {"price": price, "ts": time.time(), "change": change,
               "source": source, "observed_at": observed_at, "available_at": C.now().isoformat(timespec="microseconds")}
    if capture_metadata is not None:
        try:
            import portfolio_capture as PC
            meta = capture_metadata
            record = PC.record_quote(code, price, source=meta.get('source') or source,
                provider_observed_at=meta.get('provider_observed_at'), price_basis=meta.get('price_basis'),
                executable_qty=meta.get('executable_qty'), capacity_source=meta.get('capacity_source'),
                provenance=meta.get('provenance', 'provider_response'), received_at=meta.get('received_at'))
            q[code].update({k: record.get(k) for k in ('observation_id', 'price_basis', 'executable_qty',
                'capacity_source', 'time_basis', 'provider_observed_at', 'capture_status', 'provenance')})
            q[code]['market_observed_at'] = record.get('observed_at')
            q[code]['observed_at'] = record.get('provider_observed_at')
            q[code]['available_at'] = record.get('available_at')
        except Exception:
            q[code]['capture_status'] = 'recording_error'
    C.write_json(QUOTES, q)


def cached_quote(code, max_age=600):
    q = (C.read_json(QUOTES, {}) or {}).get(code)
    return q["price"] if q and time.time() - q["ts"] < max_age else None


def cached_change(code, max_age=600):
    q = (C.read_json(QUOTES, {}) or {}).get(code)
    return q.get("change") if q and time.time() - q["ts"] < max_age else None


def quote_metadata(code):
    q = (C.read_json(QUOTES, {}) or {}).get(code) or {}
    return {k: q.get(k) for k in ("source", "observed_at", "available_at", "observation_id",
        "market_observed_at", "price_basis", "executable_qty", "capacity_source", "time_basis",
        "provider_observed_at", "capture_status", "provenance")}


def build_account(cash, holdings):
    stock = sum(h["value"] for h in holdings)
    return {"total": round(cash + stock), "cash": round(cash), "stock_value": round(stock), "holdings": holdings}


class BrokerRejection(RuntimeError):
    def __init__(self, api_id, response):
        self.response = response
        super().__init__(f"{api_id} 실패: {response.get('return_msg')}")


# ---------------- 가상 계좌 ----------------
class MockBroker:
    name = "mock"
    supports_dispatch_guard = True

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
        cache_quote(code, p, chg, "pykrx:mock_daily", str(df.index[-1].date()) if len(df) else None)
        return p

    def quote_info(self, code):
        p = self.quote(code)
        return {"price": p, "change": cached_change(code), **quote_metadata(code)}

    def account(self):
        hs = []
        for code, pos in self.state["positions"].items():
            px = self.quote(code)
            hs.append({"code": code, "name": pos["name"], "qty": pos["qty"], "avg_price": round(pos["avg_price"]),
                       "price": px, "value": px * pos["qty"], "pnl_pct": round(px / pos["avg_price"] - 1, 4)})
        acc = build_account(self.state["cash"], hs)
        acc.update(complete=True, captured_at=C.now().isoformat(), capture_metadata={
            'source': 'local_mock_account', 'pagination_complete': True, 'required_fields_present': True,
            'provenance': 'simulated', 'received_at': C.now().isoformat(), 'completeness_status': 'complete'})
        return save_account(acc)

    def order(self, code, name, side, qty, *, order_attempt_id=None, dispatch_payload=None):
        payload = {**(dispatch_payload or {}), "code": code, "side": side, "qty": qty}
        def sender():
            return _with_execution_quality(self._order_once(code, name, side, qty, order_attempt_id))
        result = E.dispatch_once(E.account_scope(self), order_attempt_id, payload, sender)
        return _with_execution_quality(result)

    def _order_once(self, code, name, side, qty, order_attempt_id):
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
        number = "MOCK-" + order_attempt_id
        _audit("simulated_execution", order_attempt_id=order_attempt_id, order_no=number,
                 code=code, side=side, qty=qty, price=px, confirmation="simulated", source="MockBroker")
        return {"ok": True, "price": px, "qty": qty, "order_no": number, "filled": True,
                "broker_acknowledgment": "simulated", "execution_confirmation": "simulated",
                "confirmed_qty": None, "simulated_qty": qty}


# ---------------- 키움 REST ----------------
class KiwoomBroker:
    """주의: 주문(kt10000/kt10001)·현재가(ka10001) 필드는 대회 계좌 발급 후 실제 응답으로 확인 필요."""
    name = "live"
    supports_dispatch_guard = True

    def __init__(self):
        sys.path.insert(0, C.LIVE)
        import snapshot as S  # live/snapshot.py: load_env, get_token, post_json, get_balance, num
        self.S = S
        self.env = S.load_env(os.path.join(C.LIVE, ".env"))
        self.base = self.env["KIWOOM_BASE"]
        self._last = 0.0

    def _call(self, path, api_id, body):
        """Legacy body-only contract; only read requests may retry on HTTP 429."""
        result, _ = self._call_with_headers(path, api_id, body)
        return result

    def _call_with_headers(self, path, api_id, body, continuation=None, deadline=None):
        mutation = api_id in ("kt10000", "kt10001")
        attempt_id = _ORDER_ATTEMPT.get() if mutation else None
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            if deadline is not None and time.monotonic() + wait >= deadline:
                raise TimeoutError("execution query budget exhausted")
            time.sleep(wait)
        self._last = time.time()
        token = self.S.get_token(self.env)
        hdr = {"api-id": api_id, "authorization": "Bearer " + token}
        for key in ("cont-yn", "next-key"):
            if continuation and key in continuation:
                hdr[key] = continuation[key]
        if mutation:
            _audit("broker_request", order_attempt_id=attempt_id, api=api_id,
                     path=path, request=copy.deepcopy(body), source="kiwoom:REST")

        def post():
            kwargs = {}
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("execution query budget exhausted")
                kwargs["timeout"] = min(10, remaining)
            return self.S.post_json(self.base + path, body, hdr, **kwargs)
        try:
            try:
                res, response_headers = post()
            except RuntimeError as exc:
                if mutation or "HTTP 429" not in str(exc):
                    raise
                if deadline is not None and time.monotonic() + 2 >= deadline:
                    raise TimeoutError("execution query budget exhausted") from exc
                time.sleep(2)
                self._last = time.time()
                res, response_headers = post()
        except Exception as exc:
            if mutation:
                _audit("broker_transport_error", order_attempt_id=attempt_id, api=api_id,
                         submission_status="unknown", error=f"{type(exc).__name__}: {exc}")
            raise
        if mutation:
            _audit("broker_response", order_attempt_id=attempt_id, api=api_id,
                     response=copy.deepcopy(res), received_at=C.now().isoformat(),
                     order_no=str(res.get("ord_no") or res.get("ordr_no") or res.get("ord_num") or "") or None,
                     acknowledgment="accepted" if res.get("return_code", 0) in (0, "0") else "rejected")
        if res.get("return_code", 0) not in (0, "0"):
            raise BrokerRejection(api_id, res)
        return res, {str(k).lower(): v for k, v in (response_headers or {}).items()}

    def query_order_executions(self, order_date, *, max_pages=20, max_seconds=30):
        """kt00009 read-only pages. Absence is never proof of rejection/unfilled."""
        body = {"ord_dt": str(order_date).replace("-", ""), "stk_bond_tp": "1", "mrkt_tp": "0",
                "sell_tp": "0", "qry_tp": "0", "stk_cd": "", "fr_ord_no": "", "dmst_stex_tp": "KRX"}
        deadline = time.monotonic() + max_seconds
        pages, rows, seen = [], [], set()
        continuation = {}
        reason, complete = "page_limit", False
        for _ in range(max_pages):
            if time.monotonic() >= deadline:
                reason = "time_limit"
                break
            try:
                result, headers = self._call_with_headers("/api/dostk/acnt", "kt00009", body,
                                                          continuation=continuation, deadline=deadline)
            except Exception as exc:
                reason = "time_limit" if isinstance(exc, TimeoutError) else "query_error"
                pages.append({"request": copy.deepcopy(body), "continuation": continuation,
                              "received_at": C.now().isoformat(), "error": f"{type(exc).__name__}: {exc}"})
                break
            page = {"request": copy.deepcopy(body), "continuation": copy.deepcopy(continuation),
                    "received_at": C.now().isoformat(), "response": result,
                    "headers": {k: headers.get(k) for k in ("cont-yn", "next-key", "api-id")}}
            pages.append(page)
            values = result.get("acnt_ord_cntr_prst_array")
            if not isinstance(values, list):
                reason = "invalid_response"
                break
            rows.extend(values)
            if str(headers.get("cont-yn", "N")).upper() != "Y":
                complete, reason = True, None
                break
            key = headers.get("next-key")
            if not key or key in seen:
                reason = "repeated_or_missing_page_key"
                break
            seen.add(key)
            continuation = {"cont-yn": "Y", "next-key": key}
        return {"api": "kt00009", "order_date": str(order_date), "rows": rows, "pages": pages,
                "complete": complete, "reason": reason, "source": "kiwoom:kt00009"}

    def quote(self, code):
        p = cached_quote(code, 30)
        if p:
            return p
        res = self._call("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})
        p = abs(self.S.num(res.get("cur_prc")))
        # cur_prc is the received current quote, not an adjusted historical bar.
        # ka10001 supplies no executable capacity; never substitute volume.
        metadata = {'source': 'kiwoom:ka10001.cur_prc', 'price_basis': 'unadjusted',
                    **(res.get('capture_metadata') or {})}
        cache_quote(code, p, round(float(res.get("flu_rt") or 0) / 100, 4), "kiwoom:ka10001",
                    capture_metadata=metadata)   # flu_rt = 등락률 %
        return p

    def quote_info(self, code):
        """현재가 + 오늘 등락률. 잔고 조회로 캐시된 가격엔 등락률이 없으므로 그땐 새로 조회."""
        q = (C.read_json(QUOTES, {}) or {}).get(code) or {}
        if q.get("change") is None or time.time() - q.get("ts", 0) > 30:
            q = {**q, "ts": 0}
            C.write_json(QUOTES, {**(C.read_json(QUOTES, {}) or {}), code: q})
        p = self.quote(code)
        return {"price": p, "change": cached_change(code), **quote_metadata(code)}

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
        balance_received_at = C.now().isoformat()
        if _ORDER_ATTEMPT.get():
            _audit("broker_balance_snapshot", order_attempt_id=_ORDER_ATTEMPT.get(),
                   response=copy.deepcopy(snap), source="kiwoom:kt00018",
                   available_at=C.now().isoformat())
        cash = snap["total"] - snap["stock_eval"]  # 추정예탁자산 − 주식평가
        cash_metadata = {'status': 'estimate', 'source': 'kiwoom:kt00018.total_minus_stock_eval',
                         'method': 'total_minus_stock_eval', 'value': cash, 'received_at': balance_received_at,
                         'inputs': {'total': snap['total'], 'stock_eval': snap['stock_eval']}}
        if "mockapi" not in self.base:  # 모의투자 서버는 주문가능금액 조회(kt00001)를 거절함 (키움 SETUP-MCP.md)
            try:
                res = self._call("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
                cash = self.S.num(res.get("ord_alow_amt"))
                raw_cash = res.get('ord_alow_amt')
                try:
                    valid_cash = (type(raw_cash) is not bool and raw_cash not in (None, '')
                                  and math.isfinite(float(str(raw_cash).replace(',', ''))))
                except (ValueError, TypeError):
                    valid_cash = False
                cash_metadata = {'status': 'observed' if valid_cash else 'unknown',
                    'source': 'kiwoom:kt00001.ord_alow_amt', 'method': 'order_available_amount',
                    'value': cash, 'raw_value': raw_cash, 'received_at': C.now().isoformat()}
            except Exception:  # noqa: BLE001  실패하면 위 추정값 사용
                cash_metadata['reason'] = 'order_available_amount_request_failed'
        metadata = snap.get('capture_metadata') if isinstance(snap.get('capture_metadata'), dict) else {}
        synthetic_cash = metadata.get('cash_validation') if isinstance(metadata.get('cash_validation'), dict) else {}
        if (metadata.get('provenance') == 'synthetic' and synthetic_cash.get('status') == 'confirmed_synthetic'
                and type(synthetic_cash.get('value')) in (int, float) and synthetic_cash['value'] == cash
                and synthetic_cash.get('source')):
            cash_metadata.update(status='confirmed_synthetic', fixture_validation=copy.deepcopy(synthetic_cash))
        hs = [{k: h[k] for k in ("code", "name", "qty", "avg_price", "price", "value", "pnl_pct")} for h in snap["holdings"]]
        for h in hs:
            rows = metadata.get('holding_prices') if isinstance(metadata.get('holding_prices'), list) else []
            original = next((r for r in rows if isinstance(r, dict) and r.get('code') == h['code']), {})
            cache_quote(h["code"], h["price"], source='kiwoom:kt00018.cur_prc', capture_metadata={
                'source': original.get('source') or metadata.get('source') or 'kiwoom:kt00018.cur_prc',
                'received_at': original.get('received_at') or metadata.get('received_at') or balance_received_at,
                'provider_observed_at': original.get('provider_observed_at', metadata.get('provider_observed_at')),
                'executable_qty': original.get('executable_qty'), 'capacity_source': original.get('capacity_source'),
                'price_basis': 'unadjusted', 'provenance': metadata.get('provenance', 'provider_response')})
        acc = build_account(cash, hs)
        try:
            import portfolio_capture as PC
            acc.update(PC.account_metadata(snap, 'kiwoom:kt00018'))
            acc['capture_metadata']['cash'] = cash_metadata
            acc['complete'] = acc['complete'] and cash_metadata['status'] in ('observed', 'confirmed_synthetic')
            acc['capture_metadata']['completeness_status'] = 'complete' if acc['complete'] else 'unknown'
        except Exception:
            acc['capture_metadata'] = {'completeness_status': 'recording_error'}
        return save_account(acc)

    def order(self, code, name, side, qty, *, order_attempt_id=None, dispatch_payload=None):
        payload = {**(dispatch_payload or {}), "code": code, "side": side, "qty": qty}
        def sender():
            return _with_execution_quality(self._order_once(code, name, side, qty, order_attempt_id))
        result = E.dispatch_once(E.account_scope(self), order_attempt_id, payload, sender)
        return _with_execution_quality(result)

    def _order_once(self, code, name, side, qty, order_attempt_id):
        token = _ORDER_ATTEMPT.set(order_attempt_id)
        try:
            return self._perform_order(code, name, side, qty, order_attempt_id)
        finally:
            _ORDER_ATTEMPT.reset(token)

    def _perform_order(self, code, name, side, qty, order_attempt_id):
        api = "kt10000" if side == "매수" else "kt10001"
        previous = C.read_json(C.ACCOUNT, {}) or {}
        before = next((h["qty"] for h in previous.get("holdings", []) if h["code"] == code), 0)
        _audit("pre_order_balance", order_attempt_id=order_attempt_id, code=code,
                 account=previous, effective_qty=before, source="cached_account")
        try:
            res = self._call("/api/dostk/ordr", api, {
                "dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(qty),
                "ord_uv": "", "trde_tp": "3", "cond_uv": "",   # 3 = 시장가
            })
        except BrokerRejection as exc:
            return {"ok": False, "submission_status": "rejected", "broker_acknowledgment": "rejected",
                    "response": exc.response, "msg": str(exc)}
        # kt10000/kt10001 응답 필드가 문서와 다를 수 있어 원문을 그대로 남김 (응답에는 토큰·키가 없음)
        order_no = str(res.get("ord_no") or res.get("ordr_no") or res.get("ord_num") or "")
        try:
            C.append_jsonl(os.path.join(C.WORK, "orders.jsonl"),
                           {"time": C.stamp(), "run": os.environ.get("RUN_ID", ""), "api": api, "code": code,
                            "side": side, "qty": qty, "order_attempt_id": order_attempt_id, "response": res})
        except Exception as exc:
            _audit("broker_recording_error", order_attempt_id=order_attempt_id,
                   storage="orders.jsonl", order_no=order_no, error=f"{type(exc).__name__}: {exc}")
            return {"ok": False, "order_no": order_no, "broker_acknowledgment": "accepted",
                    "submission_status": "submission_unknown", "recording_status": "recording_error",
                    "confirmed_qty": None, "unconfirmed_qty": qty, "response": res,
                    "execution_confirmation": "unknown", "error": f"orders.jsonl: {exc}"}
        # 시장가도 나눠 체결될 수 있음 (11-03 현대글로비스: 2초 뒤 확인 땐 3주, 실제 잔고는 14주 → 3주로 기록됨)
        # → 주문 수량이 다 보일 때까지 2초 간격으로 최대 5번 잔고 확인. 그래도 덜 보이면 logger 가 잔고로 바로잡음
        acc = None
        observations = []
        for _ in range(5):
            time.sleep(2)
            try:
                acc = self.account()
            except Exception as exc:  # The legacy inference remains separate from confirmed executions.
                observation = {"status": "unknown", "source": "kiwoom:kt00018",
                               "available_at": C.now().isoformat(), "error": type(exc).__name__}
                observations.append(observation)
                _audit("balance_observation", order_attempt_id=order_attempt_id, observation=observation)
                continue
            after = next((h for h in acc["holdings"] if h["code"] == code), None)
            delta = (after["qty"] if after else 0) - before
            moved = abs(delta)  # preserve the existing engine's effective value
            attribution = delta if side == "매수" else -delta
            observation = {"status": "observed", "source": "kiwoom:kt00018", "available_at": C.now().isoformat(),
                           "before_qty": before if isinstance(previous.get("holdings"), list) else None,
                           "after_qty": after["qty"] if after else 0, "account": acc,
                           "observed_balance_delta": delta if isinstance(previous.get("holdings"), list) else None,
                           "attributed_estimate_qty": min(qty, attribution) if isinstance(previous.get("holdings"), list) and 0 <= attribution <= qty else None,
                           "attribution_status": "unknown" if not isinstance(previous.get("holdings"), list)
                                                 else "estimate" if 0 <= attribution <= qty else "ambiguous",
                           "legacy_effective_qty": moved, "confirmation": "balance_inference"}
            observations.append(observation)
            _audit("balance_observation", order_attempt_id=order_attempt_id, observation=observation)
            if moved >= qty:
                break
        if acc is None:
            return {"ok": True, "order_no": order_no, "price": self.quote(code), "qty": qty, "filled": None,
                    "broker_acknowledgment": "accepted", "confirmed_qty": None, "unconfirmed_qty": qty,
                    "execution_confirmation": "unknown", "execution_observations": observations}
        px = after["avg_price"] if side == "매수" and after and not before else (after["price"] if after else self.quote(code))
        return {"ok": True, "order_no": order_no, "price": px, "qty": moved or qty, "filled": moved > 0,
                "broker_acknowledgment": "accepted", "confirmed_qty": None, "unconfirmed_qty": qty,
                "execution_confirmation": "balance_inference", "execution_observations": observations}


class ShadowBroker(MockBroker):
    """11-08 그림자 운영: 가상 계좌 + 실제 시스템이 받은 순위 원문·현재가 재사용 (키움을 새로 부르지 않음). src/shadow.py"""
    name = "mock"
    replays_rank = True

    def __init__(self):
        import shadow
        self.shadow = shadow
        shadow.seed(MOCK_ACCOUNT)
        super().__init__()

    def _call(self, path, api_id, body):   # intraday.fetch 가 순위 API 를 부르는 자리
        return self.shadow.rank_response(api_id, body)

    def quote(self, code):
        p = cached_quote(code, 60)
        if p:
            return p
        px, chg, src = self.shadow.real_quote(code)
        if px:
            cache_quote(code, px, chg, src, None)
            return px
        return super().quote(code)


def get():
    if C.mode() == "live":
        return KiwoomBroker()
    import shadow
    return ShadowBroker() if shadow.active() else MockBroker()
