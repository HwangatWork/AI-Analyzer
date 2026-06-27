# -*- coding: utf-8 -*-
"""
Phase 13-B-2 회귀 테스트: aprf_schema_check.py (SubagentStop hook).

Tests:
T-APRF-HSC-1: --selftest 모드 exit 0 + "PASS" stdout
T-APRF-HSC-2: .active 플래그 없으면 즉시 exit 0 (no-op)
T-APRF-HSC-3: _extract_json_block 이 fenced ```json 블록 파싱
T-APRF-HSC-4: _extract_json_block 이 plain text 에서 None 반환
T-APRF-HSC-5: _validate 가 invalid enum 거부

DC: Phase 13-B-2 완료 기준 (DC-4, DC-5) 일부 사전 검증.
hook 실제 lifecycle (Claude Code SubagentStop trigger)은 dogfood 단계에서 검증.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "aprf_schema_check.py"
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "peer_review_response.schema.json"


def _import_hook_module():
    """Load aprf_schema_check.py as a Python module (no main() execution)."""
    spec = importlib.util.spec_from_file_location("aprf_schema_check", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook_subprocess(stdin_payload: dict, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_T_APRF_HSC_1_selftest_passes():
    """--selftest exits 0 with 'PASS' in stdout."""
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH), "--selftest"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"selftest exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "PASS" in result.stdout, f"selftest stdout missing PASS: {result.stdout!r}"


def test_T_APRF_HSC_2_skip_when_inactive():
    """Hook exits 0 immediately when .active flag is absent (no APRF in flight)."""
    active_flag = _REPO_ROOT / "output" / "peer_review" / ".active"
    if active_flag.exists():
        pytest.skip("output/peer_review/.active currently present — skip inactive-path test")

    payload = {
        "session_id": "test-session",
        "transcript_path": "",
        "agent_type": "news-agent",
        "hook_event_name": "SubagentStop",
    }
    result = _run_hook_subprocess(payload)
    assert result.returncode == 0, (
        f"inactive hook should exit 0, got {result.returncode}\nstderr: {result.stderr}"
    )


def test_T_APRF_HSC_3_extract_fenced_json():
    """_extract_json_block parses ```json fenced blocks."""
    mod = _import_hook_module()
    text = 'Header text\n```json\n{"agent": "x", "n": 1}\n```\nTrailing'
    result = mod._extract_json_block(text)
    assert result == {"agent": "x", "n": 1}


def test_T_APRF_HSC_4_extract_returns_none_for_plain_text():
    """_extract_json_block returns None when no JSON object is present."""
    mod = _import_hook_module()
    assert mod._extract_json_block("plain narrative only — no JSON here") is None
    assert mod._extract_json_block("") is None


def test_T_APRF_HSC_5_validate_rejects_invalid_enum():
    """_validate flags invalid domain_relevance enum value."""
    mod = _import_hook_module()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    bad_payload = {
        "agent": "news-agent",
        "domain_relevance": "tangent",  # not in {direct, indirect, none}
        "agreement": "agree",
        "urgency_vote": 1,
        "reason": "valid reason text here for testing the validator",
    }
    valid, err = mod._validate(bad_payload, schema)
    assert valid is False
    assert err, "error message should be non-empty"
