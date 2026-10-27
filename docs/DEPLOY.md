# 배포 가이드

대시보드(`docs/`)를 GitHub Pages로 띄우고, 게시판과 실시간 잔고를 Supabase에 연결하는 방법입니다.

## 폴더 구성
| 파일 | 역할 |
|---|---|
| `docs/index.html` | 대시보드 화면 (페라리 스타일) |
| `docs/data/*.json` | 화면에 나오는 숫자 (지금은 샘플) |
| `docs/config.js` | 댓글 저장소(Supabase) 연결 정보 |
| `supabase/schema.sql` | 댓글 + 실시간 잔고 테이블 만드는 SQL |
| `live/snapshot.py` | 키움 잔고를 5분마다 조회해 Supabase에 올리는 스크립트 (팀 계좌 키를 가진 PC 1대에서 실행) |
| `live/.env.example` | 스크립트 설정 견본 → `.env`로 복사해서 사용 |
| `live/run_snapshot.bat` | 작업 스케줄러용 실행 파일 |

## 배포 순서

### 1. 댓글 저장소 만들기 (Supabase, 무료)
1. https://supabase.com 가입 → **New project** (Region: Northeast Asia (Seoul))
2. 왼쪽 **SQL Editor** → New query → `schema.sql` 전체 붙여넣기
3. 붙여넣은 SQL 맨 아래 `'여기에-긴-비밀문구-입력'`을 아무도 모르는 긴 문구로 바꾸고 **Run**
   - ⚠️ 저장소의 `schema.sql` 파일은 고치지 말 것 (공개 저장소라 비밀문구가 노출됨). SQL Editor 안에서만 바꾸기
4. **Project Settings → API**에서 두 값 복사
   - Project URL
   - `anon` `public` 키 (⚠️ `service_role` 키는 절대 쓰지 말 것)
5. `docs/config.js`에 붙여넣기

### 2. GitHub Pages 켜기
1. 저장소 **Settings → Pages**
2. Source: **Deploy from a branch** / Branch: `main` / 폴더: **`/docs`** → Save
3. 1~2분 뒤 `https://<아이디>.github.io/hynix-298f/` 주소가 생김

### 3. 확인
- 사이트에서 댓글 하나 남겨 보고, 새로고침해서 보이는지 확인

## 댓글 관리
- 숨기기: Supabase → **Table Editor → comments** → 해당 줄 `hidden`을 `true`로
- 완전 삭제: 같은 화면에서 줄 선택 → Delete
- 기본 도배 방지: 글자 수 300자, 한 사람 30초 간격, 전체 1분 20개 제한

## 실시간 잔고 켜기 (팀 계좌 키를 가진 PC 1대에서)
1. Python 설치 확인: `python --version` (3.9 이상, 추가 설치할 패키지 없음)
2. `live/.env.example`을 복사해 `live/.env`로 이름 바꾸고 채우기
   - `ACCOUNT_NAME`: `팀` (그대로)
   - `KIWOOM_APPKEY`, `KIWOOM_SECRETKEY`: 대회용 모의투자 App Key / Secret (10/31 이후 재발급받은 것)
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`: config.js와 같은 값
   - `SNAPSHOT_SECRET`: schema.sql에 넣은 비밀문구와 똑같이
3. 연결 확인: `live` 폴더에서 `python snapshot.py --dry` → 총자산·종목이 찍히면 성공
4. 한 번 올려 보기: `python snapshot.py` → 사이트 새로고침 시 오른쪽 위에 `LIVE · 시각 갱신` 표시
5. 자동 실행 등록 (Windows 작업 스케줄러)
   - 작업 스케줄러 → 기본 작업 만들기 → 이름 `대시보드 잔고`
   - 트리거: 매주 · 월~금 · 오전 8:55
   - 동작: 프로그램 시작 → `live\run_snapshot.bat` 선택
   - 장중 5분마다 조회하고 15:35에 스스로 종료. 기록은 `live\snapshot.log`
- PC가 꺼져 있으면 그 시간 동안은 갱신이 멈추고, 마지막 값이 그대로 보임
- 조회만 하고 주문은 하지 않음. 간격은 `.env`의 `INTERVAL_SEC` (최소 60초, 기본 300초)
- `docs/config.js`의 `liveSince`(기본 11/2) 이전 기록은 그래프에 쓰지 않음. 대회 전에 시험할 땐 오늘 날짜로 잠깐 바꿔서 확인

## 실제 데이터로 바꾸기 (대회 시작 후)
- 자산·보유 종목: 실시간 잔고가 들어오면 자동으로 그걸 사용
- 거래 내역·판단 근거·리스크 차단·토큰·주간 회고: 에이전트가 `docs/data/trades.json` 등을 같은 형식으로 덮어쓰고 `git push`
- 시장 국면 띠: `docs/data/equity.json`의 날짜별 `regime`, `cap` 값을 사용 (없으면 회색)

## 보안 주의
- 키움 비밀번호, App Key, App Secret, Supabase `service_role` 키, `live/.env`는 **절대 저장소에 넣지 않기** (`.gitignore`로 막아 둠)
- 저장소가 Public이라 누구나 코드를 볼 수 있음 (`.gitignore`에 `.env`, `secrets/` 제외 설정해 둠)
