"""
그림자 운영 비교 (11-08 S.Lee): 실제 매매(지금 방식) vs 그림자(온톨로지 버전, 가상 계좌).

    python shadow/compare.py            # 날짜별 표
    python shadow/compare.py --md out.md

같은 출발 계좌(그림자 첫날 실제 계좌 복사)에서 날짜별 자산·수익률·체결·판단 수·실행 시간·토큰을 나란히 봅니다.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))
import common as C  # noqa: E402

C.load_env()


def jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def side(root, start):
    w = os.path.join(root, "agent", "work")
    rows = [r for r in jsonl(os.path.join(w, "journal.jsonl")) if r.get("time", "")[:10] >= start]
    runs = [r for r in jsonl(os.path.join(w, "runs.jsonl")) if str(r.get("time", r.get("start", "")))[:10] >= start]
    eq = {e["date"]: e for e in (C.read_json(os.path.join(root, "docs", "data", "equity.json"), []) or [])}
    by = defaultdict(lambda: {"fills": 0, "buys": 0, "sells": 0, "decisions": 0, "watch": 0, "runs": 0, "fail": 0, "sec": 0, "tokens": 0})
    for r in rows:
        d = by[r["time"][:10]]
        if r["kind"] == "fill":
            d["fills"] += 1
            d["buys" if r.get("side") == "매수" else "sells"] += 1
        elif r["kind"] == "decision" and r.get("mode") == "decide":
            d["decisions"] += 1
            d["watch"] += r.get("action") == "관망"
    for r in runs:
        d = by[str(r.get("time", r.get("start", "")))[:10]]
        d["runs"] += 1
        d["fail"] += not r.get("ok", True)
        d["sec"] += r.get("sec", 0) or 0
        d["tokens"] += r.get("tokens", 0) or 0
    for day, e in eq.items():
        if day >= start:
            by[day]["total"] = e.get("total")
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    a = ap.parse_args()
    real = os.environ.get("SHADOW_OF")
    if not real:
        sys.exit("agent/.env 에 SHADOW_OF=<실제 저장소 경로> 가 없음 (그림자 폴더에서 실행할 것)")
    seed = C.read_json(os.path.join(C.WORK, "mock_account.json"), {}) or {}
    start = (seed.get("seeded_at") or C.today().isoformat())[:10]
    base = seed.get("seed_total")
    R, S = side(real, start), side(C.ROOT, start)
    days = sorted(set(R) | set(S))
    head = "| 날짜 | 지금 방식 자산 | 온톨로지 자산 | 수익률 차 | 체결 (지금 / 온톨) | 관망 (지금 / 온톨) | 판단 1회 평균 (지금 / 온톨) | 토큰 k (지금 / 온톨) | 실패 (지금 / 온톨) |"
    lines = [f"그림자 운영 비교 · 시작 {start} · 출발 자산 {base:,.0f}원" if base else f"그림자 운영 비교 · 시작 {start}", "",
             head, "|" + "---|" * 9]
    for d in days:
        r, s = R[d], S[d]
        rt, st = r.get("total"), s.get("total")
        diff = f"{(st - rt) / base:+.2%}" if base and rt and st else "-"
        avg = lambda x: f"{x['sec'] / x['runs'] / 60:.1f}분" if x["runs"] else "-"   # noqa: E731
        lines.append(f"| {d} | {rt and f'{rt:,.0f}' or '-'} | {st and f'{st:,.0f}' or '-'} | {diff} | {r['fills']} / {s['fills']} | "
                     f"{r['watch']} / {s['watch']} | {avg(r)} / {avg(s)} | {r['tokens'] / 1000:.0f} / {s['tokens'] / 1000:.0f} | {r['fail']} / {s['fail']} |")
    out = "\n".join(lines)
    print(out)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(out + "\n")


if __name__ == "__main__":
    main()
