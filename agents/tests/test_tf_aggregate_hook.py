# -*- coding: utf-8 -*-
"""
Phase 13-B-2 hook 2/4 회귀: tf_aggregate.py (PostToolBatch).

Tests:
T_TF_HA_1: --selftest 모드 exit 0 + "PASS" stdout
T_TF_HA_2: .active 부재 시 즉시 exit 0
T_TF_HA_3: 4 고정 섹션이 모두 생성됨
T_TF_HA_4: Meta-patterns 섹션이 ≥5 agents 동일 파일 참조 시 트리거
T_TF_HA_5: Meta-patterns 섹션이 <5 agents 참조 시 미트리거
T_TF_HA_6: Minority Dissent 섹션이 lone direct dissenter (reason ≥50) 시 트리거
T_TF_HA_7: Minority Dissent 섹션이 dissent 없을 때 미트리거
T_TF_HA_8: _collect_task_outputs가 tool_calls 페이로드 형식 추출

DC-5 일부 사전 검증. 실제 PostToolBatch lifecycle firing은 dogfood에서.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "tf_aggregate.py"


def _import_hook_module():
    spec = importlib.util.spec_from_file_location("tf_aggregate", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook_subprocess(stdin_payload: dict, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_T_TF_HA_1_selftest_passes():
    """--selftest exits 0 with 'PASS' in stdout."""
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH), "--selftest"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"selftest exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "PASS" in result.stdout, f"selftest stdout missing PASS: {result.stdout!r}"


def test_T_TF_HA_2_skip_when_inactive():
    """Hook exits 0 immediately when .active flag is absent."""
    active_flag = _REPO_ROOT / "output" / "peer_review" / ".active"
    if active_flag.exists():
        pytest.skip("output/peer_review/.active currently present — skip inactive-path test")

    payload = {
        "session_id": "test-session",
        "tool_calls": [{"tool_name": "Task", "tool_output": "ignored"}],
    }
    result = _run_hook_subprocess(payload)
    assert result.returncode == 0


def test_T_TF_HA_3_four_fixed_sections_always_present():
    """All 4 fixed section headers appear regardless of conditional triggers."""
    mod = _import_hook_module()
    responses = mod._synthetic_responses(3)  # too few for meta/minority
    text = mod._build_aggregate(responses)
    for header in [
        "## 1. Consensus Matrix",
        "## 2. Urgency Revote",
        "## 3. New Items Surfaced",
        "## 4. Recommended Action Order",
    ]:
        assert header in text, f"missing fixed section: {header}"


def test_T_TF_HA_4_meta_patterns_triggers_at_threshold():
    """Meta-patterns section fires when ≥5 agents reference same file."""
    mod = _import_hook_module()
    # build 6 responses all referencing same file
    responses = []
    for i in range(6):
        responses.append({
            "agent": f"agent-{i}",
            "domain_relevance": "direct",
            "agreement": "agree",
            "urgency_vote": 1,
            "addition": {"file": "shared/path.py", "change": "fix this and verify"},
            "reason": "synthetic test response for meta pattern detection coverage",
        })
    section = mod._section_meta_patterns(responses)
    assert section is not None
    assert "## 5. Meta-Patterns" in section
    assert "shared/path.py" in section


def test_T_TF_HA_5_meta_patterns_skips_below_threshold():
    """Meta-patterns section None when only 4 agents reference same file (<5)."""
    mod = _import_hook_module()
    responses = []
    for i in range(4):
        responses.append({
            "agent": f"agent-{i}",
            "domain_relevance": "direct",
            "agreement": "agree",
            "urgency_vote": 1,
            "addition": {"file": "x.py", "change": "minor change to x"},
            "reason": "synthetic reason text for testing below threshold case",
        })
    assert mod._section_meta_patterns(responses) is None


def test_T_TF_HA_6_minority_dissent_triggers():
    """Minority Dissent fires for lone direct dissenter with reason ≥50."""
    mod = _import_hook_module()
    responses = []
    # 5 agents vote 1
    for i in range(5):
        responses.append({
            "agent": f"agent-{i}",
            "domain_relevance": "direct",
            "agreement": "agree",
            "urgency_vote": 1,
            "reason": "majority opinion reason text for testing minority dissent case",
        })
    # 1 lone direct dissenter
    responses.append({
        "agent": "lone-dissenter",
        "domain_relevance": "direct",
        "agreement": "disagree",
        "urgency_vote": 3,
        "reason": "이 항목이 사실 더 시급함 — 다른 6 agent가 놓친 구조적 결함이 있다 (50자 이상)",
    })
    section = mod._section_minority_dissent(responses)
    assert section is not None
    assert "lone-dissenter" in section
    assert "## 6. Minority Dissent" in section


def test_T_TF_HA_7_minority_dissent_skips_when_unanimous():
    """Minority Dissent section None when all agents agree on majority vote."""
    mod = _import_hook_module()
    responses = []
    for i in range(8):
        responses.append({
            "agent": f"agent-{i}",
            "domain_relevance": "direct",
            "agreement": "agree",
            "urgency_vote": 1,
            "reason": "unanimous agreement on item 1 reason text padding to fifty chars",
        })
    assert mod._section_minority_dissent(responses) is None


def test_T_TF_HA_8_collect_outputs_handles_tool_calls_shape():
    """_collect_task_outputs extracts string outputs from tool_calls shape."""
    mod = _import_hook_module()
    hook_input = {
        "tool_calls": [
            {"tool_name": "Task", "tool_output": "first task response"},
            {"tool_name": "Bash", "tool_output": "non-task ignored"},
            {"tool_name": "Task", "tool_output": "second task response"},
        ]
    }
    outputs = mod._collect_task_outputs(hook_input)
    assert outputs == ["first task response", "second task response"]
