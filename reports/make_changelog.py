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
       "Sigma Six 자동매매 AI의 **운용 규칙 변경 이력**입니다 (대시보드·시스템 운영 변경 제외). 무엇을, 왜 바꿨는지 날짜순으로 정리했습니다.", "",
       "## 현재 운용 규칙 요약", "",
       "| 항목 | 현재 규칙 |", "|---|---|",
       f"| 매매 시점 | 평일 09:30 ~ 15:20, **10분마다** 판단 후 즉시 주문 (하루 36회) |",
       f"| 의사결정 구조 | 매수 논거 AI ⇄ 매도 논거 AI 토론 → 총괄 AI가 **확신도**(0~1) 산출 → 규칙이 수량 결정 |",
       f"| 매수 조건 | 확신도 **{buy:.2f} 이상**. 근소하게 못 미치면({buy - pf.get('band', 0):.2f}~{buy:.2f}) 확신도에 비례해 {pf.get('weight_min', pf.get('weight', 0)) * 100:.0f}~{pf.get('weight', 0) * 100:.0f}% 소액 매수 |",
       f"| 포지션 크기 | 종목당 {pct(dc['min_weight'])}~{pct(dc['max_weight'])} (확신도 비례), 최대 {R['max_positions']}종목 분산 |",
       f"| 국면별 주식 비중 상한 | 상승 {pct(cap['상승'])} · 횡보 {pct(cap['횡보'])} · 하락 {pct(cap['하락'])} |",
       f"| 매도 조건 | 매도 확신도 {dc['sell_min_confidence']:.2f} 이상 (0.65 미만은 절반 분할 매도) · 손절 {pctp(dc['stop_loss_pct'])} · 익절 {pctp(dc['take_profit_pct'])} · 최대 {dc['max_hold_days']}거래일 |",
       f"| 인버스 (KODEX 인버스) | 하락 국면에서만, 최대 {pct(inv.get('weight_cap', 0))}, 비용 차감 +1.5% 익절 · 최대 2거래일 |",
       f"| 지수 (KODEX 200) | 상승·횡보 국면 최대 {pct(ix.get('weight_cap', 0))}. 당일 −3% 이하 급락일엔 하락 국면이어도 마감 직전 매수 |",
       f"| 리스크 한도 (고정) | 일일 손실 {pctp(R['daily_loss_limit'])} 도달 시 매수 중단 · 최소 현금 {pct(R['min_cash_ratio'])} · 종목당 최대 {pct(R['max_weight_per_stock'])} |",
       f"| 자동 조정 | 매 영업일 16:00 AI가 성과를 분석해 기준값 미세 조정 (리스크 한도는 조정 불가) |", "",
       "<details><summary>시스템 용어 풀이</summary>", "",
       "- **확신도**: AI가 매수(또는 매도) 판단을 얼마나 확신하는지 0~1로 낸 점수. 이 점수가 기준을 넘어야 주문이 나가고, 높을수록 포지션이 커짐",
       "- **회차**: AI가 판단·주문을 실행하는 정해진 시각 (09:30부터 15분 간격)",
       "- **자동 조정**: 사람이 승인하지 않아도 AI가 정해진 범위 안에서 기준값을 바꾸는 기능. 리스크 한도는 대상이 아님",
       "- **자동 차단**: 리스크 한도를 넘는 주문은 AI가 내더라도 체결 전에 시스템이 막음",
       "- **백테스트**: 과거 주가 데이터에 규칙을 적용해 성과를 미리 검증한 것",
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
out += ["---", "변경 단위 원문 기록: [reports/week1/changes.tsv](reports/week1/changes.tsv)", ""]
open(OUT, "w", encoding="utf-8").write("\n".join(out))
miss = [h for _, _, h, _ in rows if h not in PLAIN]
print(f"CHANGELOG.md: 전략 변경 {len(rows)}건, {len(by_day)}일" + (f" · 쉬운 설명 없음 {len(miss)}건: {' '.join(miss)}" if miss else ""))
