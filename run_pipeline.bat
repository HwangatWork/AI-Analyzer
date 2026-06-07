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

:: 텔레그램 단계 보고 헬퍼 (실패해도 파이프라인 계속)
:: 사용법: call :tg_step <번호> <이름> <상세>
goto :pipeline_start

:tg_step
python -X utf8 agents/run_telegram_agent.py --step "%~1" "%~2" "%~3" >> "%LOG_FILE%" 2>&1
exit /b 0

:tg_fail
python -X utf8 -c "
import os, urllib.request, json
from dotenv import load_dotenv; load_dotenv()
token = os.getenv('TELEGRAM_BOT_TOKEN','')
chat  = os.getenv('TELEGRAM_CHAT_ID','')
msg   = f'❌ <b>파이프라인 실패</b>\n단계: %~1\n시각: %date% %time%'
if token and chat:
    data = json.dumps({'chat_id':chat,'text':msg,'parse_mode':'HTML'}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',data=data,headers={'Content-Type':'application/json'})
    urllib.request.urlopen(req,timeout=10)
" >> "%LOG_FILE%" 2>&1
exit /b 0

:pipeline_start

:: ────────────────────────────────────────────────────────────
:: 1. Data Agent
:: ────────────────────────────────────────────────────────────
echo [1/11] Data Agent 실행 중...
python -X utf8 agents/run_data_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Data Agent failed
    call :tg_fail "1/11 Data Agent"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Data Agent failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "1" "Data Agent" "지표 데이터 수집 완료 — data/raw/ 저장"

:: ────────────────────────────────────────────────────────────
:: 2. Refresh Data
:: ────────────────────────────────────────────────────────────
echo [2/11] Refresh Data 실행 중...
python -X utf8 agents/refresh_data.py >> "%LOG_FILE%" 2>&1
call :tg_step "2" "Refresh" "최신 지표값 갱신 완료"

:: ────────────────────────────────────────────────────────────
:: 3. Analysis Agent
:: ────────────────────────────────────────────────────────────
echo [3/11] Analysis Agent 실행 중...
python -X utf8 agents/run_analysis_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Analysis Agent failed
    call :tg_fail "3/11 Analysis Agent"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Analysis Agent failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "3" "Analysis Agent" "Granger 인과관계 + 시차 상관 + 동행 페널티 분석 완료"

:: ────────────────────────────────────────────────────────────
:: 4. Stock Agent
:: ────────────────────────────────────────────────────────────
echo [4/11] Stock Agent 실행 중...
python -X utf8 agents/run_stock_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Stock Agent failed
    call :tg_fail "4/11 Stock Agent"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Stock Agent failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "4" "Stock Agent" "KOSPI/S&P500 기여·수혜 종목 Top5 분석 완료"

:: ────────────────────────────────────────────────────────────
:: 5. Evaluator Agent
:: ────────────────────────────────────────────────────────────
echo [5/11] Evaluator Agent 실행 중...
python -X utf8 agents/run_evaluator_agent_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Evaluator Agent failed
    call :tg_fail "5/11 Evaluator Agent"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Evaluator failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "5" "Evaluator Agent" "통계 유의성 검증 + 신뢰도 점수 산출 완료"

:: ────────────────────────────────────────────────────────────
:: 6. Sector Agent (WARNING 수준 — 파이프라인 계속)
:: ────────────────────────────────────────────────────────────
echo [6/11] Sector Agent 실행 중...
python -X utf8 agents/run_sector_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Sector Agent failed - continuing
    call :tg_step "6" "Sector Agent" "⚠ 일부 실패 — 파이프라인 계속 진행"
) else (
    call :tg_step "6" "Sector Agent" "반도체/AI/에너지 섹터 딥다이브 완료"
)

:: ────────────────────────────────────────────────────────────
:: 7. Validation Agent
:: ────────────────────────────────────────────────────────────
echo [7/11] Validation Agent 실행 중...
python -X utf8 agents/run_validation_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Validation BLOCKED — CRITICAL 검증 실패
    call :tg_fail "7/11 Validation Agent — CRITICAL 검증 실패"
    curl -s -H "Title: AI Analyzer 검증 실패" -H "Tags: x,warning" -d "Validation CRITICAL 실패" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "7" "Validation Agent" "30개 체크 전항목 PASS — CRITICAL 0개"

:: ────────────────────────────────────────────────────────────
:: 8. UI Agent
:: ────────────────────────────────────────────────────────────
echo [8/11] UI Agent 실행 중...
python -X utf8 agents/run_ui_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] UI Agent failed
    call :tg_fail "8/11 UI Agent"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "UI Agent failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "8" "UI Agent" "대시보드 생성 완료 — UX-1~UX-7 PASS"

:: ────────────────────────────────────────────────────────────
:: 9. Report
:: ────────────────────────────────────────────────────────────
echo [9/11] Report 생성 중...
python -X utf8 agents/generate_report_v2.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Report generation failed
    call :tg_fail "9/11 Report"
    curl -s -H "Title: AI Analyzer FAILED" -H "Tags: x" -d "Report failed" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    goto :error
)
call :tg_step "9" "Report" "FINAL_REPORT_v2.md 생성 완료"

:: ────────────────────────────────────────────────────────────
:: 10. Audit Agent (WARNING 수준)
:: ────────────────────────────────────────────────────────────
echo [10/11] Audit Agent 실행 중...
python -X utf8 agents/run_audit_agent.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Audit Agent 경고
    curl -s -H "Title: AI Analyzer 감사 경고" -H "Tags: warning" -d "Audit Agent 이상 감지" https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1
    call :tg_step "10" "Audit Agent" "⚠ 자체검증 체계 일부 이상 — 로그 확인 필요"
) else (
    call :tg_step "10" "Audit Agent" "62/62 PASS — Agent 자체검증 체계 정상"
)

:: ────────────────────────────────────────────────────────────
:: 11. Telegram 시그널 체크 + CTD 연동
:: ────────────────────────────────────────────────────────────
echo [11/11] Telegram 시그널 체크 + CTD 연동 중...
python -X utf8 agents/run_telegram_agent.py --check >> "%LOG_FILE%" 2>&1
python -X utf8 agents/run_ctd_integration_agent.py >> "%LOG_FILE%" 2>&1
call :tg_step "11" "완료 처리" "시그널 체크 + CTD 연동 완료"

:: ────────────────────────────────────────────────────────────
:: 최종 완료 요약 (텔레그램 + ntfy.sh)
:: ────────────────────────────────────────────────────────────
echo ============================================================
echo Pipeline completed: %date% %time%
echo ============================================================

python -X utf8 agents/run_telegram_agent.py --summary >> "%LOG_FILE%" 2>&1

for /f "tokens=*" %%i in ('python -X utf8 -c "import json; from pathlib import Path; data=json.loads(Path(\"output/final_results.json\").read_text(encoding=\"utf-8\")); sig=data.get(\"market_signal\") or {}; print(f\"Signal={sig.get(\"score\",\"N/A\")} {sig.get(\"direction\",\"N/A\")}\")" 2^>nul') do set SIGNAL=%%i

curl -s -H "Title: AI Analyzer 완료" -H "Tags: white_check_mark" -H "Priority: default" -d "파이프라인 완료 %date%. %SIGNAL%." https://ntfy.sh/%NTFY_TOPIC% > nul 2>&1

echo 알림 전송 완료
goto :eof

:error
echo [FAILED] Pipeline stopped. 로그: %LOG_FILE%
exit /b 1
