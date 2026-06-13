# -*- coding: utf-8 -*-
"""
Phase 9 회귀 테스트: VIX 동적 스케일링 구조 (5개)

T-9-1: _get_vix_tier() 반환값이 유효한 티어 문자열
T-9-2: _dynamic_group_b("neutral") → 핵심 2개만 (_GROUP_B_NEUTRAL)
T-9-3: _dynamic_group_b("caution") → Group B 전체 4개
T-9-4: _dynamic_group_b("extreme") → Group B 전체 4개
T-9-5: _get_vix_tier() — VIX 데이터 없으면 'caution' 반환
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_orchestrator import (
    _get_vix_tier,
    _dynamic_group_b,
    _GROUP_B_NEUTRAL,
    EXECUTION_GROUPS,
    BASE_DIR,
)


_VALID_TIERS = {"neutral", "caution", "extreme"}
_GROUP_B_ALL = next(scripts for name, _, scripts in EXECUTION_GROUPS if name == "B")


def test_T_9_1_vix_tier_valid():
    """T-9-1: _get_vix_tier() 반환값이 'neutral'|'caution'|'extreme' 중 하나."""
    tier = _get_vix_tier()
    assert tier in _VALID_TIERS, f"T-9-1 FAIL: tier={tier!r} not in {_VALID_TIERS}"


def test_T_9_2_neutral_returns_core_two():
    """T-9-2: neutral 티어 → _GROUP_B_NEUTRAL (핵심 2개만)."""
    scripts = _dynamic_group_b("neutral")
    assert scripts == _GROUP_B_NEUTRAL, (
        f"T-9-2 FAIL: neutral scripts={scripts} != _GROUP_B_NEUTRAL={_GROUP_B_NEUTRAL}"
    )
    assert len(scripts) == 2, f"T-9-2 FAIL: len={len(scripts)} (expected 2)"


def test_T_9_3_caution_returns_full_group_b():
    """T-9-3: caution 티어 → Group B 전체."""
    scripts = _dynamic_group_b("caution")
    assert set(scripts) == set(_GROUP_B_ALL), (
        f"T-9-3 FAIL: scripts={scripts} != Group B all={_GROUP_B_ALL}"
    )


def test_T_9_4_extreme_returns_full_group_b():
    """T-9-4: extreme 티어 → Group B 전체 (심층 분석은 별도 실행 예정)."""
    scripts = _dynamic_group_b("extreme")
    assert set(scripts) == set(_GROUP_B_ALL), (
        f"T-9-4 FAIL: scripts={scripts} != Group B all={_GROUP_B_ALL}"
    )


def test_T_9_5_no_vix_data_fallback_caution(monkeypatch, tmp_path):
    """T-9-5: VIX 데이터 없으면 _get_vix_tier() → 'caution'."""
    import pm_orchestrator as _pm
    monkeypatch.setattr(_pm, "BASE_DIR", tmp_path)
    tier = _get_vix_tier()
    assert tier == "caution", f"T-9-5 FAIL: tier={tier!r} (expected 'caution')"
