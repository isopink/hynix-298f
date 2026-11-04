"""경로·설정·작업 파일·날짜 계산 등 모든 모듈이 같이 쓰는 도구."""
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

KST = timezone(timedelta(hours=9))

AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(AGENT)
CONFIG = os.path.join(AGENT, "config")
WORK = os.path.join(AGENT, "work")            # 실행 산출물 (커밋 안 함)
DOCS_DATA = os.path.join(ROOT, "docs", "data")
LIVE = os.path.join(ROOT, "live")

JOURNAL = os.path.join(WORK, "journal.jsonl")  # 판단·체결·차단 기록 (모든 로그의 원본)
ACCOUNT = os.path.join(WORK, "account.json")   # 마지막으로 조회한 계좌 상태 (Hook이 읽음)
POSITIONS = os.path.join(WORK, "positions.json")  # 종목별 손절·익절·진입일
BRIEFING = os.path.join(WORK, "briefing.json")
RUNS = os.path.join(WORK, "runs.jsonl")


def now():
    return datetime.now(KST)


def today():
    return now().date()


def stamp(dt=None):
    return (dt or now()).strftime("%Y-%m-%d %H:%M")


def load_env(path=os.path.join(AGENT, ".env")):
    """agent/.env → os.environ (이미 있는 값은 덮어쓰지 않음)."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
    os.environ.setdefault("MODE", "mock")
    return os.environ


def mode():
    return os.environ.get("MODE", "mock")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def journal(kind, **fields):
    """kind: regime | decision | fill | block | review"""
    row = {"kind": kind, "time": stamp(), "run": os.environ.get("RUN_ID", ""), "mode": os.environ.get("RUN_MODE", ""), **fields}
    append_jsonl(JOURNAL, row)
    return row


def risk_limits():
    return read_json(os.path.join(CONFIG, "risk_limits.json"))


def params():
    return read_json(os.path.join(CONFIG, "params.json"))


# ---------------- 날짜 ----------------
def business_days(start, end):
    """start 다음 날부터 end 까지의 평일 수 (보유일 계산용. 11월엔 공휴일 없음)."""
    if isinstance(start, str):
        start = date.fromisoformat(start)
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def competition_week(d=None, p=None):
    """대회 몇 주차인지 (시작 전 = 1, 끝난 뒤 = 4)."""
    p = p or params()
    start = date.fromisoformat(p["competition"]["start"])
    d = d or today()
    return min(4, max(1, (d - start).days // 7 + 1))


def week_factor(p=None, d=None):
    p = p or params()
    return float(p["week_factor"][str(competition_week(d, p))])


def fill_count():
    return sum(1 for r in read_jsonl(JOURNAL) if r["kind"] == "fill")


def buy_threshold(p=None):
    """매수 확신도 기준. 최소 거래 횟수가 모자라면 정해진 주차부터 조금 낮춤."""
    p = p or params()
    base = p["decision"]["buy_min_confidence"]
    g = p["min_trade_guard"]
    if competition_week(p=p) >= g["week"] and fill_count() < g["min_count"]:
        return round(base - g["relax"], 3)
    return base


def briefing_row(code, briefing=None):
    b = briefing if briefing is not None else (read_json(BRIEFING, {}) or {})
    return next((r for r in b.get("candidates", []) + b.get("holdings", []) if r.get("code") == code), None)


def high_vol(code, p=None, briefing=None):
    """고변동 종목이면 params.high_vol 설정, 아니면 None. 브리핑의 20일 변동성 > screen.max_vol20 이 기준."""
    p = p or params()
    hv = p.get("high_vol")
    if not hv or not hv.get("enabled"):
        return None
    row = briefing_row(code, briefing) or {}
    v = row.get("vol20")
    return hv if v is not None and v > p["screen"].get("max_vol20", 9) else None


def inverse(code, p=None):
    """인버스 ETF 면 params.inverse 설정, 아니면 None."""
    inv = (p or params()).get("inverse")
    return inv if inv and inv.get("enabled") and code in inv.get("codes", {}) else None


def index_etf(code, p=None):
    """지수추종 ETF 면 params.index 설정, 아니면 None."""
    ix = (p or params()).get("index")
    return ix if ix and ix.get("enabled") and code in ix.get("codes", {}) else None


def market_etf(code, p=None):
    """시장 ETF(인버스·지수추종)면 (설정, '인버스' | '지수'), 아니면 (None, None). 둘 다 국면·하루 매수 횟수·짧은 익절 규칙을 씀."""
    p = p or params()
    if inv := inverse(code, p):
        return inv, "인버스"
    if ix := index_etf(code, p):
        return ix, "지수"
    return None, None


def stock_value(holdings, p=None):
    """국면 비중 상한에 들어가는 평가금액 = 인버스를 뺀 보유 종목 합 (인버스는 inverse.weight_cap 이 따로 막음)."""
    p = p or params()
    return sum(h["value"] for h in holdings if not inverse(h["code"], p))


def buys_today(code):
    """오늘 이 종목을 산 횟수 (체결 기록 기준)."""
    t = today().isoformat()
    return sum(1 for r in read_jsonl(JOURNAL)
               if r["kind"] == "fill" and r.get("side") == "매수" and r.get("code") == code and r["time"].startswith(t))


def gross_take(net, p=None, tax=None):
    """수수료·세금을 뺀 순익 net 을 내려면 매수가 대비 몇 % 올라야 하는지.
    순익 = 매도가 × (1 − 수수료 − 세금) ÷ (매수가 × (1 + 수수료)) − 1"""
    c = (p or params())["costs"]
    tax = c["sell_tax_rate"] if tax is None else tax
    return (1 + net) * (1 + c["fee_rate"]) / (1 - c["fee_rate"] - tax) - 1


def position_meta(holdings, p=None):
    """positions.json 의 손절가·익절가·최대 보유일. 시장 ETF(인버스·지수)는 매수 때 기록한 값 대신 평단 기준으로 지금 규칙을 적용
    (11-04 10:33 에 산 인버스가 예전 규칙 +15% · 10일로 기록돼 있었음). 익절가는 순익이 기준을 넘도록 올림."""
    p = p or params()
    meta = read_json(POSITIONS, {}) or {}
    for h in holdings:
        etf, m = market_etf(h["code"], p)[0], meta.get(h["code"])
        if etf and m and h.get("avg_price"):
            sl, tp, md = exit_levels(h["code"], p)
            meta[h["code"]] = {**m, "stop": round(h["avg_price"] * (1 + sl)), "take": math.ceil(h["avg_price"] * (1 + tp) - 1e-9), "max_days": md}
    return meta


def exit_levels(code, p=None, briefing=None):
    """(손절 %, 익절 %, 최대 보유일). 고변동 종목은 손절·익절 폭이 넓고, 시장 ETF(인버스·지수)는 익절·보유일이 짧음."""
    p = p or params()
    d, hv = p["decision"], high_vol(code, p, briefing)
    if etf := market_etf(code, p)[0]:
        return d["stop_loss_pct"], gross_take(etf["take_profit_net_pct"], p, etf.get("sell_tax_rate")), etf.get("max_hold_days", d["max_hold_days"])
    if hv:
        return hv["stop_loss_pct"], hv["take_profit_pct"], d["max_hold_days"]
    return d["stop_loss_pct"], d["take_profit_pct"], d["max_hold_days"]


def conf_boost(code, side, conf, p=None, briefing=None, regime=None):
    """확신도 보정 (보정 후 확신도, 보정 설명 또는 None). plan_order·리스크 검사·체결 기록이 같은 함수를 써서 결과가 항상 같음.
    1. RSI(14): 매수 RSI < buy_below(과매도) → + add (악재 뉴스 ⚠ 있으면 제외), 매도 RSI ≥ sell_at(과열) → + add.
       장중이면 지금 가격을 오늘 종가로 본 RSI(rsi14_live, intraday.py 가 채움), 없으면 전일 종가 RSI.
    2. 시장 하락: 오늘 국면이 market_boost.regimes 중 하나면 매수 + add (악재 뉴스 ⚠ 있으면 제외)."""
    p = p or params()
    conf = float(conf or 0)
    if side not in ("매수", "매도"):
        return conf, None
    b = briefing if briefing is not None else (read_json(BRIEFING, {}) or {})
    row = next((r for r in b.get("candidates", []) + b.get("holdings", []) if r.get("code") == code), None) or {}
    bad_news = any(n.get("risk") for n in row.get("news", []))
    add, notes = 0.0, []
    cfg = p.get("rsi_boost")
    live = row.get("rsi14_live") is not None
    rsi = row.get("rsi14_live") if live else row.get("rsi14")
    tag = "장중 RSI" if live else "RSI"
    if cfg and rsi is not None:
        if side == "매수" and rsi < cfg["buy_below"]:
            if bad_news:
                notes.append(f"{tag} {rsi} 과매도지만 악재 뉴스로 보정 안 함")
            else:
                add += cfg["add"]
                notes.append(f"{tag} {rsi} < {cfg['buy_below']} 과매도 매수 +{cfg['add']:.2f}")
        elif side == "매도" and rsi >= cfg["sell_at"]:
            add += cfg["add"]
            notes.append(f"{tag} {rsi} ≥ {cfg['sell_at']} 과열 매도 +{cfg['add']:.2f}")
    mb = p.get("market_boost")
    if mb and side == "매수":
        regime = regime if regime is not None else (latest_regime() or {}).get("regime")
        if regime in mb["regimes"]:
            if bad_news:
                notes.append(f"{regime} 국면이지만 악재 뉴스로 보정 안 함")
            else:
                add += mb["add"]
                notes.append(f"{regime} 국면 매수 +{mb['add']:.2f}")
    return round(min(1.0, conf + add), 3), (" · ".join(notes) or None)


def _slot(t=None):
    """지금을 15분 단위로 내린 'HH:MM' (작업 스케줄러가 몇 초 늦게 시작해도 같은 회차로)."""
    t = t or now()
    return f"{t.hour:02d}:{t.minute // 15 * 15:02d}"


def trade_slot(t=None, p=None):
    """이번 정기 판단 회차가 주문까지 하는 회차인지 (params.schedule.trade_times). 없으면 모든 회차가 매매."""
    times = (p or params())["schedule"].get("trade_times")
    return not times or _slot(t) in times


def missed_trade(t=None, p=None, rows=None):
    """직전 매매 시각 이후 오늘 매매 실행이 한 번도 없었으면 그 시각, 있었으면 None.
    작업 스케줄러가 그 회차를 안 돌렸거나(일정 변경·PC 꺼짐), 앞 실행 때문에 건너뛰었거나, 국면 기록 전에 실패한 경우
    다음 판단 회차가 대신 매매함. 매매 실행 = RUN_MODE decide 로 남은 국면(regime) 기록."""
    times = (p or params())["schedule"].get("trade_times") or []
    s = _slot(t)
    due = [x for x in times if x < s]
    if not due:
        return None
    last, d = due[-1], (t or now()).date().isoformat()
    rows = read_jsonl(JOURNAL) if rows is None else rows
    done = any(r["kind"] == "regime" and r.get("mode") == "decide" and r["time"].startswith(d) and r["time"][11:16] >= last
               for r in rows)
    return None if done else last


def next_trade_time(t=None, p=None):
    times = (p or params())["schedule"].get("trade_times") or []
    s = _slot(t)
    return next((t for t in times if t > s), None)


def latest_regime():
    """오늘 기록된 마지막 시장 국면 (없으면 None)."""
    t = today().isoformat()
    rows = [r for r in read_jsonl(JOURNAL) if r["kind"] == "regime" and r["time"].startswith(t)]
    return rows[-1] if rows else None
