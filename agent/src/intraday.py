"""
장중 후보 갱신: 정기 판단(09:30·11:00·14:30) 직전에 '오늘 장중 수급이 활발한 종목'으로 후보를 다시 뽑습니다.
08:30 준비는 전일 거래대금·전일까지의 수급으로 후보를 골랐는데, 그러면 오늘 돈이 몰리는 종목을 놓칩니다.

1. 키움 순위 API (판단 1회당 3번, 1.1초 간격)
   - ka10032 거래대금 상위 (오늘 누적)
   - ka10065 장중 투자자별 매매 상위 (외국인 순매수 · 기관계 순매수)
2. 후보 풀 = 위 세 목록의 합집합 → 일봉 지표(08:30 준비 결과 재사용, 없는 종목만 pykrx로 계산)
3. 안전 필터: 우선주·스팩·리츠·최근 상한가·변동성 상한·평소 거래대금 하한·오늘 +10% 이상(추격 매수 금지)·단기 추세(현재가 > 5일선 > 20일선)
4. 장중 점수 = 활발도(오늘 거래대금 ÷ 평소 같은 시각까지 거래대금) + 오늘 외국인·기관 순매수 비중 + 20일선 대비 위치 − 5일 급등 감점
5. work/briefing.json 의 candidates 를 바꿔 씀 (08:30 후보는 candidates_prep 에 보관). 실패하면 08:30 후보를 그대로 둠.

사용법
  python src/intraday.py          # 갱신 후 요약 출력 (run.py decide 가 판단 전에 부름)
  python src/intraday.py --dry    # 순위 API 응답만 확인, briefing 은 안 바꿈 (주문 없음, 조회 3번)
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

RANK_PATH = "/api/dostk/rkinfo"
SESSION_MIN = 390   # 09:00~15:30


def code6(s):
    m = re.search(r"\d{6}", str(s or ""))
    return m.group(0) if m else None


def first_list(res, key):
    """응답에서 종목 목록. 문서상 키가 없으면 첫 번째 리스트 값을 씀 (모의/실서버 필드 차이 대비)."""
    if isinstance(res.get(key), list):
        return res[key]
    return next((v for v in res.values() if isinstance(v, list)), [])


def fetch(brk, num):
    """키움 순위 API 3번 → {code: {name, price, chg, value, foreign_qty, inst_qty}}. 원문은 work/rank_raw/ 에 남김."""
    calls = [
        ("value", "ka10032", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}, "trde_prica_upper"),
        ("foreign", "ka10065", {"trde_tp": "1", "mrkt_tp": "000", "orgn_tp": "9000"}, "opmr_invsr_trde_upper"),
        ("inst", "ka10065", {"trde_tp": "1", "mrkt_tp": "000", "orgn_tp": "9999"}, "opmr_invsr_trde_upper"),
    ]
    raw_dir = os.path.join(C.WORK, "rank_raw")
    os.makedirs(raw_dir, exist_ok=True)
    pool, lists = {}, {}
    for tag, api, body, key in calls:
        res = brk._call(RANK_PATH, api, body)
        C.write_json(os.path.join(raw_dir, f"{tag}.json"), {"time": C.stamp(), "api": api, "body": body, "response": res})
        lists[tag] = first_list(res, key)
    for i, x in enumerate(lists["value"]):
        c = code6(x.get("stk_cd"))
        if not c:
            continue
        price = abs(num(x.get("cur_prc")))
        qty = abs(num(x.get("now_trde_qty")))
        pool[c] = {"code": c, "name": str(x.get("stk_nm", "")).strip(), "price": price,
                   "chg": round(num(x.get("flu_rt"), True) / 100, 4), "value": price * qty, "value_rank": i + 1}
    for tag in ("foreign", "inst"):
        for i, x in enumerate(lists[tag]):
            c = code6(x.get("stk_cd"))
            if not c:
                continue
            r = pool.setdefault(c, {"code": c, "name": str(x.get("stk_nm", "")).strip()})
            r[f"{tag}_qty"] = num(x.get("netslmt") or (num(x.get("buy_qty")) - num(x.get("sel_qty"))))
            r[f"{tag}_rank"] = i + 1
    return pool, {k: len(v) for k, v in lists.items()}


def num(s, as_float=False):
    s = str(s if s is not None else "").replace(",", "").strip()
    if not s or s in "+-":
        return 0.0 if as_float else 0
    return float(s) if as_float else int(float(s))


def elapsed_frac(now=None):
    n = now or C.now()
    m = (n.hour - 9) * 60 + n.minute
    return min(1.0, max(0.05, m / SESSION_MIN))


def rank_pct(vals):
    """작은 값 0 → 큰 값 1 (동점은 평균 순위). pandas 없이."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = ((i + j) / 2 + 1) / len(vals)
        i = j + 1
    return out


