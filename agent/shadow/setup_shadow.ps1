# 그림자 운영 설치 (11-08 S.Lee). 온톨로지 버전을 실제 매매 옆에서 가상 계좌로 나란히 돌림.
# 데스크톱 PowerShell 에서 한 번만:  powershell -ExecutionPolicy Bypass -File setup_shadow.ps1
# 지우려면:                         powershell -ExecutionPolicy Bypass -File setup_shadow.ps1 -Remove
#
# - 실제 저장소(C:\dev\uostock-ai-trader)는 읽기만 함. 주문은 가상 계좌에만, 키움 API 는 새로 부르지 않음
# - 판단은 실제 회차보다 3분 늦게 (실제 시스템이 받은 장중 순위·현재가를 그대로 쓰려고)
# - GIT_PUSH=0 : 대시보드·저장소에 아무것도 올리지 않음
param([switch]$Remove,
      [string]$Real = "C:\dev\uostock-ai-trader",
      [string]$Dir  = "C:\dev\hynix-shadow",
      [string]$Branch = "shadow/ontology")

$wk = "MON,TUE,WED,THU,FRI"
$names = "Hynix298S-prep", "Hynix298S-monitor", "Hynix298S-decide", "Hynix298S-close", "Hynix298S-review", "Hynix298S-tune"
foreach ($n in $names) { schtasks /Delete /TN $n /F 2>$null | Out-Null }
if ($Remove) { Write-Output "그림자 작업을 모두 지웠습니다. 폴더 $Dir 은 남겨 둡니다."; exit }

if (-not (Test-Path $Dir)) {
  git clone --branch $Branch (git -C $Real remote get-url origin) $Dir
} else {
  git -C $Dir fetch origin; git -C $Dir checkout $Branch; git -C $Dir pull --ff-only
}
$agent = Join-Path $Dir "agent"

# 파이썬 환경 (실제와 같은 파이썬으로 따로 만듦)
$py = Join-Path $Real "agent\.venv\Scripts\python.exe"
if (-not (Test-Path "$agent\.venv")) { & $py -m venv "$agent\.venv" }
& "$agent\.venv\Scripts\python.exe" -m pip install -q -r "$agent\requirements.txt"

# .env: 실제 agent/.env 의 KRX·네이버 키를 쓰고, 모드는 가상 계좌로 고정
$envText = (Get-Content (Join-Path $Real "agent\.env") -Encoding UTF8) | Where-Object { $_ -notmatch '^\s*(MODE|GIT_PUSH|SHADOW_OF)\s*=' }
$envText += "MODE=mock"
$envText += "GIT_PUSH=0"
$envText += "SHADOW_OF=$Real"
Set-Content -Path "$agent\.env" -Value $envText -Encoding UTF8
New-Item -ItemType Directory -Force "$agent\work" | Out-Null

$tasks = @(
  @{ Name = "Hynix298S-prep";    Time = "08:35"; Days = $wk;        Arg = "prep" },
  @{ Name = "Hynix298S-monitor"; Time = "08:35"; Days = $wk;        Arg = "monitor" },
  @{ Name = "Hynix298S-decide";  Time = "09:33"; Days = $wk;        Arg = "decide"; Every = 15; For = "05:46" },
  @{ Name = "Hynix298S-close";   Time = "15:48"; Days = $wk;        Arg = "close" },
  @{ Name = "Hynix298S-review";  Time = "16:40"; Days = "WED,FRI";  Arg = "review" },
  @{ Name = "Hynix298S-tune";    Time = "16:50"; Days = $wk;        Arg = "tune" }
)
foreach ($t in $tasks) {
  $rep = if ($t.Every) { @("/RI", $t.Every, "/DU", $t.For) } else { @() }
  schtasks /Create /TN $t.Name /TR "`"$agent\run.bat`" $($t.Arg)" /SC WEEKLY /D $t.Days /ST $t.Time @rep /F | Out-Null
  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 8)
  Set-ScheduledTask -TaskName $t.Name -Settings $s | Out-Null
  Write-Output ("등록: {0}  {1} {2}{3}" -f $t.Name, $t.Days, $t.Time, $(if ($t.Every) { " 부터 $($t.Every)분마다" } else { "" }))
}
Write-Output "그림자 운영 준비 끝. 비교: $agent\.venv\Scripts\python.exe $agent\shadow\compare.py"
