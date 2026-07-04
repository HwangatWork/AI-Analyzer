# -*- coding: utf-8 -*-
"""
Phase 12-1 CI 실패 수정 회귀 테스트 (5개)

T-CI-1: deploy-dashboard.yml "Validate credential environment" 스텝에 env: 블록 존재
T-CI-2: env: 블록에 필수 시크릿 8개 전부 포함
T-CI-3: SD-7 GitHub Actions branch 필터가 master (main 아님)
T-CI-4: audit_env_secrets.py --ci 모드 — 누락 env var → exit 1
T-CI-5: audit_env_secrets.py --ci 모드 — 전체 env var 주입 시 → exit 0
"""
import os
import re
import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
# Phase Ops-1 (2026-07-04): workflow 분리 후 Validate step 은 run-pipeline.yml 에 위치.
# 기존 deploy-dashboard.yml 은 폐기.
WORKFLOW = BASE / ".github" / "workflows" / "run-pipeline.yml"
AUDIT_SCRIPT = BASE / "scripts" / "audit_env_secrets.py"
RUN_PM_AGENT = BASE / "agents" / "run_pm_agent.py"

REQUIRED_SECRETS = {
    "FRED_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "KRX_ID",
    "KRX_PW",
    "ECOS_API_KEY",
    "ANTHROPIC_API_KEY",
    "CUSTOMS_API_KEY",
    # 2026-07-04: NOTION_TOKEN 제거 (사용자 결정)
    # 노션 저장은 Claude Code 세션에서 MCP 로 처리 (사용자가 요청할 때만).
    # GitHub Actions 서버 자동 실행에서는 노션 자동 저장 안 함 → secret 불필요.
}


# ── T-CI-1 ────────────────────────────────────────────────────────────────

def test_T_CI_1_validate_step_has_env_block():
    """T-CI-1: 'Validate credential environment' 스텝 바로 뒤에 env: 블록 존재 확인."""
    content = WORKFLOW.read_text(encoding="utf-8")
    # Validate step과 그 이후 env: 블록이 같은 step 안에 있는지 확인
    # 패턴: "Validate credential environment" 다음에 env: 가 run: 보다 먼저 나와야 함
    validate_idx = content.find("Validate credential environment")
    assert validate_idx != -1, "T-CI-1 FAIL: Validate credential environment 스텝 미존재"

    # 해당 스텝 블록 추출 (다음 "- name:" 전까지)
    step_block = content[validate_idx:]
    next_step = step_block.find("- name:", 1)
    if next_step != -1:
        step_block = step_block[:next_step]

    env_pos = step_block.find("\n        env:")
    run_pos = step_block.find("\n        run:")
    assert env_pos != -1, "T-CI-1 FAIL: Validate 스텝에 env: 블록 없음"
    assert env_pos < run_pos, "T-CI-1 FAIL: env: 블록이 run: 뒤에 위치"


# ── T-CI-2 ────────────────────────────────────────────────────────────────

def test_T_CI_2_validate_step_env_has_all_secrets():
    """T-CI-2: Validate 스텝의 env: 블록에 필수 시크릿 8개 전부 포함."""
    content = WORKFLOW.read_text(encoding="utf-8")

    validate_idx = content.find("Validate credential environment")
    step_block = content[validate_idx:]
    next_step = step_block.find("- name:", 1)
    if next_step != -1:
        step_block = step_block[:next_step]

    found = set(re.findall(r"secrets\.([A-Z0-9_]+)", step_block))
    missing = REQUIRED_SECRETS - found
    assert not missing, f"T-CI-2 FAIL: Validate 스텝 env: 블록에 시크릿 누락: {missing}"


# ── T-CI-3 ────────────────────────────────────────────────────────────────

def test_T_CI_3_sd7_uses_branch_master():
    """T-CI-3: SD-7 GitHub Actions 브랜치 필터가 master (main 아님)."""
    content = (RUN_PM_AGENT).read_text(encoding="utf-8")

    # SD-7 URL 패턴 직접 검색 (주석/docstring과 달리 실제 URL에만 branch= 사용)
    assert "branch=master" in content, (
        "T-CI-3 FAIL: run_pm_agent.py에 branch=master 없음 — SD-7 픽스 미적용"
    )
    assert "branch=main" not in content, (
        "T-CI-3 FAIL: run_pm_agent.py에 branch=main 잔존"
    )


# ── T-CI-4 ────────────────────────────────────────────────────────────────

def test_T_CI_4_audit_ci_fails_when_env_missing():
    """T-CI-4: --ci 모드는 시크릿 env var 누락 시 exit 1 반환."""
    env = {k: v for k, v in os.environ.items()
           if k not in REQUIRED_SECRETS}
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(AUDIT_SCRIPT), "--ci"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1, (
        f"T-CI-4 FAIL: env var 누락인데 exit 0 반환\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ── T-CI-5 ────────────────────────────────────────────────────────────────

def test_T_CI_5_audit_ci_passes_when_all_env_present():
    """T-CI-5: --ci 모드는 필수 env var 전부 주입 시 exit 0 반환."""
    env = os.environ.copy()
    for key in REQUIRED_SECRETS:
        env.setdefault(key, "dummy_value_for_test")
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(AUDIT_SCRIPT), "--ci"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"T-CI-5 FAIL: 전체 env 주입인데 exit 1 반환\nstdout={result.stdout}\nstderr={result.stderr}"
    )
