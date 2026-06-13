# -*- coding: utf-8 -*-
"""
Phase 6-3b 회귀 테스트: .md Input/Output Contract 참조 로직 (5개)

T-63B-1: _load_agent_spec() — 실존 .md에서 dict 반환
T-63B-2: _load_agent_spec() — .md 없으면 빈 dict 반환
T-63B-3: _verify_input_contract() — 입력 파일 없으면 False 반환
T-63B-4: _verify_output_contract() — 출력 파일 없으면 False 반환
T-63B-5: _load_agent_spec() — 손상된 .md에서도 빈 dict 반환 (fault-tolerant)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_orchestrator import (
    _load_agent_spec,
    _verify_input_contract,
    _verify_output_contract,
    _SCRIPT_TO_MD_STEM,
    _CLAUDE_AGENTS_DIR,
)


def test_T_63B_1_load_existing_md():
    """T-63B-1: 실존 .md (data-agent)에서 dict + output_contract 파일 포함."""
    spec = _load_agent_spec("run_data_agent_v2.py")
    assert isinstance(spec, dict), f"T-63B-1 FAIL: dict가 아님 — {type(spec)}"
    assert "input_contract" in spec,  "T-63B-1 FAIL: input_contract 키 없음"
    assert "output_contract" in spec, "T-63B-1 FAIL: output_contract 키 없음"
    assert "done_criteria" in spec,   "T-63B-1 FAIL: done_criteria 키 없음"
    assert "forbidden" in spec,       "T-63B-1 FAIL: forbidden 키 없음"
    # data-agent 출력에 collection_report_v2.json이 파싱되어야 함
    out_paths = spec["output_contract"]
    assert any("collection_report_v2.json" in p for p in out_paths), (
        f"T-63B-1 FAIL: collection_report_v2.json 미파싱 — out_paths={out_paths}"
    )


def test_T_63B_2_load_missing_md():
    """T-63B-2: 매핑 없는 스크립트 → 빈 dict."""
    spec = _load_agent_spec("generate_report_v2.py")
    assert spec == {}, f"T-63B-2 FAIL: 빈 dict가 아님 — {spec}"


def test_T_63B_3_verify_input_contract_missing(tmp_path):
    """T-63B-3: 입력 파일 없으면 (False, reason) 반환."""
    spec = {
        "input_contract": ["data/processed/nonexistent_file_xyz.json"],
        "output_contract": [],
        "done_criteria": [],
        "forbidden": [],
    }
    ok, reason = _verify_input_contract(spec, "test-agent")
    assert ok is False, f"T-63B-3 FAIL: ok={ok} (expected False)"
    assert "nonexistent_file_xyz.json" in reason, (
        f"T-63B-3 FAIL: 파일명이 reason에 없음 — {reason}"
    )


def test_T_63B_4_verify_output_contract_missing(tmp_path):
    """T-63B-4: 출력 파일 없으면 (False, reason) 반환."""
    spec = {
        "input_contract": [],
        "output_contract": ["output/nonexistent_output_xyz.json"],
        "done_criteria": [],
        "forbidden": [],
    }
    ok, reason = _verify_output_contract(spec, "test-agent")
    assert ok is False, f"T-63B-4 FAIL: ok={ok} (expected False)"
    assert "nonexistent_output_xyz.json" in reason, (
        f"T-63B-4 FAIL: 파일명이 reason에 없음 — {reason}"
    )


def test_T_63B_5_fault_tolerant_malformed_md(tmp_path):
    """T-63B-5: 손상된 .md → 빈 dict 반환 (crash 없음)."""
    import pm_orchestrator as _pm

    # 임시로 다른 .md 파일 경로를 가리키도록 monkeypatching
    original_dir = _pm._CLAUDE_AGENTS_DIR
    _pm._CLAUDE_AGENTS_DIR = tmp_path

    # 손상된 .md 파일 생성
    malformed = tmp_path / "data-agent.md"
    malformed.write_text("<<< NOT VALID MARKDOWN \x00\xff >>>", encoding="utf-8",
                         errors="replace")

    try:
        spec = _load_agent_spec("run_data_agent_v2.py")
        # 손상된 파일이라도 dict 반환 (crash 없음)
        assert isinstance(spec, dict), f"T-63B-5 FAIL: crash 또는 dict가 아님 — {spec}"
        # 파일이 존재하면 빈 리스트로 안전하게 파싱
        assert "input_contract" in spec or spec == {}, (
            f"T-63B-5 FAIL: 예상치 못한 반환값 — {spec}"
        )
    finally:
        _pm._CLAUDE_AGENTS_DIR = original_dir