def screen(rows, p, r, frac):
    """rows: 일봉 지표 + 장중 값(price, chg, value, foreign_qty, inst_qty)이 합쳐진 종목들 → 점수순 후보."""
    s, it = p["screen"], p["screen"].get("intraday", {})
    lim = r.get("max_buy_day_change", 0.10)
    ok = []
    for x in rows:
        nm, px = x.get("name", ""), x.get("price") or x.get("close")
        if not x["code"].endswith("0") or any(k in nm for k in s["exclude_name_keywords"]):
            continue
        if x.get("limit_up_recent") or x.get("trading_value_20d", 0) < s["min_trading_value"]:
            continue
        if x.get("vol20", 0) > s.get("max_vol20", 9):
            continue
        if (x.get("chg") or 0) >= lim:              # 어차피 리스크 규칙이 막는 추격 매수
            continue
        if not (px > x["ma5"] > x["ma20"]):           # 단기 상승 추세 (지금 가격 기준)
            continue
        f_amt = (x.get("foreign_qty") or 0) * px
        i_amt = (x.get("inst_qty") or 0) * px
        if it.get("require_flow", True) and f_amt <= 0 and i_amt <= 0:
            continue
        value = x.get("value") or 0
        x["foreign_today"], x["inst_today"] = round(f_amt), round(i_amt)
        x["activity"] = round(value / (x["trading_value_20d"] * frac), 2) if value else None
        x["flow_today_ratio"] = round((max(f_amt, 0) + max(i_amt, 0)) / x["trading_value_20d"], 4)
        x["trend_gap"] = px / x["ma20"] - 1
        ok.append(x)
    if not ok:
        return []
    a = rank_pct([x["activity"] or 0 for x in ok])
    f = rank_pct([x["flow_today_ratio"] for x in ok])
    t = rank_pct([x["trend_gap"] for x in ok])
    raw = []
    for x, ai, fi, ti in zip(ok, a, f, t):
        sc = ai + fi + ti * it.get("trend_weight", 0.5)
        if x.get("ret5", 0) > s.get("spike_ret5", 9):
            sc -= s.get("spike_penalty", 0)
        raw.append(max(0.0, sc))
    top = max(raw) or 1
    for x, sc in zip(ok, raw):
        x["score"] = round(sc / top, 3)
        x.pop("trend_gap", None)
    ok.sort(key=lambda x: -x["score"])
    return ok[: s["max_candidates"]]


