"""전략 변경 로그 → 저장소 맨 위 CHANGELOG.md (팀 공유용).
reports/week1/changes.tsv 의 '전략' 줄만, git 커밋 시각(KST)으로 날짜별 정리. 최신이 위.
실행: python reports/make_changelog.py
"""
import os
import subprocess
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSV = os.path.join(ROOT, "reports", "week1", "changes.tsv")
OUT = os.path.join(ROOT, "CHANGELOG.md")
WD = "월화수목금토일"


def when(h):
    """커밋 해시 → (YYYY-MM-DD, HH:MM) KST."""
    s = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d %H:%M", h],
                       cwd=ROOT, capture_output=True, text=True, env={**os.environ, "TZ": "Asia/Seoul"}).stdout.strip()
    return tuple(s.split(" ")) if s else (None, None)


rows = []
for line in open(TSV, encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    h, kind, text = line.rstrip("\n").split("\t", 2)
    if kind != "전략":
        continue
    d, t = when(h)
    if d:
        rows.append((d, t, h, text))

by_day = defaultdict(list)
for d, t, h, text in sorted(rows, reverse=True):
    by_day[d].append((t, h, text))

out = ["# 전략 변경 로그", "",
       "Sigma Six 트레이딩 에이전트의 **판단·매매 규칙** 변경만 모은 기록입니다 (대시보드·운영 변경 제외). 최신이 위.",
       "사전 계획서(10-28) 이후부터, 시각은 커밋 시각(KST). 기준값 자동 조정(매일 16:00) 결과는 대시보드 Feedback Loop 에 따로 쌓입니다.", ""]
import datetime as dt
for d in sorted(by_day, reverse=True):
    w = WD[dt.date.fromisoformat(d).weekday()]
    out += [f"## {d[5:].replace('-', '/')} ({w})", ""]
    for t, h, text in by_day[d]:
        out.append(f"- `{t}` {text} ([{h}](https://github.com/isopink/hynix-298f/commit/{h}))")
    out.append("")
open(OUT, "w", encoding="utf-8").write("\n".join(out))
print(f"CHANGELOG.md: 전략 변경 {len(rows)}건, {len(by_day)}일")
