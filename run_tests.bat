@echo off
:: AI Analyzer 회귀 테스트 스위트 (Phase 1)
:: 실행: run_tests.bat
cd /d "%~dp0"
echo [REGRESSION TEST] 시작...
python -m pytest agents/tests/test_regression.py -v --tb=short --no-header -q
echo [REGRESSION TEST] 완료.
