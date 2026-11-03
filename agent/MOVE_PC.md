# 에이전트를 다른 PC로 옮기기

노트북을 계속 켜둘 수 없어서 집에 계속 켜두는 PC(이하 **데스크톱**)에서 에이전트를 돌리고, 노트북은 **수정 전용**으로 씁니다.

```
노트북: 수정 → git push
데스크톱: sync 가 1분마다 확인 → 검사 → 반영 → (장중이면) 감시·잔고 루프 재시작
```

**옮기는 시각**: 평일 15:45 마감 기록이 끝난 뒤나 주말. 두 PC의 작업이 동시에 돌면 주문이 두 번 나갈 수 있으니 순서를 꼭 지킬 것.

## 1. 데스크톱 준비 (언제 해도 됨)

- [ ] 설치: [Git for Windows](https://git-scm.com/download/win), [Python 3.14](https://www.python.org/downloads/) (설치할 때 "Add to PATH" 체크)
- [ ] Claude Code 설치 후 로그인 (노트북과 같은 계정)
  ```powershell
  irm https://claude.ai/install.ps1 | iex
  claude          # 처음 한 번 로그인
  claude -p "안녕"  # 답이 나오면 OK (헤드리스 실행 확인)
  ```
- [ ] 저장소 받기 + 작성자 설정 (sync 의 rebase 와 에이전트 자동 커밋에 필요)
  ```powershell
  git clone https://github.com/isopink/hynix-298f.git C:\dev\uostock-ai-trader
  cd C:\dev\uostock-ai-trader
  git config user.name "S.Lee"
  git config user.email "2sm9908@gmail.com"
  git push --dry-run   # GitHub 로그인 창이 뜨면 로그인 (push 권한 확인)
  ```
- [ ] 파이썬 가상환경
  ```powershell
  py -m venv agent\.venv
  agent\.venv\Scripts\pip install -r agent\requirements.txt
  ```
- [ ] 전원·Windows 설정
  - 절전 모드 **안 함**, 화면 끄기는 자유 (모니터는 꺼도 됨)
  - 화면 잠금(Win+L)은 괜찮지만 **로그아웃 금지**: 작업이 로그온한 사용자로 돌아감
  - Windows 업데이트 → 사용 시간을 08:00~16:00으로 (장중 자동 재시작 방지)
  - 재부팅되면 로그온해야 작업이 다시 돎 → 재부팅 후 꼭 로그온

## 2. 노트북 멈추기 (옮기는 날, 마감 기록 뒤)

```powershell
cd C:\dev\uostock-ai-trader\agent
.\setup_tasks.ps1 -Remove
# 작업만 지우면 python 이 남을 수 있으니 직접 종료
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  ? { $_.CommandLine -match 'run.py|snapshot.py' } | % { Stop-Process -Id $_.ProcessId -Force }
cd ..; git status; git push   # 아직 안 올라간 에이전트 커밋이 없게
```

## 3. 파일 복사 (USB 등, GitHub에 올리지 말 것)

| 노트북 | 데스크톱 같은 위치로 | 왜 |
|---|---|---|
| `agent\.env` | `agent\.env` | KRX·네이버 키, MODE=live, GIT_PUSH=1 |
| `live\.env` | `live\.env` | 키움 App Key, Supabase |
| `agent\work\` 폴더 전체 | `agent\work\` | **journal.jsonl(모든 기록의 원본)**, 보유 종목 손절·익절(positions.json), 오늘 시작 자산 등. 없으면 보유 종목을 모르는 채로 시작함 |

복사한 USB의 `.env` 는 옮긴 뒤 지우기.

## 4. 데스크톱 시작

```powershell
cd C:\dev\uostock-ai-trader
git pull
python live\snapshot.py --dry                        # 키움 잔고·KOSPI 응답 확인 (Supabase 에는 안 올림)
agent\.venv\Scripts\python.exe agent\src\sync.py --once   # 동기화 한 번
cd agent
powershell -ExecutionPolicy Bypass -File .\setup_tasks.ps1   # 작업 10개 등록 (Hynix298-*)
schtasks /Run /TN Hynix298-sync                      # 동기화는 원래 로그온 때 켜지므로 이번만 직접
```

키움에서 IP 관련 오류가 나면 키움 REST API 관리 화면에서 데스크톱 IP를 허용 목록에 넣을 것.

## 5. 다음 날 아침 확인

- [ ] 08:30 이후 대시보드 "오늘의 시장 자료" 갱신
- [ ] 08:30 이후 대시보드 **시장 감시 On**
- [ ] `agent\work\sync.log` 에 `코드 동기화 시작` 이 있고 오류가 없음
- [ ] 이상 없으면 노트북의 `C:\dev\uostock-ai-trader` 는 지워도 됨 (수정은 `projects\hynix-298f` 에서)

## 노트북에서 수정할 때

1. **수정 전에 `git pull`** (데스크톱 에이전트가 계속 기록을 올림)
2. 수정 → 커밋 → `git push` → 1분 안에 반영
3. 반영 범위
   - `agent/src/`, `agent/run.py`, `agent/config/` → 장중이면 감시(monitor) 재시작
   - `live/snapshot.py` → 장중이면 잔고 루프 재시작
   - 프롬프트(`agent/CLAUDE.md`, `.claude/`) → 다음 판단부터
   - 판단·손절 실행이 도는 중이면 끝난 뒤에 반영
4. 반영 안 되는 경우
   - 문법 오류·JSON 오류·import 실패 → 그 커밋은 건너뜀. 고친 커밋을 다시 push 하면 반영
   - 대시보드 에이전트 표시가 빨간 점이면 동기화가 멈춘 것 (마우스를 올리면 이유)
5. `docs/data/`·`params.json` 은 데스크톱 에이전트가 쓰는 파일. 같은 줄이 겹치면 **데스크톱 쪽이 이김**. `params.json` 을 손으로 바꿀 거면 화·수·목 16:00 자동 조정 직후는 피하기
