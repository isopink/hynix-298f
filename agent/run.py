"""
에이전트 실행기. 작업 스케줄러가 run.bat 을 통해 부릅니다.

  python run.py prep                  08:30  계좌 조회 + 데이터 준비 (LLM 없음)
  python run.py decide                09:30 · 11:00 · 14:30  정기 판단 (Claude Code 헤드리스)
  python run.py exit --codes A,B      장중 감시가 손절·익절 조건을 보면 호출 (매도만)
  python run.py close                 15:45  계좌 조회 + 오늘 자산을 equity 에 기록
  python run.py review                토 10:00  주간 회고
  python run.py monitor               09:05~15:20  장중 감시 루프 (src/monitor.py)

  --dry   Claude 를 부르지 않고 명령만 출력
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))
import common as C  # noqa: E402

C.load_env()
PY = sys.executable
LOCK = os.path.join(C.WORK, "run.lock")

TOOLS_ALLOW = ["mcp__kiwoom__get_briefing", "mcp__kiwoom__get_account", "mcp__kiwoom__set_regime",
               "mcp__kiwoom__plan_order", "mcp__kiwoom__place_order", "mcp__kiwoom__record_decision",
               "mcp__kiwoom__submit_review", "Agent", "Task", "WebSearch", "Read"]
TOOLS_DENY = ["Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch"]

PROMPTS = {
    "decide": "정기 판단 실행입니다 ({time}). CLAUDE.md 의 'A. 정기 판단' 순서대로 진행하세요.",
    "exit": "손절·익절 실행입니다 ({time}). 대상 종목: {codes}. 감시 사유: {why}. CLAUDE.md 의 'B. 손절·익절 실행' 순서대로 진행하세요.",
    "review": "주간 회고 실행입니다 ({time}). 대회 {week}주차, 기간 {period}. CLAUDE.md 의 'C. 주간 회고' 순서대로 진행하세요.",
}


def log(msg):
    print(f"[{C.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def py(script, *args):
    r = subprocess.run([PY, os.path.join(HERE, "src", script), *args], cwd=HERE)
    return r.returncode == 0


def refresh_account():
    import broker
    acc = broker.get().account()
    log(f"계좌 {C.mode()} · 총자산 {acc['total']:,} · 현금 {acc['cash']:,} · {len(acc['holdings'])}종목")


# ---------------- 잠금 (실행 두 개가 동시에 주문하지 않도록) ----------------
def acquire():
    os.makedirs(C.WORK, exist_ok=True)
    try:
        if time.time() - os.path.getmtime(LOCK) < 30 * 60:
            return False
    except OSError:
        pass
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    return True


def release():
    try:
        os.remove(LOCK)
    except OSError:
        pass


# ---------------- Claude Code 헤드리스 ----------------
def mcp_config():
    """.mcp.json 을 절대 경로로 바꿔 work/ 에 씀 (스케줄러가 어떤 폴더에서 부르든 서버가 뜨도록)."""
    path = os.path.join(C.WORK, "mcp.json")
    C.write_json(path, {"mcpServers": {"kiwoom": {
        "command": PY, "args": [os.path.join(HERE, "src", "mcp_server.py")], "env": {"MODE": C.mode()}}}})
    return path


# 실행이 정말 일을 했는지: 에이전트가 끝까지 갔다면 이 종류의 기록이 하나 이상 남아 있어야 함
EXPECT = {"decide": {"regime"}, "exit": {"fill", "decision", "block"}, "review": {"review"}}


def did_work(kind, run_id):
    return any(r.get("run") == run_id and r["kind"] in EXPECT[kind] for r in C.read_jsonl(C.JOURNAL))


SUMMARY = re.compile(r"(상승|횡보|하락)\s*/\s*매수\s*\d+건\s*/\s*매도\s*\d+건\s*/\s*관망\s*\d+건")


def summary_line(text):
    """대시보드 상태 문구. 에이전트 출력의 '국면 / 매수 n건 / 매도 n건 / 관망 n건' 줄을 쓰고,
    없으면 첫 줄(마크다운 기호 제거)을 씀. 마지막 줄을 쓰면 할 일 목록 같은 게 그대로 노출됨."""
    text = (text or "").strip()
    m = SUMMARY.search(text)
    if m:
        return m.group(0)
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return re.sub(r"^[\s>*#\-⚠]+|\*\*", "", first).strip()[:120]


def claude(kind, prompt, dry=False):
    run_id = f"{C.now().strftime('%Y%m%d-%H%M')}-{kind}"
    exe = shutil.which("claude")
    cmd = [exe or "claude", "-p", prompt, "--output-format", "json",
           "--mcp-config", mcp_config(), "--strict-mcp-config",
           "--allowedTools", *TOOLS_ALLOW, "--disallowedTools", *TOOLS_DENY,
           "--max-budget-usd", os.environ.get("MAX_BUDGET_USD", "5")]
    if dry:
        log("DRY: " + " ".join(cmd[:4]) + " ...")
        return True
    env = {**os.environ, "RUN_ID": run_id, "RUN_MODE": kind}
    t0 = time.time()
    rec = {"time": C.stamp(), "run_id": run_id, "kind": kind, "ok": False, "tokens": 0}
    try:
        p = subprocess.Popen(cmd, cwd=HERE, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        try:
            out, err = p.communicate(timeout=25 * 60)
        except subprocess.TimeoutExpired:
            # 자식(MCP 서버, 서브에이전트)까지 통째로 종료. 안 그러면 파이프가 안 닫혀 계속 기다림
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            p.communicate(timeout=30)
            raise
        p.stdout, p.stderr = out, err
        res = json.loads(out or "{}")
        u = res.get("usage") or {}
        rec.update(ok=p.returncode == 0 and not res.get("is_error") and did_work(kind, run_id),
                   tokens=sum(u.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")),
                   cost_usd=res.get("total_cost_usd"), note=summary_line(res.get("result")))
        if not rec["ok"]:
            rec["note"] = ("기록 없음: " if p.returncode == 0 else "") + rec["note"]
        C.write_json(os.path.join(C.WORK, "runs", run_id + ".json"), {"cmd_prompt": prompt, "result": res, "stderr": p.stderr[-2000:]})
    except subprocess.TimeoutExpired:
        rec["note"] = "시간 초과 (25분)"
    except Exception as e:  # noqa: BLE001
        rec["note"] = f"{type(e).__name__}: {e}"[:200]
    rec["sec"] = round(time.time() - t0)
    C.append_jsonl(C.RUNS, rec)
    log(f"{kind} {'완료' if rec['ok'] else '실패'} · {rec['sec']}초 · {rec['tokens'] / 1000:.0f}k 토큰 · {rec.get('note', '')}")
    return rec["ok"]


def publish(msg):
    """docs/data 를 갱신하고, GIT_PUSH=1 이면 커밋·푸시해서 대시보드에 반영."""
    py("logger.py")
    if os.environ.get("GIT_PUSH") != "1":
        return
    paths = ["docs/data", "reports/drafts"]
    subprocess.run(["git", "add", "--", *[p for p in paths if os.path.exists(os.path.join(C.ROOT, p))]], cwd=C.ROOT)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=C.ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=C.ROOT)
    r = subprocess.run(["git", "push", "-q"], cwd=C.ROOT, capture_output=True, text=True)
    log("푸시 완료" if r.returncode == 0 else f"푸시 실패: {r.stderr.strip()[:200]}")


def briefing_fresh():
    b = C.read_json(C.BRIEFING) or {}
    return b.get("created", "").startswith(C.today().isoformat())


def main():
    import argparse
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("kind")
    ap.add_argument("--codes", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    kind, dry = a.kind, a.dry

    if kind == "monitor":
        import monitor
        monitor.loop()
        return
    if kind == "prep":
        refresh_account()
        py("data_prep.py")
        publish(f"Agent prep {C.today().isoformat()}")   # 판단 전에도 대시보드에 오늘 시장 자료가 보이도록
        return
    if kind == "close":
        refresh_account()
        py("logger.py", "--close")
        publish(f"Agent close {C.today().isoformat()}")
        return
    if kind not in PROMPTS:
        sys.exit(f"알 수 없는 실행: {kind}\n{__doc__}")

    if not acquire():
        log("다른 실행이 진행 중이라 건너뜀")
        sys.exit(3)   # 감시 루프가 다음 회차에 다시 시도하도록
    try:
        if kind == "decide" and not briefing_fresh():
            refresh_account()
            py("data_prep.py")
        p = C.params()
        start = p["competition"]["start"]
        prompt = PROMPTS[kind].format(time=C.stamp(), codes=a.codes, why=a.why,
                                      week=C.competition_week(p=p), period=f"{start} 이후 이번 주")
        claude(kind, prompt, dry)
        publish(f"Agent {kind} {C.stamp()}")
    finally:
        release()


if __name__ == "__main__":
    main()
