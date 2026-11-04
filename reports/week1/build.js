// 1주차 주간 운용보고서 PDF 만들기
//   node reports/week1/build.js            → reports/week1/week1_report.pdf (+ .html)
// 1쪽: 초기 전략 + 누적 양도차익 · KOSPI 대비 · 현재 수익률 (공개 대시보드에서 지금 값을 읽음) + 수익률 차트
// 2쪽~: 사전 계획서(10-28) 이후 변경 로그 전부 (changes.tsv, 시각은 git 커밋 시각 KST)
// 제출 직전(일요일)에 다시 실행하면 숫자와 로그가 그 시점 기준으로 갱신됨. Playwright 필요
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { chromium } = require('playwright');

const HERE = __dirname;
const ROOT = path.resolve(HERE, '..', '..');
const DASH = 'https://isopink.github.io/hynix-298f/';
const SINCE = '2026-10-28';
const RUNS = /^Agent (decide|view|prep|close|tune|exit|review) 20/;   // 에이전트 자동 실행 기록 커밋은 변경이 아님
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---------- 변경 로그 ----------
const rows = fs.readFileSync(path.join(HERE, 'changes.tsv'), 'utf8').split('\n')
  .filter(l => l.trim() && !l.startsWith('#')).map(l => { const [h, cat, text] = l.split('\t'); return { h, cat, text }; });
const byHash = new Map(rows.map(r => [r.h, r]));
const log = execSync(`git log --since="${SINCE}" --format="%h|%ad|%s" --date=format-local:"%Y-%m-%d %H:%M"`,
  { cwd: ROOT, env: { ...process.env, TZ: 'Asia/Seoul' } }).toString().trim().split('\n').map(l => {
  const [h, t, ...s] = l.split('|'); return { h, t, s: s.join('|') };
});
const missing = log.filter(c => !RUNS.test(c.s) && !byHash.has(c.h) && !c.s.startsWith('Report:'));
if (missing.length) console.warn(`changes.tsv 에 없는 커밋 ${missing.length}건 (보고서에서 빠짐, 필요하면 추가):\n` + missing.map(c => `  ${c.h} ${c.t} ${c.s}`).join('\n'));
const time = new Map(log.map(c => [c.h, c.t]));
const entries = rows.filter(r => time.has(r.h)).map(r => ({ ...r, t: time.get(r.h) })).sort((a, b) => a.t < b.t ? -1 : 1);
const cats = ['전략', '운영', '대시보드', '문서'];
const count = Object.fromEntries(cats.map(c => [c, entries.filter(e => e.cat === c).length]));

