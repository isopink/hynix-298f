"""
그림자 운영 (11-08 S.Lee): 온톨로지 버전을 실제 매매 옆에서 가상 계좌(mock)로 나란히 돌려 비교.

agent/.env 에 MODE=mock, GIT_PUSH=0, SHADOW_OF=<실제 저장소 경로> 를 두면 켜짐.
- 키움을 새로 부르지 않음: 장중 순위 원문은 실제 시스템이 방금 받은 work/rank_raw/ 를,
  현재가는 실제 시스템의 work/quotes.json · 브리핑 · live/last_snapshot.json 을 읽음 (없을 때만 pykrx).
- 첫 실행 때 가상 계좌를 실제 계좌(현금·보유 종목·평단)와 손절·익절 기록으로 시작.
- 실제 저장소의 파일은 읽기만 함.
"""
import os
import shutil
import time
from datetime import datetime

import common as C

RANK_MAX_AGE = 20 * 60     # 실제 순위 원문이 이보다 오래됐으면 쓰지 않음 (그 회차는 직전 후보 유지)
QUOTE_MAX_AGE = 5 * 60


def real_root():
    p = os.environ.get("SHADOW_OF", "").strip()
    return p if p and os.path.isdir(p) and os.path.abspath(p) != os.path.abspath(C.ROOT) else None


def active():
    return C.mode() == "mock" and real_root() is not None


def _real(*parts):
    return os.path.join(real_root(), *parts)


def _age(stamp):
    """C.stamp() 형식 'YYYY-MM-DD HH:MM' → 지금까지 초 (못 읽으면 아주 큰 값)."""
    try:
        t = datetime.strptime(stamp[:16], "%Y-%m-%d %H:%M").replace(tzinfo=C.KST)
        return (C.now() - t).total_seconds()
    except Exception:  # noqa: BLE001
        return 1e9


def rank_response(api, body):
    """실제 시스템이 방금 받은 순위 원문 중 같은 API·같은 조건을 돌려줌. 오래됐거나 없으면 오류 (직전 후보 유지 경로로 감)."""
    d = _real("agent", "work", "rank_raw")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            x = C.read_json(os.path.join(d, f)) or {}
            if x.get("api") == api and x.get("body") == body and _age(x.get("time", "")) <= RANK_MAX_AGE:
                return x["response"]
    raise RuntimeError(f"그림자: 실제 시스템의 {api} 순위 원문이 없거나 {RANK_MAX_AGE // 60}분보다 오래됨")


def real_quote(code):
    """실제 시스템이 본 최근 가격 (원, 출처). 없으면 (None, None)."""
    q = (C.read_json(_real("agent", "work", "quotes.json"), {}) or {}).get(code)
    if q and q.get("price") and time.time() - q.get("ts", 0) <= QUOTE_MAX_AGE:
        return q["price"], q.get("change"), "shadow:real_quotes"
    snap = C.read_json(_real("live", "last_snapshot.json")) or {}
    if time.time() - snap.get("epoch", 0) <= QUOTE_MAX_AGE:
        for h in snap.get("holdings", []):
            if h.get("code") == code and h.get("price"):
                return h["price"], None, "shadow:real_snapshot"
    b = C.read_json(_real("agent", "work", "briefing.json")) or {}
    if b.get("asof") and _age(C.today().isoformat() + " " + (b.get("intraday") or {}).get("time", "00:00")) <= QUOTE_MAX_AGE * 3:
        for x in b.get("candidates", []) + b.get("holdings", []):
            if x.get("code") == code and x.get("price"):
                return x["price"], x.get("chg"), "shadow:real_briefing"
    return None, None, None


def seed(mock_account_path):
    """가상 계좌가 없으면 실제 계좌로 시작 (현금·보유 수량·평단 + 손절·익절·진입일 기록)."""
    if os.path.exists(mock_account_path):
        return None
    acc = C.read_json(_real("agent", "work", "account.json")) or {}
    if not acc.get("holdings") and acc.get("cash") is None:
        return None
    state = {"cash": acc.get("cash", 0), "positions": {h["code"]: {"name": h["name"], "qty": h["qty"], "avg_price": h["avg_price"]}
                                                     for h in acc.get("holdings", []) if h.get("qty")},
             "seeded_from": real_root(), "seeded_at": C.now().isoformat(timespec="seconds"), "seed_total": acc.get("total")}
    C.write_json(mock_account_path, state)
    if not os.path.exists(C.POSITIONS) and os.path.exists(_real("agent", "work", "positions.json")):
        shutil.copyfile(_real("agent", "work", "positions.json"), C.POSITIONS)
    C.journal("shadow_seed", total=acc.get("total"), cash=acc.get("cash"), holdings=len(state["positions"]))
    return state


def real_struggling(window_min=60):
    """실제 시스템이 최근 1시간 안에 실패했으면 이유 문자열 (사용 한도·시간 초과 등). 그림자는 그 동안 쉬어 실제 매매에 한도를 양보함."""
    path = _real("agent", "work", "runs.jsonl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            tail = f.readlines()[-30:]
    except OSError:
        return None
    import json
    for line in reversed(tail):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if _age(r.get("time", "")) > window_min * 60:
            break
        if not r.get("ok", True):
            return f"실제 시스템 {r.get('time')} {r.get('kind')} 실패 ({str(r.get('note', ''))[:60]}) 뒤 {window_min}분 쉼"
    return None


EQUITY = os.path.join(C.WORK, "shadow_equity.jsonl")   # 실제 시스템 logger 가 읽어 docs/data/shadow.json 으로 올림


def record_equity(note=""):
    """그림자(가상 계좌)와 실제 계좌의 총자산을 같은 시각에 한 줄씩 남김."""
    import broker
    acc = broker.get().account()
    real = C.read_json(_real("agent", "work", "account.json")) or {}
    snap = C.read_json(_real("live", "last_snapshot.json")) or {}
    real_total = snap.get("total") if time.time() - snap.get("epoch", 0) <= QUOTE_MAX_AGE else real.get("total")
    row = {"time": C.stamp(), "total": acc.get("total"), "cash": acc.get("cash"), "real_total": real_total,
           "holdings": [{"code": h["code"], "name": h["name"], "qty": h["qty"], "value": h.get("value"), "pnl_pct": h.get("pnl_pct")}
                        for h in acc.get("holdings", [])], "note": note[:40]}
    C.append_jsonl(EQUITY, row)
    return row
