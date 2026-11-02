# 작업 스케줄러 등록 (한 번만 실행). 지우려면: .\setup_tasks.ps1 -Remove
# 평일: 08:30 준비 → 08:55 잔고 루프 → 09:05 장중 감시 → 09:30·11:00·14:30 정기 판단 → 15:45 마감 기록
# 화·수·목 16:00 기준값 자동 조정 · 토요일 10:00 주간 회고
# 코드 동기화: 로그온할 때(+ 매일 07:00 안전망) 켜져서 계속 돎. push 된 수정을 1분 안에 반영
param([switch]$Remove)

$agent = $PSScriptRoot
$live  = Join-Path (Split-Path $agent) "live"
$wk    = "MON,TUE,WED,THU,FRI"

$tasks = @(
  @{ Name = "Hynix298-prep";     Time = "08:30"; Days = $wk;  Cmd = "`"$agent\run.bat`" prep" },
  @{ Name = "Hynix298-snapshot"; Time = "08:55"; Days = $wk;  Cmd = "`"$live\run_snapshot.bat`"" },
  @{ Name = "Hynix298-monitor";  Time = "09:05"; Days = $wk;  Cmd = "`"$agent\run.bat`" monitor" },
  @{ Name = "Hynix298-decide-am"; Time = "09:30"; Days = $wk; Cmd = "`"$agent\run.bat`" decide" },
  @{ Name = "Hynix298-decide-mid"; Time = "11:00"; Days = $wk; Cmd = "`"$agent\run.bat`" decide" },
  @{ Name = "Hynix298-decide-pm"; Time = "14:30"; Days = $wk; Cmd = "`"$agent\run.bat`" decide" },
  @{ Name = "Hynix298-close";    Time = "15:45"; Days = $wk;  Cmd = "`"$agent\run.bat`" close" },
  @{ Name = "Hynix298-tune";     Time = "16:00"; Days = "TUE,WED,THU"; Cmd = "`"$agent\run.bat`" tune" },
  @{ Name = "Hynix298-review";   Time = "10:00"; Days = "SAT"; Cmd = "`"$agent\run.bat`" review" }
)

foreach ($t in $tasks) {
  schtasks /Delete /TN $t.Name /F 2>$null | Out-Null
  if (-not $Remove) {
    schtasks /Create /TN $t.Name /TR $t.Cmd /SC WEEKLY /D $t.Days /ST $t.Time /F | Out-Null
    # 기본값은 "AC 전원일 때만 시작"이라 노트북이 배터리면 대기에 멈춤 → 배터리에서도 실행, 놓친 회차는 켜지면 바로 실행
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Set-ScheduledTask -TaskName $t.Name -Settings $s | Out-Null
    Write-Output ("등록: {0}  {1} {2}" -f $t.Name, $t.Days, $t.Time)
  }
}
# 코드 동기화는 시각이 아니라 로그온에 맞춰 켜고, 시간 제한 없이 계속 돌게 함 (이미 돌고 있으면 새로 안 띄움)
$sync = "Hynix298-sync"
Unregister-ScheduledTask -TaskName $sync -Confirm:$false -ErrorAction SilentlyContinue
if (-not $Remove) {
  $act = New-ScheduledTaskAction -Execute "$agent\run.bat" -Argument "sync"
  $trg = @((New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME), (New-ScheduledTaskTrigger -Daily -At "07:00"))
  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
       -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $sync -Action $act -Trigger $trg -Settings $s | Out-Null
  Write-Output "등록: $sync  로그온 시 + 매일 07:00 (계속 실행)"
}
if ($Remove) { Write-Output "모두 삭제했습니다." }
