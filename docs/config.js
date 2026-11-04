// Supabase 연결 정보 (README 1단계 참고)
// anon public 키는 브라우저에 공개되는 용도라 여기 넣어도 괜찮아요.
// service_role 키, 키움 비밀번호·App Key·App Secret은 절대 넣지 마세요.
window.DASH_CONFIG = {
  supabaseUrl: "https://tfmeqvcjqfcbxvjcvpin.supabase.co",
  supabaseAnonKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRmbWVxdmNqcWZjYnh2amN2cGluIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMwNjgyNDMsImV4cCI6MjEwODY0NDI0M30.q0kVoi92PFG6oqoPHIJXKIR2c2MSgRhjiajyvzr3pTQ",  // anon public
  liveSince: "2026-11-02",  // 이 날짜부터의 실시간 잔고를 그래프에 사용 (대회 시작일)
  kospiStart: 5645.52,      // KOSPI 수익률 기준 = 대회 시작일(11-02) 09:00 1분봉 (실시간 KOSPI 차트의 첫 점)
  // 양도차익 계산용 비용 (agent/config/params.json costs 와 같게). ETF(인버스·지수)는 매도 세금 없음
  costs: { fee: 0.0035, sellTax: 0.002, taxFree: ["114800", "069500"] }
};