def run(dry=False):
    import broker
    p, r = C.params(), C.risk_limits()
    it = p["screen"].get("intraday", {})
    if not it.get("enabled", True):
        return print("장중 후보 갱신 꺼짐 (params.screen.intraday.enabled)")
    n = C.now()
    if not dry and (not (900 <= n.hour * 100 + n.minute <= 1530) or n.weekday() >= 5):
        return print("장중이 아니라 08:30 후보를 그대로 씀")
    brk = broker.get()
    if brk.name != "live":
        return print("mock 모드: 순위 API 가 없어 08:30 후보를 그대로 씀")

    pool, sizes = fetch(brk, num)
    print(f"순위 API: 거래대금 {sizes['value']} · 외국인 {sizes['foreign']} · 기관 {sizes['inst']} → 풀 {len(pool)}종목")
    if dry:
        for x in sorted(pool.values(), key=lambda x: x.get("value_rank", 999))[:15]:
            print(f"  {x['code']} {x['name']} 가격 {x.get('price')} 등락 {x.get('chg')} 거래대금 {x.get('value', 0) / 1e8:,.0f}억 "
                  f"외국인 {x.get('foreign_qty')}주 기관 {x.get('inst_qty')}주")
        return print("(--dry: briefing 은 바꾸지 않음. 원문은 work/rank_raw/)")
    if not pool:
        raise RuntimeError("순위 API 결과가 비어 있음")

    b = C.read_json(C.BRIEFING)
    if not b:
        raise RuntimeError("08:30 브리핑이 없음")
    held = {h["code"] for h in (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", [])}
    cache = {x["code"]: x for x in (C.read_json(PREP_ROWS, []) or [])}

    # 풀 정렬: 거래대금 순위·외국인·기관 순위 중 가장 좋은 것 순 → 일봉 지표가 없는 종목은 max_new_analyze 개까지만 새로 계산
    order = sorted((x for c, x in pool.items() if c not in held),
                   key=lambda x: min(x.get("value_rank", 999), x.get("foreign_rank", 999), x.get("inst_rank", 999)))
    login, asof, new = None, None, 0
    rows = []
    for x in order:
        ind = cache.get(x["code"])
        if ind is None and new < it.get("max_new_analyze", 30):
            import pandas as pd
            import data_prep
            login = data_prep.krx_login() if login is None else login
            asof = asof or pd.Timestamp(b["asof"]).date()
            try:
                ind = data_prep.analyze(x["code"], x["name"] or data_prep.name_of(x["code"]), p, asof, login)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {x['code']} 지표 실패: {e}")
            new += 1
            if ind:
                cache[x["code"]] = ind
        if ind:
            rows.append({**ind, **{k: v for k, v in x.items() if v not in (None, "")}})

    cands = screen(rows, p, r, elapsed_frac(n))
    if not cands:
        print("장중 조건을 통과한 종목이 없어 08:30 후보를 그대로 씀")
        b["intraday"] = {"time": n.strftime("%H:%M"), "pool": len(pool), "passed": 0, "kept_prep": True}
        C.write_json(C.BRIEFING, b)
        return
    old = {c["code"]: c for c in b.get("candidates_prep", b.get("candidates", []))}
    need_news = [c for c in cands if c["code"] not in old]
    if need_news:
        import data_prep
        found = data_prep.news(need_news)
    else:
        found = {}
    for c in cands:
        c["news"] = old[c["code"]].get("news", []) if c["code"] in old else found.get(c["code"], [])
    b.setdefault("candidates_prep", b.get("candidates", []))
    b["candidates"] = cands
    b["intraday"] = {"time": n.strftime("%H:%M"), "pool": len(pool), "analyzed_new": new, "passed": len(cands), "kept_prep": False}
    C.write_json(C.BRIEFING, b)
    C.write_json(PREP_ROWS, list(cache.values()))
    print(f"장중 후보 {len(cands)}개 ({n.strftime('%H:%M')}): " + ", ".join(f"{c['name']}({c['score']})" for c in cands))


PREP_ROWS = os.path.join(C.WORK, "prep_rows.json")   # 08:30 준비에서 계산한 전 종목 일봉 지표 (data_prep.build 가 씀)


if __name__ == "__main__":
    C.load_env()
    try:
        run(dry="--dry" in sys.argv)
    except Exception as e:  # noqa: BLE001  실패해도 판단은 08:30 후보로 진행
        print(f"장중 후보 갱신 실패, 08:30 후보를 그대로 씀: {type(e).__name__}: {e}")
