"""
키움 모의투자 잔고를 조회해서 대시보드(Supabase)에 올리는 스크립트.

- 조회만 합니다. 주문은 절대 하지 않습니다.
- 키움 키는 이 PC의 .env 에만 있고, 사이트로는 숫자만 넘어갑니다.
- 파이썬 기본 라이브러리만 사용 (pip 설치 필요 없음).

사용법
  python snapshot.py            # 지금 한 번 조회해서 올림
  python snapshot.py --loop     # 장중(평일 09:00~15:35) 동안 INTERVAL_SEC 마다 반복, 장 끝나면 종료
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
        time.sleep(0.3)
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


def market_open(now):
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 900 <= hm <= 1535


def run_once(env, dry=False):
    token = get_token(env)
    snap = get_balance(env, token)
    kospi = get_kospi(env, token)
    stamp = datetime.now(KST).strftime("%m-%d %H:%M:%S")
    print(f"[{stamp}] {env['ACCOUNT_NAME']} 총자산 {snap['total']:,}원 · 주식 {snap['stock_eval']:,}원 · 종목 {len(snap['holdings'])}개 · KOSPI {kospi}")
    if dry:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return
    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SNAPSHOT_SECRET"):
        if not env.get(k):
            sys.exit(f".env 에 {k} 값이 비어 있습니다.")
    push(env, snap, kospi)
    print("  → 대시보드에 올림")


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
