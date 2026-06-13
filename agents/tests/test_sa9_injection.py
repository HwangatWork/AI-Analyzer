# -*- coding: utf-8 -*-
"""
SA9-T4 회귀 테스트: _sa9_inject_done_criteria() 검증 (5개)

T-SA9-1: _SA9_INJECT_TARGETS 7개 파일 모두 _DC_INJECT_MARKER 포함
T-SA9-2: 7개 파일 모두 DONE_CRITERIA: PASS 포함
T-SA9-3: 7개 파일 모두 Python syntax 이상 없음
T-SA9-4: run_news_agent.py — DC 블록이 sys.exit(0) 직전에 위치
T-SA9-5: _sa9_inject_done_criteria() 멱등성 — 2차 실행 시 주입 0개, skip 7개
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_orchestrator import (
    _DC_INJECT_MARKER,
    _SA9_INJECT_TARGETS,
    _sa9_inject_done_criteria,
    AGENTS_DIR,
)

import pytest


def test_T_SA9_1_marker_present():
    """T-SA9-1: 7개 주입 대상 파일에 _DC_INJECT_MARKER 포함."""
    missing = []
    for fname in _SA9_INJECT_TARGETS:
        text = (AGENTS_DIR / fname).read_text(encoding="utf-8")
        if _DC_INJECT_MARKER not in text:
            missing.append(fname)
    assert not missing, f"T-SA9-1 FAIL: marker 없음 — {missing}"


def test_T_SA9_2_done_criteria_pass_present():
    """T-SA9-2: 7개 주입 대상 파일에 'DONE_CRITERIA: PASS' 포함."""
    missing = []
    for fname in _SA9_INJECT_TARGETS:
        text = (AGENTS_DIR / fname).read_text(encoding="utf-8")
        if "DONE_CRITERIA: PASS" not in text:
            missing.append(fname)
    assert not missing, f"T-SA9-2 FAIL: DONE_CRITERIA: PASS 없음 — {missing}"


def test_T_SA9_3_syntax_valid():
    """T-SA9-3: 7개 주입 대상 파일 Python syntax 오류 없음."""
    errors = []
    for fname in _SA9_INJECT_TARGETS:
        src = (AGENTS_DIR / fname).read_text(encoding="utf-8")
        try:
            compile(src, fname, "exec")
        except SyntaxError as e:
            errors.append(f"{fname}: {e}")
    assert not errors, f"T-SA9-3 FAIL: syntax error — {errors}"


def test_T_SA9_4_news_agent_dc_before_exit():
    """T-SA9-4: run_news_agent.py DC 블록이 sys.exit(0) 직전에 위치."""
    text = (AGENTS_DIR / "run_news_agent.py").read_text(encoding="utf-8")
    marker_pos = text.rfind(_DC_INJECT_MARKER)
    exit0_pos  = text.rfind("    sys.exit(0)")
    assert marker_pos != -1, "T-SA9-4 FAIL: DC 마커 없음"
    assert exit0_pos  != -1, "T-SA9-4 FAIL: sys.exit(0) 없음"
    assert marker_pos < exit0_pos, (
        f"T-SA9-4 FAIL: DC 마커({marker_pos}) >= sys.exit(0)({exit0_pos}) — 순서 역전"
    )


def test_T_SA9_5_idempotent():
    """T-SA9-5: _sa9_inject_done_criteria() 2차 실행 — 주입 0개, skip 7개."""
    result = _sa9_inject_done_criteria()
    detail = result.get("detail", "")
    # injected list should be empty
    assert "주입: []" in detail, f"T-SA9-5 FAIL: 2차 실행에서 주입 발생 — {detail}"
    # all 7 targets should appear in skipped
    for fname in _SA9_INJECT_TARGETS:
        assert fname in detail, f"T-SA9-5 FAIL: {fname} skip 목록 없음 — {detail}"
