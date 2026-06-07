@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo AI Analyzer - Full Pipeline Run
echo %date% %time%
echo ============================================================

cd /d "%~dp0"

set NTFY_TOPIC=ai-analyzer-hwangatwork
:: 로그 날짜는 실행 시점 동적 생성
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set LOG_DATE=%DT:~0,8%
set LOG_FILE=%~dp0logs\pipeline_%LOG_DATE%.log

if not exist "%~dp0logs" mkdir "%~dp0logs"

:: 파이프라인 실행
python -X utf8 agents/run_data_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Data Agent failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x,chart_with_downwards_trend" -d "Data Agent failed at %date% %time%. Check %LOG_FILE%" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/refresh_data.py >> "%LOG_FILE%" 2>&1

python -X utf8 agents/run_analysis_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Analysis Agent failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Analysis Agent failed at %date% %time%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/run_stock_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Stock Agent failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Stock Agent failed at %date% %time%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/run_evaluator_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Evaluator Agent failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Evaluator failed at %date% %time%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/run_sector_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Sector Agent failed - continuing pipeline
)

python -X utf8 agents/run_validation_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Validation Agent BLOCKED pipeline — CRITICAL 검증 실패
    curl -s -H "Title: AI Analyzer 검증 실패" -H "Tags: x,warning" -d "Validation Agent가 파이프라인을 차단했습니다. 로그 확인: %LOG_FILE%" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/run_ui_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] UI Agent failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "UI Agent failed at %date% %time%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/generate_report_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Report generation failed
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Report failed at %date% %time%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)

python -X utf8 agents/run_audit_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Audit Agent 경고 — Agent 자체검증 체계 이상 감지. 로그 확인: %LOG_FILE%
    curl -s -H "Title: AI Analyzer 감사 경고" -H "Tags: warning" -d "Audit Agent: Done Criteria 검증 체계에 이상이 감지되었습니다. 로그: %LOG_FILE%" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
)

python -X utf8 agents/run_telegram_agent.py --check >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Telegram Agent 경고 — 시그널 알림 전송 실패 (파이프라인 계속 진행)
)

echo ============================================================
echo Pipeline completed: %date% %time%
echo Output: output\dashboard.html
echo        output\final_results.json
echo        output\FINAL_REPORT_v2.md
echo Log:    %LOG_FILE%
echo ============================================================

:: ntfy.sh 알림 전송 (무료 웹훅, 설치 불필요)
:: 구독: ntfy.sh 앱 설치 후 ai-analyzer-hwangatwork 채널 구독
:: 또는 브라우저에서 https://ntfy.sh/ai-analyzer-hwangatwork
python -X utf8 -c "
import json
from pathlib import Path
data = json.loads(Path('output/final_results.json').read_text(encoding='utf-8'))
sig = data.get('market_signal') or {}
score = sig.get('score', 'N/A')
direction = sig.get('direction', 'N/A')
print(f'Signal={score} ({direction})')
" 2>&1 > nul

for /f "tokens=*" %%i in ('python -X utf8 -c "import json; from pathlib import Path; data=json.loads(Path(\"output/final_results.json\").read_text(encoding=\"utf-8\")); sig=data.get(\"market_signal\") or {}; print(f\"Signal={sig.get(\"score\",\"N/A\")} {sig.get(\"direction\",\"N/A\")}\")"') do set SIGNAL=%%i

curl -s -H "Title: AI Analyzer 완료" -H "Tags: white_check_mark,chart_with_upwards_trend" -H "Priority: default" -d "파이프라인 완료 %date%. %SIGNAL%. 대시보드: output/dashboard.html" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1

echo 알림 전송 완료 (ntfy.sh/%NTFY_TOPIC%)
goto :eof

:error
echo [FAILED] Pipeline stopped. 로그: %LOG_FILE%
exit /b 1