(async () => {
  const browser = await chromium.launch();
  // ---------- 지금 숫자: 공개 대시보드 상단 ----------
  const dash = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  await dash.goto(DASH, { waitUntil: 'networkidle' });
  await dash.waitForFunction(() => document.getElementById('pnl-won')?.textContent.trim() !== '—', null, { timeout: 30000 });
  await dash.waitForTimeout(1500);
  const kpi = await dash.evaluate(() => ({
    pnl: document.getElementById('pnl-won').textContent.trim(),
    alpha: document.getElementById('k-alpha').textContent.trim(),
    ret: document.getElementById('ret-pct').textContent.trim(),
  }));
  await dash.evaluate(() => { const s = document.getElementById('st-line'); if (s) s.style.display = 'none'; });   // 차트 위 On/Off 표시는 빼고 찍음
  const chart = (await (await dash.$('.hero-chart')).screenshot()).toString('base64');
  const asof = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');
  await dash.close();
  console.log('지금 숫자', kpi, asof);

  const tone = v => /^[−-]/.test(v) ? 'down' : /^\+/.test(v) ? 'up' : '';
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>
@page { size: A4; margin: 16mm 15mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Serif KR", serif; color: #1c1c1c; font-size: 10.5pt; line-height: 1.55; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 2mm; letter-spacing: -.3px; }
h2 { font-size: 12.5pt; margin: 7mm 0 2.5mm; padding-bottom: 1.5mm; border-bottom: 1.5px solid #da291c; }
.meta { color: #666; font-size: 9.5pt; }
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm; margin-top: 5mm; }
.kpi { border: 1px solid #e3e3e3; border-radius: 3mm; padding: 4mm 5mm; }
.kpi .l { font-size: 9pt; color: #666; }
.kpi .v { font-size: 19pt; font-weight: 700; margin-top: 1mm; }
.up { color: #da291c; } .down { color: #2b7fb0; }
.chart { margin-top: 4mm; border-radius: 3mm; overflow: hidden; background: #111; }
.chart img { width: 100%; display: block; }
.note { font-size: 8.5pt; color: #777; margin-top: 1.5mm; }
ul { margin: 0; padding-left: 5mm; } li { margin: .6mm 0; }
table.st { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
table.st td { padding: 1.2mm 2mm; border-bottom: 1px solid #eee; vertical-align: top; }
table.st td:first-child { width: 28mm; color: #555; white-space: nowrap; }
.log { page-break-before: always; }
.sum { display: flex; gap: 3mm; flex-wrap: wrap; margin-bottom: 3mm; font-size: 9pt; color: #555; }
table.lg { width: 100%; border-collapse: collapse; font-size: 9pt; }
table.lg th { text-align: left; font-weight: 600; color: #555; border-bottom: 1.5px solid #ccc; padding: 1.5mm 2mm; }
table.lg td { padding: 1.3mm 2mm; border-bottom: 1px solid #eee; vertical-align: top; }
table.lg tr { page-break-inside: avoid; }
table.lg td.t { white-space: nowrap; color: #555; width: 24mm; font-variant-numeric: tabular-nums; }
.b { display: inline-block; font-size: 8pt; padding: .2mm 2mm; border-radius: 9mm; border: 1px solid #ccc; white-space: nowrap; }
.b.전략 { color: #da291c; border-color: #f0a49c; background: #fff4f2; font-weight: 600; }
.b.운영 { color: #2b7fb0; border-color: #a9cfe4; background: #f2f8fc; }
.b.대시보드 { color: #555; } .b.문서 { color: #888; }
tr.전략 td:last-child { font-weight: 600; }
</style></head><body>

<h1>1주차 주간 운용보고서</h1>
<div class="meta">Sigma Six · 팀 「하이닉스 298층 주민」 이석민 · 박문화 · 2026 나비스트 UOStock AI 자동매매 모의투자대회<br>
기간 2026-11-02 ~ 11-06 · 숫자 기준 ${esc(asof)} (실시간 대시보드 ${esc(DASH)})</div>

<div class="kpis">
  <div class="kpi"><div class="l">누적 양도차익</div><div class="v ${tone(kpi.pnl)}">${esc(kpi.pnl)}</div></div>
  <div class="kpi"><div class="l">KOSPI 대비 수익률</div><div class="v ${tone(kpi.alpha)}">${esc(kpi.alpha)}</div></div>
  <div class="kpi"><div class="l">현재 수익률</div><div class="v ${tone(kpi.ret)}">${esc(kpi.ret)}</div></div>
</div>
<div class="chart"><img src="data:image/png;base64,${chart}"></div>
<div class="note">초기 자산 50,000,000원 · KOSPI 기준 11-02 09:00 1분봉 5,645.52 · 누적 양도차익은 매도로 확정된 손익</div>

<h2>초기 전략 (사전 계획서 · 10-28)</h2>
<table class="st">
<tr><td>원칙</td><td>에이전트는 제안하고, 규칙이 결정한다. LLM 은 근거 토론과 확신도만, 수량 · 리스크 · 주문 차단은 코드가 결정</td></tr>
<tr><td>판단 주기</td><td>장 시작 전 1회 (착수 시 09:30 · 14:30 하루 2번)</td></tr>
<tr><td>데이터 · 후보</td><td>KRX 전 종목 중 전일 거래대금 상위 60 → 20·60일선 상승 추세 + 외국인·기관 5일 순매수 → 점수 상위 10개. LLM 에는 숫자 요약만</td></tr>
<tr><td>판단 구조</td><td>국면 서브에이전트(상승 / 횡보 / 하락) → 매수 측 ⇄ 매도 측 토론 → 총괄이 종목별 확신도(0~1) 산출</td></tr>
<tr><td>매매 기준</td><td>매수 확신도 0.60 이상 · 매도 0.60 이상 · 0.80 이상이면 종목 한도까지. 손절 −7% · 익절 +15% · 최대 10거래일</td></tr>
<tr><td>주식 비중 상한</td><td>상승 90% · 횡보 60% · 하락 30%, 1주차와 4주차는 ×0.5</td></tr>
<tr><td>리스크 한도 (Hook 강제)</td><td>종목당 20% · 최대 6종목 · 현금 10% 이상 · 1회 주문 1,000만 원 · 실행당 8건 · 일일 손실 −3% 신규 매수 중단 · 누적 −10% 상한 절반</td></tr>
<tr><td>개선 루프</td><td>토요일 주간 회고 에이전트가 기준값 조정안 제안 → 사람이 검토해 반영 (리스크 한도는 수정 불가)</td></tr>
</table>

<section class="log">
<h2>변경 로그 (사전 계획서 이후 ${entries.length}건)</h2>
<div class="sum">${cats.map(c => `<span><span class="b ${c}">${c}</span> ${count[c]}건</span>`).join('')}<span>· 시각은 GitHub 커밋 기준 (KST)</span></div>
<table class="lg"><thead><tr><th>일시</th><th>구분</th><th>변경 내용</th></tr></thead><tbody>
${entries.map(e => `<tr class="${e.cat}"><td class="t">${esc(e.t.slice(5))}</td><td><span class="b ${e.cat}">${e.cat}</span></td><td>${esc(e.text)}</td></tr>`).join('\n')}
</tbody></table>
</section>
</body></html>`;

  fs.writeFileSync(path.join(HERE, 'week1_report.html'), html);
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: 'networkidle' });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.pdf({ path: path.join(HERE, 'week1_report.pdf'), format: 'A4', printBackground: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:8px;color:#999;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '16mm', bottom: '16mm', left: '15mm', right: '15mm' } });
  await browser.close();
  console.log(`완료: reports/week1/week1_report.pdf (변경 로그 ${entries.length}건)`);
})();
