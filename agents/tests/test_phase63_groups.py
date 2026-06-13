# -*- coding: utf-8 -*-
"""
Phase 6-3 회귀 테스트: EXECUTION_GROUPS 병렬 실행 구조 검증 (4개)

T-63-1: EXECUTION_GROUPS — 4개 그룹(A/B/C/D) 정의됨
T-63-2: Group B is_parallel=True, 나머지는 False
T-63-3: EXECUTION_GROUPS 전체 스크립트 == PIPELINE_STAGES 전체 스크립트 (순서 무관)
T-63-4: Group B 스크립트가 STAGE_DEPS에서 refresh_data.py 이하 의존성만 가짐
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_orchestrator import EXECUTION_GROUPS, PIPELINE_STAGES, STAGE_DEPS

import pytest


def test_T_63_1_four_groups():
    """T-63-1: EXECUTION_GROUPS는 정확히 4개 그룹(A/B/C/D)."""
    names = [g[0] for g in EXECUTION_GROUPS]
    assert names == ["A", "B", "C", "D"], (
        f"T-63-1 FAIL: 그룹 이름 불일치 — {names}"
    )


def test_T_63_2_group_b_parallel_only():
    """T-63-2: Group B만 is_parallel=True, 나머지는 False."""
    for name, is_par, _ in EXECUTION_GROUPS:
        if name == "B":
            assert is_par, "T-63-2 FAIL: Group B is_parallel != True"
        else:
            assert not is_par, f"T-63-2 FAIL: Group {name} is_parallel != False"


def test_T_63_3_full_coverage():
    """T-63-3: EXECUTION_GROUPS 스크립트 집합 == PIPELINE_STAGES 스크립트 집합."""
    group_scripts: set[str] = {
        s for _, _, scripts in EXECUTION_GROUPS for s in scripts
    }
    pipeline_scripts: set[str] = {s for s, *_ in PIPELINE_STAGES}
    missing = pipeline_scripts - group_scripts
    extra   = group_scripts - pipeline_scripts
    assert not missing, f"T-63-3 FAIL: PIPELINE_STAGES에만 있음 — {missing}"
    assert not extra,   f"T-63-3 FAIL: EXECUTION_GROUPS에만 있음 — {extra}"


def test_T_63_4_group_b_deps():
    """T-63-4: Group B 스크립트는 refresh_data.py 또는 의존성 없음만 허용."""
    allowed = {"refresh_data.py", "run_data_agent_v2.py"}
    _, _, group_b = next(g for g in EXECUTION_GROUPS if g[0] == "B")
    for script in group_b:
        deps = set(STAGE_DEPS.get(script, []))
        bad = deps - allowed - {script}
        assert not bad, (
            f"T-63-4 FAIL: {script} deps={deps} — refresh 이외 의존성 있음: {bad}"
        )
