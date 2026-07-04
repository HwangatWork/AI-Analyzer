# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — dynamics: 단계 기대값 드리프트와 전이 시그널.

drift = ΔE[k], E[k] = Σ k·p_k. 3주 이동평균으로 평활 후 차분.
MA_WINDOW_WEEKS 는 고정 설계 상수 — 백테스트 성과에 맞춰 튜닝 금지
(사전등록 원칙, 사용자 지시 2026-07-04).
"""
from __future__ import annotations

MA_WINDOW_WEEKS = 3  # FIXED — 튜닝 금지
SECOND_CYCLE_EPS = 0.05  # Stage4 drift→0 판정 폭


def expected_stage(P: dict[int, float]) -> float:
    return sum(k * p for k, p in P.items())


def drift(series: list[tuple[object, dict[int, float]]]) -> float | None:
    """주간 (date, P) 시계열의 3주 MA 평활 E[k] 차분.

    series는 시간 오름차순. MA 2개(연속 윈도우)를 만들 수 있는
    최소 길이 = MA_WINDOW_WEEKS + 1. 미달 시 None.
    """
    if len(series) < MA_WINDOW_WEEKS + 1:
        return None
    e = [expected_stage(p) for _, p in series]
    w = MA_WINDOW_WEEKS
    ma_now = sum(e[-w:]) / w
    ma_prev = sum(e[-w - 1:-1]) / w
    return ma_now - ma_prev


def signal(stage: int, drift_val: float | None) -> str | None:
    """전이 시그널 (스펙 정의 3종)."""
    if drift_val is None:
        return None
    if stage == 2:
        return "healthy-pullback" if drift_val < 0 else "overheating"
    if stage == 4 and abs(drift_val) < SECOND_CYCLE_EPS:
        return "second-cycle-candidate"
    return None
