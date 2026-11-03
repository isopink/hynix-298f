// README 도식 렌더링: assets/diagrams/*.mmd → *.png
// GitHub 모바일 앱은 ```mermaid 를 그림으로 안 그려서 PNG 로 넣음. .mmd 를 고친 뒤 다시 실행:
//   node assets/diagrams/render.js        (Playwright 필요, mermaid 는 CDN 에서 받음)
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const DIR = __dirname;
const MERMAID = 'https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js';
const CONFIG = {
  startOnLoad: false, theme: 'base', securityLevel: 'loose',
  fontFamily: '"Noto Serif KR", serif',
  flowchart: { htmlLabels: true, curve: 'basis', padding: 16, nodeSpacing: 40, rankSpacing: 48, useMaxWidth: false, wrappingWidth: 280 },
  themeVariables: {
    background: '#14161b', fontSize: '17px',
    primaryColor: '#23262e', primaryTextColor: '#ececec', primaryBorderColor: '#4a4e58',
    lineColor: '#8c8c8c', textColor: '#ececec',
    clusterBkg: '#1b1e25', clusterBorder: '#3a3e48',
    edgeLabelBackground: '#14161b', tertiaryColor: '#1b1e25',
  },
};

(async () => {
  const files = fs.readdirSync(DIR).filter(f => f.endsWith('.mmd'));
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 900, height: 800 } });
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600&display=swap" rel="stylesheet">
    <style>body{margin:0;background:#14161b} #out{display:inline-block;padding:28px;background:#14161b;border-radius:16px}
    .nodeLabel, .edgeLabel, .label{word-break:keep-all}</style>
    <script src="${MERMAID}"></script></head><body><div id="out"></div></body></html>`);
  await page.waitForFunction(() => window.mermaid);
  // 글자 폭을 잴 때 웹폰트가 이미 있어야 노드 안 글자가 안 잘림 (영문·한글·기호 글리프 모두 미리 로드)
  await page.evaluate(async () => {
    for (const w of ['400', '600']) await document.fonts.load(`${w} 17px "Noto Serif KR"`, 'Aa09 가나다 →⇄≥·…');
    await document.fonts.ready;
  });
  for (const f of files) {
    const src = fs.readFileSync(path.join(DIR, f), 'utf8');
    await page.evaluate(async ({ src, cfg }) => {
      mermaid.initialize(cfg);
      const { svg } = await mermaid.render('g' + Date.now(), src);
      document.getElementById('out').innerHTML = svg;
      const s = document.querySelector('#out svg');
      void s;
      await document.fonts.ready;
    }, { src, cfg: CONFIG });
    await page.waitForTimeout(300);
    const out = path.join(DIR, f.replace(/\.mmd$/, '.png'));
    await (await page.$('#out')).screenshot({ path: out, omitBackground: false });
    console.log('rendered', path.basename(out));
  }
  await browser.close();
})();
