"""
키움 모의투자 잔고를 조회해서 대시보드(Supabase)에 올리는 스크립트.

- 조회만 합니다. 주문은 절대 하지 않습니다.
- 키움 키는 이 PC의 .env 에만 있고, 사이트로는 숫자만 넘어갑니다.
- 파이썬 기본 라이브러리만 사용 (pip 설치 필요 없음).

사용법
  python snapshot.py            # 지금 한 번 조회해서 올림
  python snapshot.py --loop     # 평일 08:30~15:35 동안 INTERVAL_SEC 마다 반복, 장 끝나면 종료
  python snapshot.py --dry      # 올리지 않고 조회 결과만 출력 (처음 설정 확인용)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
TOKEN_CACHE = os.path.join(HERE, ".token_cache.json")


def load_env(path=os.path.join(HERE, ".env")):
    env = {}
    if not os.path.exists(path):
        sys.exit(".env 파일이 없습니다. .env.example 을 복사해 .env 로 만들고 값을 채우세요.")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #")[0].strip().strip('"').strip("'")
            env[k.strip()] = v
    for k in ("ACCOUNT_NAME", "KIWOOM_APPKEY", "KIWOOM_SECRETKEY"):
        if not env.get(k):
            sys.exit(f".env 에 {k} 값이 비어 있습니다.")
    env.setdefault("KIWOOM_BASE", "https://mockapi.kiwoom.com")
    env.setdefault("INTERVAL_SEC", "300")
    return env


def post_json(url, body, headers=None, timeout=10):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json;charset=UTF-8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8") or "null"
            return json.loads(raw), dict(r.headers)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url}: {e.read().decode('utf-8', 'replace')[:300]}")


# ---------------- 키움 ----------------
def get_token(env):
    """au10001 접근토큰. 만료 전이면 캐시 재사용."""
    try:
        with open(TOKEN_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("appkey_tail") == env["KIWOOM_APPKEY"][-4:] and c.get("expires_dt", "") > datetime.now(KST).strftime("%Y%m%d%H%M%S"):
            return c["token"]
    except (OSError, ValueError):
        pass
    res, _ = post_json(env["KIWOOM_BASE"] + "/oauth2/token", {
        "grant_type": "client_credentials",
        "appkey": env["KIWOOM_APPKEY"],
        "secretkey": env["KIWOOM_SECRETKEY"],
    })
    if not res or not res.get("token"):
        raise RuntimeError(f"토큰 발급 실패: {res}")
    with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
        json.dump({"token": res["token"], "expires_dt": res.get("expires_dt", ""), "appkey_tail": env["KIWOOM_APPKEY"][-4:]}, f)
    return res["token"]


def num(s, as_float=False):
    """'+000000012345' / '-0000012' / '7.03' / '' → 숫자"""
    s = str(s or "").replace(",", "").strip()
    if not s or s in "+-":
        return 0.0 if as_float else 0
    return float(s) if as_float else int(float(s))


def get_balance(env, token):
    """kt00018 계좌평가잔고내역요청 (연속조회 포함)"""
    url = env["KIWOOM_BASE"] + "/api/dostk/acnt"
    body = {"qry_tp": "1", "dmst_stex_tp": "KRX"}
    head, items, cont, key = None, [], "N", ""
    for _ in range(10):
        h = {"api-id": "kt00018", "authorization": "Bearer " + token}
        if cont == "Y":
            h.update({"cont-yn": "Y", "next-key": key})
        res, rh = post_json(url, body, h)
        if res.get("return_code", 0) not in (0, "0"):
            raise RuntimeError(f"잔고 조회 실패: {res.get('return_msg')}")
        head = head or res
        items += res.get("acnt_evlt_remn_indv_tot") or []
        rh = {k.lower(): v for k, v in rh.items()}
        cont, key = rh.get("cont-yn", "N"), rh.get("next-key", "")
        if cont != "Y":
            break
        time.sleep(1.1)   # 같은 API 연속 호출은 초당 1회 (모의서버 유량 제한)
    holdings = []
    for it in items:
        qty = num(it.get("rmnd_qty"))
        if qty <= 0:
            continue
        holdings.append({
            "code": str(it.get("stk_cd", "")).lstrip("A"),
            "name": str(it.get("stk_nm", "")).strip(),
            "account": env["ACCOUNT_NAME"],
            "qty": qty,
            "avg_price": num(it.get("pur_pric")),
            "price": abs(num(it.get("cur_prc"))),
            "value": num(it.get("evlt_amt")),
            "pnl_pct": round(num(it.get("prft_rt"), True) / 100, 4),
        })
    total = num(head.get("prsm_dpst_aset_amt"))
    stock_eval = num(head.get("tot_evlt_amt"))
    return {"total": total, "stock_eval": stock_eval, "pur_amt": num(head.get("tot_pur_amt")), "holdings": holdings}


def get_kospi(env, token):
    """ka20001 업종현재가요청 (KOSPI 종합 = 001). 실패해도 전체 흐름은 계속."""
    try:
        res, _ = post_json(env["KIWOOM_BASE"] + "/api/dostk/sect",
                           {"mrkt_tp": "0", "inds_cd": "001"},
                           {"api-id": "ka20001", "authorization": "Bearer " + token})
        v = abs(num(res.get("cur_prc"), True))
        return v or None
    except Exception as e:  # noqa: BLE001
        print(f"  (KOSPI 조회 건너뜀: {e})")
        return None


# ---------------- Supabase ----------------
def push(env, snap, kospi):
    url = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/push_snapshot"
    key = env["SUPABASE_ANON_KEY"]
    post_json(url, {
        "p_secret": env["SNAPSHOT_SECRET"], "p_account": env["ACCOUNT_NAME"],
        "p_total": snap["total"], "p_stock_eval": snap["stock_eval"], "p_pur_amt": snap["pur_amt"],
        "p_holdings": snap["holdings"], "p_kospi": kospi,
    }, {"apikey": key, "Authorization": "Bearer " + key})


SHADOW_LIVE = os.path.join(os.environ.get("SHADOW_DIR") or os.path.join(os.path.dirname(os.path.dirname(HERE)), "hynix-shadow"),
                           "agent", "work", "shadow_live.json")   # 11-09 그림자 운영 감시가 1분마다 씀


def shadow_texts(dc, journal, n=140):
    """11-09 그림자(온톨로지) decision.json 은 근거를 '비공개'로 가림 → 그림자 journal 의 같은 회차 판단·체결에서 bull·bear·decision 을 채움."""
    if not dc or not dc.get("items"):
        return
    last = {}
    with open(journal, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") in ("decision", "fill") and r.get("code"):   # 가장 최근 회차 (decision.json 시각과 기록 시각이 몇 분 다름)
                last[r["code"]] = r
    for it in dc["items"]:
        r = last.get(it.get("code"))
        if r:
            for k in ("bull", "bear", "decision"):
                if r.get(k):
                    it[k] = str(r[k])[:n]


def _rj(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def shadow_now(snap):
    """11-09 그림자(SiON) 가상 계좌를 지금 가격으로 평가. 그림자 감시 루프가 멈춰도 여기서 1분마다 계산하므로 대시보드가 멈추지 않음.
    가격: 실제 잔고(방금 받은 키움 kt00018) → 실제·그림자 quotes.json(15분 안) → 평단. 키움 새 호출 없음."""
    work = os.path.dirname(SHADOW_LIVE)
    shadow_root = os.path.dirname(os.path.dirname(work))
    m = _rj(os.path.join(work, "mock_account.json"))
    if not m or "positions" not in m:
        return None
    px = {h["code"]: h["price"] for h in snap.get("holdings", []) if h.get("price")}
    now = time.time()
    for q in (os.path.join(os.path.dirname(HERE), "agent", "work", "quotes.json"), os.path.join(work, "quotes.json")):
        for c, v in (_rj(q, {}) or {}).items():
            if c not in px and v.get("price") and now - v.get("ts", 0) <= 15 * 60:
                px[c] = v["price"]
    hs = []
    for c, p in m["positions"].items():
        if not p.get("qty"):
            continue
        avg = p.get("avg_price") or 0
        price = px.get(c) or avg
        hs.append({"code": c, "name": p.get("name", c), "qty": p["qty"], "price": price, "value": price * p["qty"],
                   "pnl_pct": round(price / avg - 1, 4) if avg else None})
    st = _rj(os.path.join(shadow_root, "docs", "data", "status.json"), {}) or {}
    status = {k: st.get(k) for k in ("last_run", "last_ok", "next_run", "runs_today", "failures_today", "note")}
    dc = _rj(os.path.join(shadow_root, "docs", "data", "decision.json"), {}) or {}
    seeded = str(m.get("seeded_at", ""))[:16].replace("T", " ")
    if dc.get("time") and dc["time"] >= seeded:
        status["decision"] = {"time": dc["time"], "regime": dc.get("regime"),
                              "items": [{k: x.get(k) for k in ("code", "name", "action", "qty", "confidence", "decision")} for x in dc.get("items", [])]}
        shadow_texts(status["decision"], os.path.join(work, "journal.jsonl"))
    return {"total": round(m.get("cash", 0) + sum(h["value"] for h in hs)), "cash": round(m.get("cash", 0)), "holdings": hs, "status": status}


def push_shadow(env, snap):
    """11-09 온톨로지 그림자 운영의 1분 자산·상태·최근 판단을 같이 올림 (supabase/shadow.sql). 그림자가 없으면 건너뜀.
    실패해도 실제 잔고 업로드에는 영향 없음."""
    try:
        x = shadow_now(snap)
    except Exception as e:  # noqa: BLE001
        return print(f"  (그림자 계산 건너뜀: {str(e)[:120]})")
    if not x or not x.get("total"):
        return
    try:
        key = env["SUPABASE_ANON_KEY"]
        post_json(env["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/push_shadow", {
            "p_secret": env["SNAPSHOT_SECRET"], "p_total": int(x["total"]), "p_cash": int(x.get("cash") or 0),
            "p_holdings": x.get("holdings", []), "p_status": x.get("status", {})}, {"apikey": key, "Authorization": "Bearer " + key})
        print(f"  → 그림자(온톨로지) {int(x['total']):,}원")
    except Exception as e:  # noqa: BLE001  shadow.sql 실행 전이면 404
        print(f"  (그림자 업로드 건너뜀: {str(e)[:120]})")


def market_open(now):
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 830 <= hm <= 1535   # 08:30부터: 장 전에도 손절·익절 감시(monitor)가 이 잔고를 읽음 (가격은 09:00부터 움직임)


def run_once(env, dry=False):
    token = get_token(env)
    snap = get_balance(env, token)
    kospi = get_kospi(env, token)
    stamp = datetime.now(KST).strftime("%m-%d %H:%M:%S")
    print(f"[{stamp}] {env['ACCOUNT_NAME']} 총자산 {snap['total']:,}원 · 주식 {snap['stock_eval']:,}원 · 종목 {len(snap['holdings'])}개 · KOSPI {kospi}")
    # 에이전트 장중 감시(agent/src/monitor.py)가 키움을 다시 부르지 않고 읽을 수 있게 로컬에 남김
    with open(os.path.join(HERE, "last_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump({**snap, "kospi": kospi, "epoch": time.time()}, f, ensure_ascii=False)
    if dry:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return
    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SNAPSHOT_SECRET"):
        if not env.get(k):
            sys.exit(f".env 에 {k} 값이 비어 있습니다.")
    push(env, snap, kospi)
    print("  → 대시보드에 올림")
    push_shadow(env, snap)


def main():
    env = load_env()
    args = set(sys.argv[1:])
    if "--loop" not in args:
        run_once(env, dry="--dry" in args)
        return
    interval = max(60, int(env["INTERVAL_SEC"]))
    print(f"반복 모드 시작 · {interval}초 간격 · 장 마감(15:35) 후 종료")
    while True:
        now = datetime.now(KST)
        if now.weekday() >= 5 or now.hour * 100 + now.minute > 1535:
            print("장 마감 · 종료")
            return
        if market_open(now):
            try:
                run_once(env)
            except Exception as e:  # noqa: BLE001  하나 실패해도 다음 회차에 다시 시도
                print(f"  ! 실패: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
