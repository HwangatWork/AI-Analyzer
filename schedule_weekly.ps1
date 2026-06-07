# AI Analyzer - Windows Task Scheduler 주 1회 자동화 설정
# 실행: PowerShell을 관리자 권한으로 열고 .\schedule_weekly.ps1
# 알림: ntfy.sh 앱(무료)에서 채널 'ai-analyzer-hwangatwork' 구독

$TaskName        = "AIAnalyzer_WeeklyPipeline"
$TaskNameDaily   = "AIAnalyzer_DailyTelegram"
$ScriptDir       = $PSScriptRoot
$PipelineBat     = Join-Path $ScriptDir "run_pipeline.bat"
$PythonExe       = "python"
$TelegramAgent   = Join-Path $ScriptDir "agents\run_telegram_agent.py"
$LogDir          = Join-Path $ScriptDir "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# 기존 태스크 제거
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "기존 태스크 제거됨"
}

# 트리거: 매주 월요일 오전 7시
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "07:00AM"

# 액션: 로그 파일에 출력 저장
$Today  = Get-Date -Format "yyyyMMdd"
$Action = New-ScheduledTaskAction `
    -Execute  "cmd.exe" `
    -Argument "/c `"$PipelineBat`" >> `"$LogDir\pipeline_$Today.log`" 2>&1" `
    -WorkingDirectory $ScriptDir

# 실행 설정
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 2) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 10) `
    -MultipleInstances   IgnoreNew `
    -StartWhenAvailable  $true    # 로그오프 중 놓친 경우 다음 로그인 시 실행

# Principal: S4U - 로그온 없이 실행 (비밀번호 저장 불필요)
$Principal = New-ScheduledTaskPrincipal `
    -UserId    $env:USERNAME `
    -LogonType S4U `
    -RunLevel  Highest

try {
    Register-ScheduledTask `
        -TaskName   $TaskName `
        -Trigger    $Trigger `
        -Action     $Action `
        -Settings   $Settings `
        -Principal  $Principal `
        -Description "AI Analyzer 주 1회 자동 데이터 갱신 (매주 월요일 07:00)"

    Write-Host ""
    Write-Host "======================================================"
    Write-Host "태스크 등록 완료: $TaskName"
    Write-Host "실행 주기: 매주 월요일 오전 7:00"
    Write-Host "LogonType: S4U (로그오프 상태에서도 실행)"
    Write-Host "알림: ntfy.sh 앱 -> 채널 'ai-analyzer-hwangatwork' 구독"
    Write-Host "로그 위치: $LogDir"
    Write-Host "======================================================"
} catch {
    Write-Host "[경고] S4U 실패, Interactive로 폴백: $_"
    $Principal2 = New-ScheduledTaskPrincipal `
        -UserId    $env:USERNAME `
        -LogonType Interactive `
        -RunLevel  Highest
    Register-ScheduledTask `
        -TaskName   $TaskName `
        -Trigger    $Trigger `
        -Action     $Action `
        -Settings   $Settings `
        -Principal  $Principal2 `
        -Description "AI Analyzer 주 1회 자동 데이터 갱신 (매주 월요일 07:00)"
    Write-Host "태스크 등록 완료 (Interactive 모드)"
}

# ── Daily Telegram 리포트 태스크 (매일 오전 8시) ──────────────
Write-Host ""
Write-Host "Telegram Daily 리포트 태스크 등록 중..."

if (Get-ScheduledTask -TaskName $TaskNameDaily -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskNameDaily -Confirm:$false
    Write-Host "기존 Daily 태스크 제거됨"
}

$TriggerDaily = New-ScheduledTaskTrigger -Daily -At "08:00AM"

$ActionDaily = New-ScheduledTaskAction `
    -Execute       "python" `
    -Argument      "-X utf8 `"$TelegramAgent`" --daily" `
    -WorkingDirectory $ScriptDir

$SettingsDaily = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances  IgnoreNew `
    -StartWhenAvailable $true

try {
    Register-ScheduledTask `
        -TaskName   $TaskNameDaily `
        -Trigger    $TriggerDaily `
        -Action     $ActionDaily `
        -Settings   $SettingsDaily `
        -Principal  $Principal `
        -Description "AI Analyzer 텔레그램 데일리 리포트 (매일 08:00)"

    Write-Host "======================================================"
    Write-Host "태스크 등록 완료: $TaskNameDaily"
    Write-Host "실행 주기: 매일 오전 8:00"
    Write-Host "스크립트: $TelegramAgent --daily"
    Write-Host "======================================================"
} catch {
    Write-Host "[경고] Daily 태스크 S4U 실패, Interactive로 폴백: $_"
    $Principal2Daily = New-ScheduledTaskPrincipal `
        -UserId    $env:USERNAME `
        -LogonType Interactive `
        -RunLevel  Highest
    Register-ScheduledTask `
        -TaskName   $TaskNameDaily `
        -Trigger    $TriggerDaily `
        -Action     $ActionDaily `
        -Settings   $SettingsDaily `
        -Principal  $Principal2Daily `
        -Description "AI Analyzer 텔레그램 데일리 리포트 (매일 08:00)"
    Write-Host "Daily 태스크 등록 완료 (Interactive 모드)"
}

Write-Host ""
Write-Host "ntfy.sh 알림 구독 방법:"
Write-Host "  1. https://ntfy.sh 또는 앱 스토어에서 'ntfy' 앱 설치"
Write-Host "  2. 채널 구독: ai-analyzer-hwangatwork"
Write-Host "  3. 파이프라인 완료/실패 시 자동 푸시 알림 수신"
Write-Host ""
Write-Host "수동 실행 테스트:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  python `"$TelegramAgent`" --test"
Write-Host ""
Write-Host "태스크 제거:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskNameDaily' -Confirm:`$false"
