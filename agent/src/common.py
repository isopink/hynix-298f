"""경로·설정·작업 파일·날짜 계산 등 모든 모듈이 같이 쓰는 도구."""
import json
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
    row = {"kind": kind, "time": stamp(), "run": os.environ.get("RUN_ID", ""), **fields}
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


def rsi_boost(code, side, conf, p=None, briefing=None):
    """과매도 보정. 매수이고 브리핑 RSI(14) < below 이면 확신도 + add (악재 뉴스 ⚠ 있으면 제외).
    (보정 후 확신도, 보정 설명 또는 None). plan_order·리스크 검사가 같은 함수를 써서 결과가 항상 같음."""
    p = p or params()
    cfg = p.get("rsi_boost")
    conf = float(conf or 0)
    if side != "매수" or not cfg:
        return conf, None
    b = briefing if briefing is not None else (read_json(BRIEFING, {}) or {})
    row = next((r for r in b.get("candidates", []) + b.get("holdings", []) if r.get("code") == code), None)
    rsi = row.get("rsi14") if row else None
    if rsi is None or rsi >= cfg["below"]:
        return conf, None
    if any(n.get("risk") for n in row.get("news", [])):
        return conf, f"RSI {rsi} 과매도지만 악재 뉴스로 보정 안 함"
    return round(min(1.0, conf + cfg["add"]), 3), f"RSI {rsi} < {cfg['below']} 과매도 +{cfg['add']:.2f}"


def latest_regime():
    """오늘 기록된 마지막 시장 국면 (없으면 None)."""
    t = today().isoformat()
    rows = [r for r in read_jsonl(JOURNAL) if r["kind"] == "regime" and r["time"].startswith(t)]
    return rows[-1] if rows else None
