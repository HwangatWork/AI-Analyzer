# -*- coding: utf-8 -*-
"""
Phase 6-4 회귀 테스트: failure_memory.json 패턴 기억 레이어 (5개)

T-64-1: _load_failure_memory() — 파일 없으면 빈 구조 반환
T-64-2: _record_failure() — 동일 agent+type이면 count 증가
T-64-3: _record_success() — 성공 시 resolved=true
T-64-4: _check_repeat_failures() — count >= 3 탐지 → HIGH severity
T-64-5: 멱등성 — 여러 번 기록해도 JSON 손상 없음
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_orchestrator import (
    _load_failure_memory,
    _record_failure,
    _record_success,
    _check_repeat_failures,
)


def test_T_64_1_load_empty(tmp_path):
    """T-64-1: 파일 없을 때 빈 구조 반환."""
    result = _load_failure_memory(tmp_path / "nonexistent.json")
    assert result == {"patterns": []}, f"T-64-1 FAIL: {result}"


def test_T_64_2_record_count_increment(tmp_path):
    """T-64-2: 동일 agent+type 2회 호출 → count=2."""
    p = tmp_path / "fm.json"
    _record_failure("run_foo.py", "crash", "err1", p)
    _record_failure("run_foo.py", "crash", "err2", p)
    mem = _load_failure_memory(p)
    entry = next((x for x in mem["patterns"] if x["agent"] == "run_foo.py"), None)
    assert entry is not None, "T-64-2 FAIL: 패턴 없음"
    assert entry["count"] == 2, f"T-64-2 FAIL: count={entry['count']} (expected 2)"
    assert entry["last_error"] == "err2", "T-64-2 FAIL: last_error 미갱신"


def test_T_64_3_record_success_resolves(tmp_path):
    """T-64-3: 실패 기록 후 _record_success() → resolved=true."""
    p = tmp_path / "fm.json"
    _record_failure("run_bar.py", "timeout", "timed out", p)
    assert not _load_failure_memory(p)["patterns"][0]["resolved"], "사전조건 실패"
    _record_success("run_bar.py", p)
    mem = _load_failure_memory(p)
    entry = next(x for x in mem["patterns"] if x["agent"] == "run_bar.py")
    assert entry["resolved"] is True, f"T-64-3 FAIL: resolved={entry['resolved']}"


def test_T_64_4_check_repeat_failures_detects(tmp_path):
    """T-64-4: count >= 3 미해결 패턴 → SA-FM severity=HIGH."""
    p = tmp_path / "fm.json"
    for _ in range(3):
        _record_failure("run_baz.py", "dc_fail", "DC-2 FAIL", p)
    result = _check_repeat_failures(p)
    assert result["severity"] == "HIGH", (
        f"T-64-4 FAIL: severity={result['severity']} (expected HIGH)"
    )
    assert "run_baz.py" in result["detail"], (
        f"T-64-4 FAIL: agent not in detail — {result['detail']}"
    )


def test_T_64_5_idempotent_no_corruption(tmp_path):
    """T-64-5: 10회 연속 기록 후 JSON 유효 + count=10."""
    p = tmp_path / "fm.json"
    for i in range(10):
        _record_failure("run_x.py", "crash", f"error {i}", p)

    raw = p.read_text(encoding="utf-8")
    mem = json.loads(raw)  # raises if corrupt

    assert isinstance(mem, dict), "T-64-5 FAIL: JSON 손상"
    assert "patterns" in mem, "T-64-5 FAIL: patterns 키 없음"
    entry = next((x for x in mem["patterns"] if x["agent"] == "run_x.py"), None)
    assert entry is not None, "T-64-5 FAIL: 패턴 없음"
    assert entry["count"] == 10, f"T-64-5 FAIL: count={entry['count']} (expected 10)"
