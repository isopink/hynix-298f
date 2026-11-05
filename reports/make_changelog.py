"""전략 변경 로그 → 저장소 맨 위 CHANGELOG.md (팀 공유용).
reports/week1/changes.tsv 의 '전략' 줄만, git 커밋 시각(KST)으로 날짜별 정리. 최신이 위.
쉬운 설명은 reports/changelog_plain.tsv (해시 → 분야 · 무엇을 · 왜), 맨 위 "지금 전략 한눈에"는 params.json 에서 계산.
실행: python reports/make_changelog.py
"""
import json
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

PLAIN = {}
for line in open(os.path.join(ROOT, "reports", "changelog_plain.tsv"), encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    h, area, what, why = line.rstrip("\n").split("\t", 3)
    PLAIN[h] = (area, what, why)

by_day = defaultdict(list)
for d, t, h, text in sorted(rows, reverse=True):
    by_day[d].append((t, h, text))

P = json.load(open(os.path.join(ROOT, "agent", "config", "params.json"), encoding="utf-8"))
R = json.load(open(os.path.join(ROOT, "agent", "config", "risk_limits.json"), encoding="utf-8"))
dc, cap, ix, inv = P["decision"], P["regime_cap"], P.get("index", {}), P.get("inverse", {})
buy = dc["buy_min_confidence"]
pf = (dc.get("probe") or {})
pct = lambda v: f"{v * 100:.0f}%"
pctp = lambda v: f"{v * 100:+.0f}%"

out = ["# 전략 변경 로그", "",
       "Sigma Six 트레이딩 AI가 **언제, 무엇을, 왜** 바꿨는지 쉬운 말로 정리한 기록입니다. 대시보드·운영 변경은 빼고 매매 규칙만 담았습니다.", "",
       "## 지금 전략 한눈에", "",
       "| 항목 | 지금 규칙 |", "|---|---|",
       f"| 언제 사고파나 | 평일 09:30 ~ 15:15, **15분마다** AI가 판단하고 바로 주문 (하루 24번) |",
       f"| 어떻게 정하나 | '사자' 쪽 AI와 '팔자' 쪽 AI가 토론 → 총괄 AI가 **확신도**(0~1 점수)를 매김 |",
       f"| 언제 사나 | 확신도 **{buy:.2f} 이상**이면 매수, 아깝게 못 미치면({buy - pf.get('band', 0):.2f}~{buy:.2f}) {pf.get('weight', 0) * 100:.1f}%만 조금 매수 |",
       f"| 한 종목에 얼마나 | 보통 {pct(dc['min_weight'])}~{pct(dc['max_weight'])} (확신할수록 크게), 최대 {R['max_positions']}종목에 나눠 담음 |",
       f"| 시장 분위기별 투자 한도 | 상승장 {pct(cap['상승'])} · 옆걸음 {pct(cap['횡보'])} · 하락장 {pct(cap['하락'])} (나머지는 현금) |",
       f"| 언제 파나 | 팔자 확신도 {dc['sell_min_confidence']:.2f} 이상이면 매도 (애매하면 절반만) · 손절 {pctp(dc['stop_loss_pct'])} · 익절 {pctp(dc['take_profit_pct'])} · 최대 {dc['max_hold_days']}일 보유 |",
       f"| 하락장 대비 | 인버스(시장이 내리면 오르는 상품)를 하락장에서만 최대 {pct(inv.get('weight_cap', 0))} |",
       f"| 시장 전체 투자 | KODEX 200(코스피 대형주 200개 묶음)을 최대 {pct(ix.get('weight_cap', 0))}, 폭락한 날(−3% 이하)엔 하락장이어도 마감 직전에 매수 가능 |",
       f"| 절대 안 넘는 선 | 하루 손실 {pctp(R['daily_loss_limit'])}면 그날 매수 중단 · 현금 {pct(R['min_cash_ratio'])} 이상 유지 · 한 종목 최대 {pct(R['max_weight_per_stock'])} |",
       f"| 스스로 고치기 | 매일 16:00 AI가 성과를 보고 기준값을 조금씩 조정 (결과는 대시보드 Feedback Loop) |", "",
       "<details><summary>용어 풀이</summary>", "",
       "- **확신도**: AI가 '이 종목을 사야 한다(또는 팔아야 한다)'고 얼마나 확신하는지 0~1 점수. 1에 가까울수록 확실",
       "- **국면**: 지금 시장이 상승장 · 옆걸음(횡보) · 하락장 중 어디인지",
       "- **손절 / 익절**: 정해둔 만큼 떨어지면 손해를 끊고 팔기 / 정해둔 만큼 오르면 이익을 확정하고 팔기",
       "- **RSI**: 최근 얼마나 많이 오르거나 내렸는지 보는 지표. 낮으면 '많이 빠짐(과매도)', 높으면 '많이 오름(과열)'",
       "- **인버스 / KODEX 200**: 코스피가 내리면 오르는 상품 / 코스피 대형주 200개를 한 번에 사는 상품",
       "- **회전율**: 얼마나 자주 사고팔았는지. 대회 순위가 같을 때 비교 기준",
       "- **5·20일선**: 최근 5일·20일 평균 주가. 지금 가격이 이보다 위면 오르는 흐름으로 봄",
       "", "</details>", "",
       "## 변경 기록 (최신이 위)", ""]
import datetime as dt
for d in sorted(by_day, reverse=True):
    w = WD[dt.date.fromisoformat(d).weekday()]
    out += [f"### {d[5:].replace('-', '/')} ({w}) · {len(by_day[d])}건", "", "| 시각 | 분야 | 무엇을 바꿨나 | 왜 |", "|:---:|:---:|---|---|"]
    for t, h, text in by_day[d]:
        area, what, why = PLAIN.get(h, ("", text, ""))
        out.append(f"| {t} | {area} | {what.replace('|', '/')} | {why.replace('|', '/')} |")
    out.append("")
out += ["---", "커밋 단위 원문은 [reports/week1/changes.tsv](reports/week1/changes.tsv)에 있습니다.", ""]
open(OUT, "w", encoding="utf-8").write("\n".join(out))
miss = [h for _, _, h, _ in rows if h not in PLAIN]
print(f"CHANGELOG.md: 전략 변경 {len(rows)}건, {len(by_day)}일" + (f" · 쉬운 설명 없음 {len(miss)}건: {' '.join(miss)}" if miss else ""))
