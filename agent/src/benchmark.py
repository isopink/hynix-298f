"""비교 기준 KODEX 200 (069500) 일봉 → docs/data/kodex200.json.
11-11 S.Lee: 대시보드의 비교선·초과수익을 KOSPI 지수 대신 KODEX 200 으로. 대회 시작일 시가가 기준(대회 게시판과 같은 09:00 가격).
마감 기록(close) 때 갱신하고, 실패해도 마감 기록은 계속함. 네이버 증권 일봉(공개, 키 없음)."""
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

CODE, NAME = "069500", "KODEX 200"
URL = f"https://fchart.stock.naver.com/sise.nhn?symbol={CODE}&timeframe=day&count=40&requestType=0"


def parse(xml):
    """네이버 일봉 응답 → {YYYY-MM-DD: {o, c}} (시가 · 종가)."""
    days = {}
    for line in re.findall(r'data="([^"]+)"', xml):
        d, o, _h, _l, c, _v = line.split("|")
        days[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = {"o": float(o), "c": float(c)}
    return days


def build(days, start_date):
    days = {d: v for d, v in days.items() if d >= start_date}
    if start_date not in days:
        raise ValueError(f"{start_date} 일봉이 없음")
    return {"symbol": CODE, "name": NAME, "start_date": start_date, "start": days[start_date]["o"],
            "days": dict(sorted(days.items())), "updated": C.stamp()}


def update():
    xml = urllib.request.urlopen(URL, timeout=20).read().decode("euc-kr", errors="replace")
    out = build(parse(xml), C.params()["competition"]["start"])
    C.write_json(os.path.join(C.DOCS_DATA, "kodex200.json"), out)
    return out


if __name__ == "__main__":
    try:
        r = update()
        print(f"KODEX 200 기준 {len(r['days'])}일 · 시작 시가 {r['start']:,.0f} · 마지막 {max(r['days'])} 종가 {r['days'][max(r['days'])]['c']:,.0f}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! KODEX 200 기준 갱신 실패: {e}")
        sys.exit(1)
