"""
코드 자동 동기화 (LLM 없음). 노트북에서 push 한 수정을 이 PC가 1분 안에 받아 반영합니다.

  1분마다 git fetch → 새 커밋이 있으면
    1) 받은 코드를 임시 폴더에 풀어 문법·JSON·import 검사 (실패하면 그 커밋은 반영하지 않음)
    2) 판단·손절 실행이 도는 중(run.lock)이면 끝날 때까지 기다림
    3) rebase 로 반영 (에이전트가 아직 못 올린 docs/data 커밋은 위에 다시 얹고 push)
    4) 장중이면 바뀐 코드에 맞춰 장중 감시(monitor)·잔고 루프(snapshot)를 재시작
  장중에 monitor·snapshot 이 꺼져 있으면 다시 켬 (5분에 한 번까지)

상태는 work/sync_state.json → logger 가 status.json 의 sync 로 내보내 대시보드에 표시.
sync.py 자신이 바뀌면 종료 코드 10 으로 끝나고, run.py 가 새 코드로 다시 띄움.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import common as C

STATE = os.path.join(C.WORK, "sync_state.json")
LOCK = os.path.join(C.WORK, "run.lock")
PIDLOCK = os.path.join(C.WORK, "sync.pid")
INTERVAL = 60
SELF = "agent/src/sync.py"

# (이름, 작업 스케줄러 작업, 명령줄에서 찾을 문자열, 이 경로가 바뀌면 재시작, 동작 시간)
LOOPS = [
    ("monitor", "Hynix298-monitor", "run.py monitor", ("agent/src/", "agent/run.py", "agent/config/"), None),
    ("snapshot", "Hynix298-snapshot", "snapshot.py --loop", ("live/snapshot.py",), ("08:25", "15:35")),
]
CHECK_IMPORTS = ["common", "monitor", "broker", "risk", "sizing", "logger", "tuning", "sync"]


def log(msg):
    print(f"[{C.now().strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def git(*args, check=False):
    r = subprocess.run(["git", *args], cwd=C.ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def rev(ref):
    r = git("rev-parse", "--verify", "-q", ref)
    return r.stdout.strip() if r.returncode == 0 else None


def state():
    return C.read_json(STATE, {}) or {}


def save(**kw):
    st = {**state(), **kw, "checked_at": C.stamp()}
    C.write_json(STATE, st)
    return st


# ---------------- 반영 전 검사 ----------------
def precheck(sha):
    """받은 커밋의 agent/·live/ 를 임시 폴더에 풀어 검사. 실패하면 이유 문자열, 통과하면 None."""
    tmp = tempfile.mkdtemp(prefix="sync-")
    try:
        files = git("ls-tree", "-r", "--name-only", sha, "--", "agent", "live", check=True).stdout.split()
        for path in files:
            if not path.endswith((".py", ".json")):
                continue
            data = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=C.ROOT, capture_output=True).stdout
            dst = os.path.join(tmp, *path.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            try:
                text = data.decode("utf-8-sig")
                if path.endswith(".py"):
                    compile(text, path, "exec")
                else:
                    json.loads(text)
            except (SyntaxError, ValueError) as e:
                return f"{path}: {type(e).__name__} {e}"[:300]
        code = f"import sys; sys.path.insert(0, {os.path.join(tmp, 'agent', 'src')!r}); " + \
               "; ".join(f"import {m}" for m in CHECK_IMPORTS)
        r = subprocess.run([sys.executable, "-c", code], cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode != 0:
            return "import 실패: " + (r.stderr.strip().splitlines() or ["?"])[-1][:300]
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_busy():
    """판단·손절 실행이 진행 중이면 True (run.py 와 같은 기준: 30분 안에 만든 잠금)."""
    try:
        return time.time() - os.path.getmtime(LOCK) < 30 * 60
    except OSError:
        return False


# ---------------- 장중 루프 관리 ----------------
def processes(pattern):
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        rows = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    rows = rows if isinstance(rows, list) else [rows]
    return [p["ProcessId"] for p in rows if pattern in (p.get("CommandLine") or "")]


def in_window(win, now=None):
    n = now or C.now()
    if n.weekday() >= 5:
        return False
    if win is None:
        s = C.params()["schedule"]
        win = (s["monitor_start"], s["monitor_end"])
    hm = n.hour * 100 + n.minute
    start, end = (int(t.replace(":", "")) for t in win)
    return start <= hm < end


def start_task(task):
    for _ in range(5):   # 방금 끈 작업이 '실행 중'에서 빠지기까지 몇 초 걸림
        r = subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True, text=True,
                           encoding="mbcs", errors="replace")
        if r.returncode == 0:
            return True
        time.sleep(3)
    log(f"  ! {task} 시작 실패: {(r.stderr or r.stdout).strip()[:200]}")
    return False


def restart(name, task, pattern):
    for pid in processes(pattern):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    time.sleep(2)
    if start_task(task):
        log(f"  {name} 재시작")


def ensure_schedule():
    """정기 판단 작업(Hynix298-decide)의 반복 간격을 params.schedule.interval_min 에 맞춤 (11-06 15분 → 10분).
    설정이 바뀔 때 한 번만 시도 (실패해도 1분마다 다시 하지 않음). 실패하면 setup_tasks.ps1 을 다시 실행해야 함."""
    if os.name != "nt":
        return
    s = C.params()["schedule"]
    times = s.get("trade_times") or []
    if not times:
        return
    k = C.interval_min()
    h0, m0 = map(int, times[0].split(":"))
    h1, m1 = map(int, times[-1].split(":"))
    span = (h1 * 60 + m1) - (h0 * 60 + m0) + 1   # 마지막 회차까지 포함
    dur = f"{span // 60:04d}:{span % 60:02d}"
    want = f"{times[0]}|{k}|{dur}"
    if state().get("decide_schedule") == want:
        return
    save(decide_schedule=want)
    r = subprocess.run(["schtasks", "/Change", "/TN", "Hynix298-decide", "/RI", str(k), "/DU", dur],
                       capture_output=True, text=True, encoding="mbcs", errors="replace", input="", timeout=60)
    if r.returncode == 0:
        log(f"정기 판단 작업을 {times[0]}부터 {k}분마다 {dur} 동안으로 바꿈")
    else:
        log(f"  ! 정기 판단 간격 변경 실패 (setup_tasks.ps1 을 다시 실행할 것): {(r.stderr or r.stdout).strip()[:200]}")


def ensure_review_mid():
    """11-06 S.Lee: 주간 회고를 수·금 15:50 으로 (토 10:00 에서 옮김). 같은 날 16:00 기준값 조정이 회고를 기다렸다 그 제안을 바로 검토
    → 목요일·월요일 장부터 반영. setup_tasks.ps1 을 다시 안 돌려도 되게 sync 가 한 번 등록."""
    if os.name != "nt" or state().get("review_mid") == "WED,FRI 15:50":
        return
    save(review_mid="WED,FRI 15:50")
    subprocess.run(["schtasks", "/Delete", "/TN", "Hynix298-review-mid", "/F"], capture_output=True, input="", timeout=60)   # 잠깐 쓰던 수요일 전용 작업
    bat = os.path.join(C.AGENT, "run.bat")
    r = subprocess.run(["schtasks", "/Create", "/TN", "Hynix298-review", "/TR", f'"{bat}" review', "/SC", "WEEKLY", "/D", "WED,FRI", "/ST", "15:50", "/F"],
                       capture_output=True, text=True, encoding="mbcs", errors="replace", input="", timeout=60)
    log("주간 회고 작업을 수·금 15:50 으로 등록" if r.returncode == 0 else f"  ! 중간 회고 작업 등록 실패 (setup_tasks.ps1 을 다시 실행할 것): {(r.stderr or r.stdout).strip()[:200]}")


_last_heal = {}


def heal():
    """장중에 루프가 꺼져 있으면 다시 켬. 바로 죽는 코드면 재시작이 반복되지 않도록 5분에 한 번까지."""
    for name, task, pattern, _, win in LOOPS:
        if not in_window(win) or processes(pattern) or time.time() - _last_heal.get(name, 0) < 5 * 60:
            continue
        if name == "monitor" and run_busy():
            continue
        _last_heal[name] = time.time()
        log(f"{name} 가 꺼져 있어 다시 켬")
        start_task(task)


# ---------------- 그림자(SiON) 따라잡기 (11-12 S.Lee) ----------------
# 데스크톱이 꺼졌다 켜지면 SiON 은 놓친 회차를 다시 돌리지 않았음 (11-11 11:15 뒤로 멈춤).
# 이 sync 는 로그온부터 늘 도니까 여기서 SiON 작업(Hynix298S-*)을 살핌. 같은 일은 한 번만 시도.
_shadow_tried = {}


def shadow_root():
    d = os.environ.get("SHADOW_DIR") or os.path.join(os.path.dirname(C.ROOT), "hynix-shadow")
    return d if os.path.isfile(os.path.join(d, "agent", "run.py")) else None


def task_running(task):
    r = subprocess.run(["schtasks", "/Query", "/TN", task, "/FO", "CSV", "/NH"], capture_output=True, text=True,
                       encoding="mbcs", errors="replace")
    out = r.stdout or ""
    return "Running" in out or "실행 중" in out


def shadow_heal(now=None):
    if not (C.params().get("sion") or {}).get("enabled", True):   # 11-12 S.Lee: SiON 멈춤
        return None
    d = shadow_root()
    n = now or C.now()
    if not d or n.weekday() >= 5:
        return None
    hm, today = n.strftime("%H:%M"), n.date().isoformat()
    w = os.path.join(d, "agent", "work")

    def kick(task, key, why):
        name = "Hynix298S-" + task
        if _shadow_tried.get(name) == key or task_running(name):
            return None
        _shadow_tried[name] = key
        log(f"SiON {why} → {name} 시작")
        return name if start_task(name) else None

    s = C.params()["schedule"]
    if "08:40" <= hm < s.get("monitor_end", "15:20"):
        b = C.read_json(os.path.join(w, "briefing.json"), {}) or {}
        if str(b.get("created", ""))[:10] != today:
            return kick("prep", today, "오늘 준비가 없음")
        if not task_running("Hynix298S-monitor"):   # 10분에 한 번까지
            r = kick("monitor", f"{today} {hm[:4]}", "감시가 꺼져 있음")
            if r:
                return r
        rows = C.read_jsonl(os.path.join(w, "journal.jsonl"))
        missed = C.missed_trade(n, None, rows)
        if missed:
            return kick("decide", f"{today} {missed}", f"{missed} 회차를 놓침")
    elif "15:55" <= hm:
        eq = C.read_json(os.path.join(d, "docs", "data", "equity.json"), []) or []
        if not eq or eq[-1].get("date") != today:
            return kick("close", today, "오늘 마감 기록이 없음")
        if hm >= "17:00":
            rows = C.read_jsonl(os.path.join(w, "journal.jsonl"))
            if not any(r.get("kind") == "tune" and str(r.get("time", "")).startswith(today) for r in rows):
                return kick("tune", today, "오늘 기준값 조정이 없음")
    return None


# ---------------- 한 회차 ----------------
def once():
    if git("fetch", "-q", "origin").returncode != 0:
        log("  fetch 실패 (네트워크?) · 다음 회차에 다시")
        return False
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remote = rev(f"origin/{branch}")
    if not remote:
        return False
    base = git("merge-base", "HEAD", remote).stdout.strip()
    if base == remote:   # 받을 것 없음. 에이전트 커밋이 못 올라갔으면 올림
        if rev("HEAD") != remote:
            r = git("push", "-q")
            if r.returncode == 0:
                log("밀린 에이전트 커밋 push")
        save(ok=True, error=None, head=rev("HEAD")[:7])
        return False

    st = state()
    if st.get("rejected") == remote:
        return False     # 이미 검사에서 떨어진 커밋. 새 커밋이 올라올 때까지 대기
    err = precheck(remote)
    if err:
        log(f"반영 안 함 ({remote[:7]}): {err}")
        save(ok=False, error=f"{remote[:7]} 검사 실패 · {err}", rejected=remote)
        return False
    while run_busy():
        log("  판단·손절 실행 중이라 끝나길 기다림")
        heartbeat()   # 11-12 기다리는 동안에도 연결 신호 (판단 중에 push 하면 최대 15분 신호가 끊겨 Server 가 빨강이던 것)
        time.sleep(20)

    # 지난 rebase 가 충돌난 채로 남은 파일이 있으면 autostash 가 안 돼 계속 실패함 (11-03 docs/index.html).
    # 이 PC는 코드를 고치지 않으므로 docs/data 밖의 충돌 파일은 마지막 커밋 상태로 되돌림
    for f in git("diff", "--name-only", "--diff-filter=U").stdout.split():
        if not f.startswith("docs/data/"):
            git("checkout", "HEAD", "--", f)
            log(f"  충돌 상태로 남은 {f} 를 마지막 커밋 상태로 되돌림")

    changed = git("diff", "--name-only", base, remote).stdout.split()
    # PC가 커밋하는 건 에이전트 기록(docs/data·params.json)뿐이라, 같은 줄이 겹치면 PC 쪽(방금 만든 기록)을 씀
    r = git("rebase", "--autostash", "-X", "theirs", "-q", remote)
    if r.returncode != 0:
        git("rebase", "--abort")
        msg = (r.stderr or r.stdout).strip().splitlines()
        if "index.lock" in r.stderr:   # 에이전트가 같은 순간 커밋하는 중. 다음 회차에 다시
            log("  에이전트 커밋과 겹쳐 다음 회차에 다시")
            return False
        log("rebase 실패 (충돌 등) · 반영 안 함: " + " / ".join(msg[-3:]))
        # 검사 실패와 달리 rejected 로 막지 않음: 작업 트리 문제는 고쳐지면 다음 회차에 바로 반영되게
        save(ok=False, error=f"{remote[:7]} rebase 실패 · " + (msg[-1] if msg else "?")[:200])
        return False
    if rev("HEAD") != remote:
        git("push", "-q")
    log(f"반영 {base[:7]} → {remote[:7]} · {len(changed)}개 파일")
    save(ok=True, error=None, rejected=None, head=rev("HEAD")[:7], applied_at=C.stamp())

    for name, task, pattern, paths, win in LOOPS:
        if any(f.startswith(paths) for f in changed) and in_window(win):
            if name == "monitor":
                while run_busy():   # 감시가 띄운 손절 실행이 끝난 뒤에 끔
                    heartbeat()
                    time.sleep(20)
            restart(name, task, pattern)
    return SELF in changed


def single_instance():
    """sync 가 두 개 뜨지 않도록 잠금 파일을 프로세스가 살아 있는 동안 잡아 둠."""
    import msvcrt
    os.makedirs(C.WORK, exist_ok=True)
    f = open(PIDLOCK, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return f


def catch_up(now=None):
    """놓친 매매 회차를 다음 회차까지 기다리지 않고 바로 보충 (11-05 09:45 사고 뒤 추가).
    매매 회차가 실패·건너뜀으로 국면 기록 없이 끝났으면(C.missed_trade) 정기 판단 작업을 지금 한 번 더 띄움.
    같은 회차·같은 코드로는 한 번만 시도 → 코드 버그로 계속 실패해도 1분마다 토큰을 쓰지 않음.
    수정 코드가 반영되면(HEAD 가 바뀌면) 다시 한 번 시도 = '복구되자마자 매매'."""
    n = now or C.now()
    s = C.params()["schedule"]
    times = s.get("trade_times") or []
    if not times or not in_window((times[0], s.get("monitor_end", "15:20")), n):
        return False
    missed = C.missed_trade(n)
    if not missed or run_busy():
        return False
    key = f"{n.date().isoformat()} {missed} {rev('HEAD')[:7]}"
    if state().get("catch_up") == key:
        return False
    save(catch_up=key)
    log(f"{missed} 매매 회차가 실행되지 않아 지금 보충 매매를 띄움 ({key})")
    return start_task("Hynix298-decide")


_HB = {"env": None, "fail": 0}


def heartbeat():
    """11-11 S.Lee: 대시보드 'Server' 점. 데스크톱이 켜져 있으면 1분마다 Supabase heartbeat 표에 신호 (supabase/heartbeat.sql).
    live/.env 의 SUPABASE_URL · SUPABASE_ANON_KEY · SNAPSHOT_SECRET 을 씀. 실패해도 동기화는 계속."""
    import socket
    import urllib.request
    if _HB["env"] is None:
        env = {}
        try:
            with open(os.path.join(C.ROOT, "live", ".env"), encoding="utf-8") as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            pass
        _HB["env"] = env
    env = _HB["env"]
    url, key, secret = env.get("SUPABASE_URL"), env.get("SUPABASE_ANON_KEY"), env.get("SNAPSHOT_SECRET")
    if not (url and key and secret):
        return
    body = json.dumps({"p_secret": secret, "p_host": "desktop",
                       "p_info": {"pc": socket.gethostname()[:30], "sync": (rev("HEAD") or "")[:7]}}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/rpc/push_heartbeat", data=body, method="POST",
                                 headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8).read()
        _HB["fail"] = 0
    except Exception as e:  # noqa: BLE001
        _HB["fail"] += 1
        if _HB["fail"] in (1, 30):   # 같은 실패를 매분 찍지 않음
            log(f"  ! 연결 신호 실패: {type(e).__name__}: {str(e)[:120]}")


def loop():
    keep = single_instance()
    if not keep:
        log("이미 다른 sync 가 실행 중이라 종료")
        return 0
    log(f"코드 동기화 시작 · {INTERVAL}초 간격 · {C.ROOT}")
    while True:
        try:
            heartbeat()
        except Exception:  # noqa: BLE001
            pass
        try:
            if once():
                log("sync.py 가 바뀌어 새 코드로 다시 시작")
                return 10
            heal()
            ensure_schedule()
            ensure_review_mid()
            catch_up()
            shadow_heal()   # 11-12 SiON 놓친 작업 따라잡기
        except Exception as e:  # noqa: BLE001
            log(f"  ! 동기화 실패: {type(e).__name__}: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    if "--once" in sys.argv:
        once()
    elif "--check" in sys.argv:
        print(precheck(sys.argv[-1]) or "통과")
    else:
        sys.exit(loop())
