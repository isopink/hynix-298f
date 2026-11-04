"""
장중 감시 (LLM 없음). 1분마다 보유 종목의 손절가·익절가·보유일을 확인하고,
조건에 닿은 종목이 있으면 손절·익절 실행(run.py exit)을 띄웁니다. 주문은 그 실행의 에이전트가 Hook 을 거쳐 냅니다.

키움 호출을 늘리지 않도록 live 모드에서는 live/snapshot.py 가 남긴 last_snapshot.json 만 읽습니다.
"""
import os
import subprocess
import sys
import time

import common as C

STATE = os.path.join(C.WORK, "monitor_state.json")
RETRY_SEC = 10 * 60   # 매도 실행 뒤에도 잔고에 남아 있으면 이만큼 지나서 다시


def holdings():
    if C.mode() == "live":
        snap = C.read_json(os.path.join(C.LIVE, "last_snapshot.json"))
        if not snap or time.time() - snap.get("epoch", 0) > 15 * 60:
            return None
        return snap["holdings"]
    import broker
    return broker.get().account()["holdings"]


def triggers(hs):
    """{code: (매수 건 키, 사유)}. 키는 진입일·손절가·익절가로 만들어 다시 사거나 더 사면 새 건으로 봄."""
    meta = C.position_meta(hs)
    hit = {}
    for h in hs:
        m = meta.get(h["code"])
        if not m:
            continue
        key = f"{h['code']}@{m.get('entry_date')}/{m.get('stop')}/{m.get('take')}"
        if m.get("stop") and h["price"] <= m["stop"]:
            hit[h["code"]] = (key, f"{h['name']} 현재가 {h['price']:,} ≤ 손절가 {m['stop']:,}")
        elif m.get("take") and h["price"] >= m["take"]:
            hit[h["code"]] = (key, f"{h['name']} 현재가 {h['price']:,} ≥ 익절가 {m['take']:,}")
        elif m.get("entry_date") and C.business_days(m["entry_date"], C.today()) >= m.get("max_days", 99):
            hit[h["code"]] = (key, f"{h['name']} 보유 {C.business_days(m['entry_date'], C.today())}일 ≥ 최대 {m['max_days']}일")
    return hit


def check_once():
    hs = holdings()
    if hs is None:
        print("  (최근 잔고 스냅샷이 없어 건너뜀)", flush=True)
        return
    hit = triggers(hs)
    st = C.read_json(STATE, {}) or {}
    if st.get("date") != C.today().isoformat() or not isinstance(st.get("fired"), dict):
        st = {"date": C.today().isoformat(), "fired": {}}
    n = C.now()
    hm, t = n.hour * 100 + n.minute, time.time()

    def due(key):
        # 같은 매수 건은 실행 뒤 RETRY_SEC 동안 다시 띄우지 않음 (매도 체결 전 중복 주문 방지).
        # 장 전(08:30~09:00)에 낸 매도는 09:00 동시호가로 체결되거나 거절될 수 있음 → 장 전엔 한 번만, 09:05 뒤 남아 있으면 다시
        at = st["fired"].get(key)
        return at is None or (hm >= 905 and t - at >= RETRY_SEC)

    new = {c: why for c, (key, why) in hit.items() if due(key)}
    if not new:
        return
    print(f"[{C.now().strftime('%H:%M')}] 조건 도달: " + " / ".join(new.values()), flush=True)
    r = subprocess.run([sys.executable, os.path.join(C.AGENT, "run.py"), "exit",
                        "--codes", ",".join(new), "--why", " / ".join(new.values())], cwd=C.AGENT)
    if r.returncode == 0:   # 실행이 잠금으로 건너뛰었으면 다음 회차에 다시
        st["fired"].update({hit[c][0]: t for c in new})
        C.write_json(STATE, st)


def loop():
    s = C.params()["schedule"]
    start, end = (int(t.replace(":", "")) for t in (s["monitor_start"], s["monitor_end"]))
    print(f"장중 감시 시작 · {s['monitor_interval_sec']}초 간격 · {s['monitor_end']} 종료", flush=True)
    while True:
        n = C.now()
        hm = n.hour * 100 + n.minute
        if n.weekday() >= 5 or hm > end:
            print("감시 종료", flush=True)
            return
        if hm >= start:
            try:
                check_once()
            except Exception as e:  # noqa: BLE001
                print(f"  ! 감시 실패: {e}", flush=True)
        time.sleep(s["monitor_interval_sec"])
