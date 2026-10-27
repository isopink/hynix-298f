// Supabase 연결 정보 (README 1단계 참고)
// anon public 키는 브라우저에 공개되는 용도라 여기 넣어도 괜찮아요.
// service_role 키, 키움 비밀번호·App Key·App Secret은 절대 넣지 마세요.
window.DASH_CONFIG = {
  supabaseUrl: "",          // 예: "https://abcdefgh.supabase.co"
  supabaseAnonKey: "",      // 예: "eyJhbGciOi..." (Project Settings → API → anon public)
  liveSince: "2026-11-02"   // 이 날짜부터의 실시간 잔고를 그래프에 사용 (대회 시작일)
};
