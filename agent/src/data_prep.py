"""
데이터 준비: 시세·수급·뉴스 수집 → GS Quant 지표 → 후보 종목 선별 → 숫자 요약.

LLM은 여기서 만든 요약(briefing)만 봅니다. 숫자는 전부 이 코드가 계산합니다.

사용법
  python src/data_prep.py          # work/briefing.json 생성 후 요약 출력
  python src/data_prep.py --show   # 저장된 요약만 출력

KRX_ID / KRX_PW 가 있으면 전 종목에서 후보를 고르고(정식 모드),
없으면 params.json 의 fallback_universe 대형주 안에서만 고릅니다(대체 모드, 수급 없음).
NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 있으면 후보·보유 종목의 최근 뉴스 제목을 붙입니다.
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import warnings
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

C.load_env()
os.environ.setdefault("MPLCONFIGDIR", os.path.join(C.WORK, ".mpl"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402
import gs_quant.timeseries as gts  # noqa: E402
from pykrx import stock  # noqa: E402  (import 시점에 KRX_ID/KRX_PW 로 로그인)

INDEX_PROXY = "069500"  # KRX 로그인 없을 때 KOSPI 대신 쓰는 KODEX 200
NEWS_DAYS = 3  # 최근 며칠 뉴스까지 볼지
RISK_WORDS = ["유상증자", "전환사채", "신주인수권", "감자", "횡령", "배임", "소송", "불성실공시",
              "관리종목", "거래정지", "상장적격성", "최대주주변경", "영업정지"]


def ymd(d):
    return d.strftime("%Y%m%d")


def krx_login():
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def completed(df):
    """장 마감(15:30) 전이면 오늘의 미완성 일봉을 뺌."""
    if df is None or df.empty:
        return df
    n = C.now()
    if n.hour * 100 + n.minute < 1530:
        df = df[df.index.date < n.date()]
    return df


def ohlcv(code, days=150):
    end = C.today()
    if C.market_etf(code)[0]:   # ETF 는 ETF 시세 (종목 시세 조회에 안 나올 수 있음)
        try:
            df = stock.get_etf_ohlcv_by_date(ymd(end - timedelta(days=days * 1.6)), ymd(end), code)
            time.sleep(0.15)
            if df is not None and not df.empty:
                return completed(df)
        except Exception as e:  # noqa: BLE001  아래 일반 시세로 한 번 더
            print(f"  ! {code} ETF 시세 실패, 일반 시세로: {e}")
    df = stock.get_market_ohlcv(ymd(end - timedelta(days=days * 1.6)), ymd(end), code)
    time.sleep(0.15)
    return completed(df)


def name_of(code):
    if etf := C.market_etf(code)[0]:
        return etf["codes"][code]
    try:
        return stock.get_market_ticker_name(code) or code
    except Exception:  # noqa: BLE001
        return code


# ---------------- 지표 (GS Quant) ----------------
def indicators(close):
    """종가 시리즈 → 숫자 요약. 데이터가 60일 미만이면 None."""
    close = close.astype(float)
    if len(close) < 60:
        return None
    ma5 = gts.moving_average(close, gts.Window(5, 0))
    ma20 = gts.moving_average(close, gts.Window(20, 0))
    ma60 = gts.moving_average(close, gts.Window(60, 0))
    rsi = gts.relative_strength_index(close, 14)
    vol = gts.volatility(close, gts.Window(20, 0))          # 연율화 %
    mdd = gts.max_drawdown(close, gts.Window(60, 0))        # 60일 최대 낙폭 (음수)
    c = float(close.iloc[-1])
    return {
        "close": round(c),
        "ma5": round(float(ma5.iloc[-1])),
        "ma20": round(float(ma20.iloc[-1])),
        "ma60": round(float(ma60.iloc[-1])),
        "ma20_slope5": round(float(ma20.iloc[-1] / ma20.iloc[-6] - 1), 4),
        "ret5": round(c / float(close.iloc[-6]) - 1, 4),
        "ret20": round(c / float(close.iloc[-21]) - 1, 4),
        "rsi14": round(float(rsi.iloc[-1]), 1),
        "vol20": round(float(vol.iloc[-1]) / 100, 3),
        "mdd60": round(float(mdd.iloc[-1]), 3),
    }


# ---------------- 시장 ----------------
def market_summary():
    end = C.today()
    start = ymd(end - timedelta(days=200))
    src = "KOSPI"
    try:
        if not krx_login():
            raise RuntimeError("no login")
        df = completed(stock.get_index_ohlcv(start, ymd(end), "1001"))
        if df is None or df.empty:
            raise RuntimeError("empty")
    except Exception:  # noqa: BLE001
        df, src = ohlcv(INDEX_PROXY, 200), "KODEX 200 (KOSPI 대용)"
    ind = indicators(df["종가"])
    return {"source": src, "asof": df.index[-1].strftime("%Y-%m-%d"), **(ind or {}),
            "rule_hint": rule_hint(ind) if ind else "횡보",
            "closes": [round(float(v), 2) for v in df["종가"].tail(65)]}   # 장중 실시간 힌트 계산용 (대시보드·판단)


def rule_hint(ind):
    """종가·5일선·20일선 배열과 20일선 기울기로 국면 힌트.
    대회가 4주라 60일선 기준은 너무 늦게 반응해서 11-03부터 5·20일선으로 바꿈."""
    if ind["close"] > ind["ma5"] > ind["ma20"] and ind["ma20_slope5"] > 0:
        return "상승"
    if ind["close"] < ind["ma5"] < ind["ma20"] and ind["ma20_slope5"] < 0:
        return "하락"
    return "횡보"


def live_market(b):
    """장중이면 마감된 일봉 + 지금 KOSPI(잔고 루프가 5분마다 받는 값)로 힌트를 다시 계산. 키움 호출 없음."""
    m, snap = b.get("market", {}), C.read_json(os.path.join(C.LIVE, "last_snapshot.json")) or {}
    closes, px = m.get("closes") or [], snap.get("kospi")
    if m.get("source") != "KOSPI" or len(closes) < 65 or not px or time.time() - snap.get("epoch", 0) > 15 * 60:
        return None
    s = closes + [float(px)]
    ma = lambda n, off=0: sum(s[len(s) - off - n:len(s) - off]) / n   # noqa: E731
    ind = {"close": round(float(px), 2), "ma5": round(ma(5)), "ma20": round(ma(20)), "ma60": round(ma(60)),
           "ma20_slope5": round(ma(20) / ma(20, 5) - 1, 4)}
    return {**ind, "rule_hint": rule_hint(ind), "time": C.now().strftime("%H:%M")}


# ---------------- 종목 ----------------
def universe_krx(p, asof):
    """전 종목 중 거래대금·이름 조건으로 1차 선별 (KRX 로그인 필요)."""
    s = p["screen"]
    quota = {k: v for k, v in (s.get("prefilter_by_market") or {}).items() if not k.startswith("_")}
    out, markets = [], {}
    for m in s["markets"]:   # 11-04 시장별로 따로 상위 N (합쳐 뽑으면 코스피 대형주가 거의 다 차지해 코스닥이 빠짐)
        n = quota.get(m, s["prefilter_top"])
        df = stock.get_market_ohlcv(ymd(asof), market=m)
        markets.update({c: m for c in df.index})   # 종목코드 → 시장 (대시보드 Watch List 표시용, 장중 재선별 종목도 여기서 찾음)
        df = df[(df["거래대금"] >= s["min_trading_value"]) & (df.index.str.endswith("0"))]  # 우선주 제외
        got = 0
        for code in df.sort_values("거래대금", ascending=False).index[: n * 2]:
            nm = name_of(code)
            if any(k in nm for k in s["exclude_name_keywords"]) or C.other_etf(nm, p):
                continue
            out.append((code, nm))
            got += 1
            if got >= n:
                break
    C.write_json(C.MARKETS, markets)
    return out


def flows(code, asof, n):
    """최근 n거래일 외국인·기관 순매수 금액 합 (원). KRX 로그인 필요."""
    try:
        df = stock.get_market_trading_value_by_date(ymd(asof - timedelta(days=n * 2 + 7)), ymd(asof), code)
        time.sleep(0.15)
        df = df.tail(n)
        return int(df["외국인합계"].sum()), int(df["기관합계"].sum())
    except Exception:  # noqa: BLE001
        return None, None


def news(rows):
    """네이버 뉴스 검색 API로 종목별 최근 뉴스 제목 (최대 3개). 악재 단어가 있으면 risk=True. 키 없으면 빈 결과."""
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and sec):
        return {}
    since = C.today() - timedelta(days=NEWS_DAYS)
    out = {}
    for r in rows:
        q = urllib.parse.quote(f'"{r["name"]}"')
        # 2026-07 이후 신규 키는 NAVER API HUB(네이버 클라우드)에서만 발급 → 주소·헤더가 바뀜, 응답 형식은 같음
        req = urllib.request.Request(f"https://naverapihub.apigw.ntruss.com/search/v1/news?query={q}&display=20&sort=date",
                                     headers={"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec})
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                items = json.loads(res.read().decode("utf-8")).get("items", [])
        except Exception:  # noqa: BLE001
            continue
        finally:
            time.sleep(0.15)
        hits, seen = [], set()
        for it in items:
            d = pd.to_datetime(it.get("pubDate"), errors="coerce")
            title = html.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip()
            if pd.isna(d) or d.date() < since or r["name"] not in title or title in seen:
                continue
            seen.add(title)
            hits.append({"date": d.strftime("%m-%d"), "title": title, "risk": any(w in title for w in RISK_WORDS)})
        hits.sort(key=lambda h: not h["risk"])  # 악재 단어가 있는 제목을 먼저
        if hits:
            out[r["code"]] = hits[:3]
    return out


def analyze(code, name, p, asof, login):
    df = ohlcv(code)
    if df is None or len(df) < 60:
        return None
    ind = indicators(df["종가"])
    if not ind:
        return None
    s = p["screen"]
    tv = df["거래대금"] if "거래대금" in df else df["종가"] * df["거래량"]
    lim = df["등락률"].tail(s["limit_up_lookback"]) >= 29.5 if "등락률" in df else pd.Series([False])
    row = {"code": code, "name": name, **ind,
           "trading_value_20d": int(tv.tail(20).mean()),
           "limit_up_recent": bool(lim.any()),
           "closes": [round(float(x)) for x in df["종가"].tail(120)]}   # 장중 RSI 계산용 (intraday.py)
    if login:
        f, i = flows(code, asof, s["flow_days"])
        row["foreign_net"], row["inst_net"] = f, i
    return row


def screen(rows, p, login, regime=None):
    """추세 조건 + (정식 모드) 수급 조건 → 점수순 상위."""
    s = p["screen"]
    ok = []
    for r in rows:
        if r["limit_up_recent"] or r["trading_value_20d"] < s["min_trading_value"]:
            continue
        hv = p.get("high_vol") or {}
        r["high_vol"] = r["vol20"] > s.get("max_vol20", 9)   # 변동성이 크면 손절 -7%가 소음에도 걸림 → 고변동 몫으로 따로, 작게
        if r["high_vol"] and not (hv.get("enabled") and r["vol20"] <= hv.get("max_vol20", 0)):
            continue
        if not C.trend_ok(r["close"], r, regime, p):   # 단기 상승 추세 (11-03 5·20일선). 하락 국면이면 20일선 위만 (11-05)
            continue
        if login and r.get("foreign_net") is not None:
            if r["foreign_net"] <= 0 and r["inst_net"] <= 0:
                continue
            r["flow_ratio"] = round((max(r["foreign_net"], 0) + max(r["inst_net"], 0)) / r["trading_value_20d"], 3)
        ok.append(r)
    if not ok:
        return []
    df = pd.DataFrame(ok)
    df["trend_gap"] = df["close"] / df["ma20"] - 1
    score = df["ret20"].rank(pct=True) + df["trend_gap"].rank(pct=True)
    if "flow_ratio" in df:
        score += df["flow_ratio"].fillna(0).rank(pct=True)
    score -= (df["ret5"] > s.get("spike_ret5", 9)).astype(float) * s.get("spike_penalty", 0)   # 5일 급등 종목 감점 (꼭대기 추격 방지)
    score = score.clip(lower=0)
    df["score"] = (score / score.max()).round(3) if score.max() > 0 else 0.0
    df = df.drop(columns=["trend_gap"]).sort_values("score", ascending=False)
    hv_n = (p.get("high_vol") or {}).get("max_candidates", 0)
    return (df[~df["high_vol"]].head(s["max_candidates"]).to_dict("records")
            + df[df["high_vol"]].head(hv_n).to_dict("records"))


def inverse_rows(p, asof, login, held, kinds=("inverse", "index")):
    """시장 ETF(인버스·지수추종)는 추세·수급 조건 없이 매일 후보에 따로 넣음 (살 수 있는지는 국면으로 코드가 정함).
    보유 중이면 보유 쪽에만. 행에 inverse=True 또는 index=True 표시."""
    out = []
    for kind in kinds:
        cfg = p.get(kind) or {}
        if not cfg.get("enabled"):
            continue
        for code, nm in cfg.get("codes", {}).items():
            if code in held:
                continue
            try:
                r = analyze(code, nm, p, asof, False)   # ETF 는 투자자별 수급 조회를 하지 않음
            except Exception as e:  # noqa: BLE001
                print(f"  ! {nm}({code}) 건너뜀: {e}")
                continue
            if r:
                r[kind], r["score"] = True, None
                out.append(r)
    return out


def build():
    p = C.params()
    login = krx_login()
    market = market_summary()
    asof = pd.Timestamp(market["asof"]).date()
    held = {h["code"]: h["name"] for h in (C.read_json(C.ACCOUNT, {}) or {}).get("holdings", [])}

    if login:
        try:
            uni = universe_krx(p, asof)
        except Exception as e:  # noqa: BLE001
            print(f"  ! 전 종목 조회 실패, 대체 모드로 진행: {e}")
            login, uni = False, None
    if not login:
        uni = [(c, name_of(c)) for c in p["screen"]["fallback_universe"]]

    rows, done = [], set()
    for code, nm in uni + [(c, n) for c, n in held.items()]:
        if code in done:
            continue
        done.add(code)
        try:
            r = analyze(code, nm, p, asof, login)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {code} 건너뜀: {e}")
            continue
        if r:
            rows.append(r)

    cands = screen([r for r in rows if r["code"] not in held and not C.market_etf(r["code"], p)[0]], p, login, market.get("rule_hint"))
    cands += inverse_rows(p, asof, login, held)
    holdings = [r for r in rows if r["code"] in held]
    found = news(cands + holdings)
    for r in cands + holdings:
        r["news"] = found.get(r["code"], [])

    out = {
        "created": C.stamp(), "asof": market["asof"],
        "source": "krx" if login else "fallback",
        "market": market, "candidates": cands, "holdings": holdings,
        "universe_size": len(rows),
    }
    C.write_json(C.BRIEFING, out)
    C.write_json(os.path.join(C.WORK, "prep_rows.json"), [{k: v for k, v in r.items() if k != "news"} for r in rows])   # 장중 후보 갱신(intraday.py)이 재사용
    return out


# ---------------- LLM 에 넘길 요약 ----------------
def pct(x):
    return "-" if x is None else f"{x * 100:+.1f}%"


def eok(x):
    return "-" if x is None else f"{x / 1e8:+,.0f}억"


def to_text(b):
    m = b["market"]
    lines = [
        f"# 브리핑 ({b['asof']} 종가 기준, {'전 종목' if b['source'] == 'krx' else '대형주 목록, 수급 없음'})",
        "",
        f"## 시장 ({m['source']})",
        f"종가 {m.get('close', 0):,} · 5일선 {m.get('ma5', 0):,} · 20일선 {m.get('ma20', 0):,} · 60일선 {m.get('ma60', 0):,} · "
        f"20일선 5일 기울기 {pct(m.get('ma20_slope5'))} · 20일 수익률 {pct(m.get('ret20'))} · "
        f"변동성 {m.get('vol20', 0) * 100:.0f}% · 60일 최대낙폭 {pct(m.get('mdd60'))} · 규칙 기반 힌트: {m['rule_hint']}",
        "",
    ]
    lv = m.get("live")
    if lv:
        lines[-1:-1] = [f"장중 실시간 ({lv['time']}, 지금 KOSPI를 오늘 종가로 가정): {lv['close']:,} · 5일선 {lv['ma5']:,} · 20일선 {lv['ma20']:,} · "
                        f"60일선 {lv['ma60']:,} · 20일선 5일 기울기 {pct(lv['ma20_slope5'])} · 실시간 힌트: {lv['rule_hint']}"]
    cols = "| 코드 | 종목 | 종가 | 5일선 | 20일선 | 60일선 | 5일 | 20일 | RSI | 변동성 | 60일 낙폭 | 외국인 5일 | 기관 5일 | 점수 |"
    sep = "|" + "---|" * 14

    def row(r):
        ma5 = f"{r['ma5']:,}" if r.get('ma5') else '-'
        kind = C.market_etf(r["code"])[1]
        tag = " 🔻인버스" if kind == "인버스" else " 📈지수" if kind == "지수" else " ⚡고변동" if r.get("high_vol") else ""
        return (f"| {r['code']} | {r['name']}{tag} | {r['close']:,} | {ma5} | {r['ma20']:,} | {r['ma60']:,} | {pct(r['ret5'])} | "
                f"{pct(r['ret20'])} | {r['rsi14']} | {r['vol20'] * 100:.0f}% | {pct(r['mdd60'])} | "
                f"{eok(r.get('foreign_net'))} | {eok(r.get('inst_net'))} | {r.get('score', '-')} |")

    it = b.get("intraday") or {}
    if it and not it.get("kept_prep"):
        lines += [f"## 장중 수급 ({it['time']} 기준) — 아래 후보는 오늘 장중 거래대금·외국인·기관 순매수로 다시 뽑은 것",
                  "지표(5일선·RSI 등)는 전일 종가 기준, 현재가·등락·거래대금·순매수는 지금 기준. "
                  "활발도 = 오늘 거래대금 ÷ 평소 같은 시각까지 거래대금 (1.0 = 평소 수준)", "",
                  "| 코드 | 종목 | 현재가 | 오늘 등락 | 오늘 거래대금 | 활발도 | 외국인 오늘 | 기관 오늘 |", "|" + "---|" * 8]
        for r in b["candidates"]:
            if r.get("from_prep") or r.get("inverse") or r.get("index"):
                lines.append(f"| {r['code']} | {r['name']} | - | - | - | - | - | - |   ({'인버스' if r.get('inverse') else '지수추종' if r.get('index') else '08:30 후보로 채움'})")
                continue
            act = r.get("activity")
            lines.append(f"| {r['code']} | {r['name']} | {r.get('price', 0):,} | {pct(r.get('chg'))} | "
                         f"{(r.get('value') or 0) / 1e8:,.0f}억 | {'-' if act is None else f'{act:.1f}배'} | "
                         f"{eok(r.get('foreign_today'))} | {eok(r.get('inst_today'))} |")
        lines.append("")
    elif it:
        lines += [f"장중 수급 갱신({it['time']}): 조건 통과 종목이 없어 08:30 후보를 그대로 씀", ""]
    for title, rs in (("후보 종목", b["candidates"]), ("보유 종목", b["holdings"])):
        lines.append(f"## {title} ({len(rs)})")
        if rs:
            lines += [cols, sep] + [row(r) for r in rs]
        else:
            lines.append("없음")
        notes = [f"- {r['name']} {n['date']}{' ⚠' if n['risk'] else ''} {n['title']}" for r in rs for n in r.get("news", [])]
        if notes:
            lines += ["", f"최근 뉴스 ({NEWS_DAYS}일, ⚠ = 악재 단어 포함):"] + notes
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--show" not in sys.argv:
        t = time.time()
        b = build()
        print(f"완료 · {b['source']} 모드 · {b['universe_size']}종목 분석 · 후보 {len(b['candidates'])}개 · {time.time() - t:.0f}초\n")
    print(to_text(C.read_json(C.BRIEFING)))
