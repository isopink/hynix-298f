"""
장중 후보 갱신: 정기 판단(09:30~15:00, 30분마다) 직전에 '오늘 장중 수급이 활발한 종목'으로 후보를 다시 뽑습니다.
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


def screen(rows, p, r, frac, regime=None):
    """rows: 일봉 지표 + 장중 값(price, chg, value, foreign_qty, inst_qty)이 합쳐진 종목들 → 점수순 후보."""
    s, it = p["screen"], p["screen"].get("intraday", {})
    lim = r.get("max_buy_day_change", 0.10)
    ok = []
    for x in rows:
        nm, px = x.get("name", ""), x.get("price") or x.get("close")
        if not x["code"].endswith("0") or any(k in nm for k in s["exclude_name_keywords"]) or C.other_etf(nm, p):
            continue
        if x.get("limit_up_recent") or x.get("trading_value_20d", 0) < s["min_trading_value"]:
            continue
        hv = p.get("high_vol") or {}
        x["high_vol"] = x.get("vol20", 0) > s.get("max_vol20", 9)
        if x["high_vol"] and not (hv.get("enabled") and x["vol20"] <= hv.get("max_vol20", 0)):
            continue
        if (x.get("chg") or 0) >= lim:              # 어차피 리스크 규칙이 막는 추격 매수
            continue
        if not C.trend_ok(px, x, regime, p):          # 단기 상승 추세 (지금 가격 기준). 하락 국면이면 20일선 위만
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
    hv_n = (p.get("high_vol") or {}).get("max_candidates", 0)   # 고변동 종목은 따로 몇 개만 (작게 사는 몫)
    return [x for x in ok if not x["high_vol"]][: s["max_candidates"]] + [x for x in ok if x["high_vol"]][:hv_n]


def ensure_inverse(b, p, held):
    """08:30 준비에 시장 ETF(인버스·지수) 후보가 없으면(설정을 장중에 켠 날) 여기서 한 번 만들어 후보에 붙임."""
    have = b.get("candidates_prep", b.get("candidates", []))
    kinds = tuple(k for k in ("inverse", "index") if (p.get(k) or {}).get("enabled") and not any(x.get(k) for x in have))
    if not kinds:
        return
    try:
        import pandas as pd
        import data_prep
        rows = data_prep.inverse_rows(p, pd.Timestamp(b["asof"]).date(), False, held, kinds)
    except Exception as e:  # noqa: BLE001
        return print(f"  ! 인버스 후보 추가 실패: {e}")
    for key in ("candidates", "candidates_prep"):
        if key in b:
            b[key] = b[key] + rows
    if rows:
        print("시장 ETF 후보 추가: " + ", ".join(r["name"] for r in rows))


def fill_up(cands, prep, held, n):
    """장중 통과가 n개보다 적으면 08:30 후보로 n개까지 채우고(from_prep), 08:30 시장 ETF(인버스·지수) 후보는 항상 붙임.
    (11-04 09:30 처럼 통과 2개만 남아 판단할 게 없는 일 방지)"""
    out, have = list(cands), {c["code"] for c in cands}
    for x in prep:
        if sum(1 for c in out if not etf(c)) >= n:
            break
        if x["code"] not in have and x["code"] not in held and not etf(x):
            out.append({**x, "from_prep": True})
            have.add(x["code"])
    return out + [x for x in prep if etf(x) and x["code"] not in have and x["code"] not in held]


def dips(rows, cands, held, p, now):
    """📉급락 반등 후보 (params.dip, 11-05): from 이후 회차에만, 거래대금 상위 안에서 오늘 drop 이하로 빠진 종목.
    추세·수급 조건은 면제(급락한 날이라 대개 못 넘음). 살지는 토론·확신도가 정하고 크기는 sizing 이 dip.weight 로."""
    dp = p.get("dip") or {}
    if not dp.get("enabled") or now.strftime("%H:%M") < dp.get("from", "15:10"):
        return []
    s, have = p["screen"], {c["code"] for c in cands}
    out = []
    for x in sorted(rows, key=lambda x: x.get("chg") or 0):
        nm = x.get("name", "")
        if (x.get("chg") is None or x["chg"] > dp["drop"] or x.get("value_rank", 999) > dp["top_value_rank"]
                or x["code"] in held or not x["code"].endswith("0") or C.other_etf(nm, p)
                or any(k in nm for k in s["exclude_name_keywords"])):
            continue
        if x["code"] in have:   # 이미 후보면 표시만
            next(c for c in cands if c["code"] == x["code"])["dip"] = True
            continue
        px = x.get("price") or x.get("close") or 0
        out.append({**x, "dip": True, "score": x.get("score", 0),
                    "foreign_today": round((x.get("foreign_qty") or 0) * px), "inst_today": round((x.get("inst_qty") or 0) * px)})
        if len(out) >= dp["max_candidates"]:
            break
    if out:
        print("📉급락 후보: " + ", ".join(f"{x['name']}({x['chg']:+.1%})" for x in out))
    return out


def etf(x):
    return x.get("inverse") or x.get("index")


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
    ensure_inverse(b, p, held)

    # 풀 정렬: 거래대금 순위·외국인·기관 순위 중 가장 좋은 것 순 → 일봉 지표가 없는 종목은 max_new_analyze 개까지만 새로 계산
    order = sorted((x for c, x in pool.items() if c not in held and not C.market_etf(c, p)[0]),
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

    regime = (C.latest_regime() or {}).get("regime") or b.get("market", {}).get("rule_hint")
    cands = screen(rows, p, r, elapsed_frac(n), regime)
    if not cands:
        print("장중 조건을 통과한 종목이 없어 08:30 후보를 그대로 씀")
        b["intraday"] = {"time": n.strftime("%H:%M"), "pool": len(pool), "passed": 0, "kept_prep": True}
        C.write_json(C.BRIEFING, b)
        return
    prep = b.get("candidates_prep", b.get("candidates", []))
    cands = fill_up(cands, prep, held, it.get("min_candidates", 0))
    cands += dips(rows, cands, held, p, n)
    old = {c["code"]: c for c in prep}
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


def rsi_now(closes, price):
    """전일까지 종가 + 지금 가격(오늘 종가로 가정) → RSI(14). 전일 RSI 와 같은 GS Quant 함수."""
    import pandas as pd
    from data_prep import gts
    s = pd.Series([*closes, price], index=pd.bdate_range(end=C.today(), periods=len(closes) + 1), dtype=float)
    return round(float(gts.relative_strength_index(s, 14).iloc[-1]), 1)


def live_rsi():
    """후보·보유 종목의 rsi14_live 를 지금 가격으로 채움 (conf_boost 가 씀). 오늘 산 종목도 보유에 넣음.
    현재가는 순위 API 값(있으면) → 없으면 ka10001 (1.1초 간격). 종가가 없으면 pykrx 로 받음."""
    import broker
    n = C.now()
    if not (900 <= n.hour * 100 + n.minute <= 1530) or n.weekday() >= 5:
        return print("장중이 아니라 장중 RSI 생략 (전일 RSI 사용)")
    brk = broker.get()
    if brk.name != "live":
        return print("mock 모드: 장중 RSI 생략")
    b = C.read_json(C.BRIEFING)
    if not b:
        return
    cache = {x["code"]: x for x in (C.read_json(PREP_ROWS, []) or [])}
    for x in b.get("candidates_prep", []) + b.get("candidates", []):
        cache.setdefault(x["code"], x)
    hold = b.setdefault("holdings", [])
    for h in (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", []):
        if h["code"] not in {x["code"] for x in hold} and h["code"] in cache:
            hold.append({**cache[h["code"]]})
    done, out = {}, []
    for x in b.get("candidates", []) + hold:
        c = x["code"]
        if c not in done:
            try:
                closes = x.get("closes") or cache.get(c, {}).get("closes")
                if not closes:
                    import data_prep
                    closes = [round(float(v)) for v in data_prep.ohlcv(c)["종가"].tail(120)]
                    x["closes"] = closes
                price = x.get("price") if x.get("activity") is not None else None   # 순위 API 로 방금 받은 가격
                price = price or brk.quote_info(c)["price"]
                done[c] = rsi_now(closes, price) if len(closes) >= 15 and price else None
            except Exception as e:  # noqa: BLE001  한 종목 실패는 전일 RSI 로
                print(f"  ! {c} 장중 RSI 실패: {e}")
                done[c] = None
            if done[c] is not None:
                out.append(f"{x.get('name', c)} {x.get('rsi14')}→{done[c]}")
        x["rsi14_live"] = done[c]
    b["rsi_live_time"] = n.strftime("%H:%M")
    C.write_json(C.BRIEFING, b)
    print(f"장중 RSI ({n.strftime('%H:%M')}): " + (", ".join(out) or "없음"))


if __name__ == "__main__":
    C.load_env()
    if "--rsi" in sys.argv:   # run.py decide 가 후보 갱신 다음에 따로 부름 (서로 실패해도 영향 없게)
        try:
            live_rsi()
        except Exception as e:  # noqa: BLE001
            print(f"장중 RSI 실패, 전일 RSI 를 씀: {type(e).__name__}: {e}")
        sys.exit(0)
    try:
        run(dry="--dry" in sys.argv)
    except Exception as e:  # noqa: BLE001  실패해도 판단은 08:30 후보로 진행
        print(f"장중 후보 갱신 실패, 08:30 후보를 그대로 씀: {type(e).__name__}: {e}")
        b = C.read_json(C.BRIEFING)
        if b:   # 실패도 briefing 에 남겨 대시보드·커밋에서 보이게
            b["intraday"] = {"time": C.now().strftime("%H:%M"), "kept_prep": True, "error": f"{type(e).__name__}: {str(e)[:120]}"}
            C.write_json(C.BRIEFING, b)
