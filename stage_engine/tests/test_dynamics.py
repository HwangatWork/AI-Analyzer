# -*- coding: utf-8 -*-
"""dynamics 합성 시퀀스 단위 테스트 (스펙 S4 요구).

- 단조 진행(advancing) 시퀀스 → drift > 0
- 단조 후퇴(retreating) 시퀀스 → drift < 0
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from stage_engine.dynamics import (  # noqa: E402
    MA_WINDOW_WEEKS, drift, expected_stage, signal,
)


def _p(stage_center: float) -> dict[int, float]:
    """E[k]=stage_center 근방의 합성 P 벡터 (두 인접 단계 혼합)."""
    lo = int(stage_center)
    frac = stage_center - lo
    P = {k: 0.0 for k in range(5)}
    if lo >= 4:
        P[4] = 1.0
    else:
        P[lo] = 1.0 - frac
        P[lo + 1] = frac
    return P


def test_expected_stage():
    assert expected_stage({0: 1.0, 1: 0, 2: 0, 3: 0, 4: 0}) == 0.0
    assert abs(expected_stage(_p(2.5)) - 2.5) < 1e-9


def test_monotonic_advancing_gives_positive_drift():
    centers = [0.5, 0.8, 1.1, 1.4, 1.7, 2.0, 2.3]
    series = [(i, _p(c)) for i, c in enumerate(centers)]
    d = drift(series)
    assert d is not None and d > 0, f"진행 시퀀스 drift={d}"


def test_monotonic_retreating_gives_negative_drift():
    centers = [3.0, 2.7, 2.4, 2.1, 1.8, 1.5, 1.2]
    series = [(i, _p(c)) for i, c in enumerate(centers)]
    d = drift(series)
    assert d is not None and d < 0, f"후퇴 시퀀스 drift={d}"


def test_flat_sequence_gives_zero_drift():
    series = [(i, _p(2.0)) for i in range(6)]
    d = drift(series)
    assert d is not None and abs(d) < 1e-12


def test_too_short_series_returns_none():
    series = [(i, _p(1.0)) for i in range(MA_WINDOW_WEEKS)]
    assert drift(series) is None


def test_signals():
    assert signal(2, -0.1) == "healthy-pullback"
    assert signal(2, +0.1) == "overheating"
    assert signal(4, 0.01) == "second-cycle-candidate"
    assert signal(4, 0.5) is None
    assert signal(0, 0.3) is None
    assert signal(2, None) is None


def test_ma_window_is_fixed_constant():
    assert MA_WINDOW_WEEKS == 3
