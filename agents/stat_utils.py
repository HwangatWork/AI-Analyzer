# -*- coding: utf-8 -*-
"""
공통 통계 유틸리티 — constant series 안전 래퍼
pearsonr/linregress 전 std==0 검사를 표준화한다.
"""
import numpy as np
from typing import Optional, Tuple

# 분산 없음 판정 임계값 (절대 기준 — 수치 오차 허용)
_ZERO_STD_THRESHOLD = 1e-10


def is_constant(arr: np.ndarray, threshold: float = _ZERO_STD_THRESHOLD) -> bool:
    """배열이 사실상 상수인지 확인 (거래정지·forward-fill 감지용)."""
    return bool(np.std(arr) < threshold)


def safe_pearsonr(
    x: np.ndarray,
    y: np.ndarray,
    threshold: float = _ZERO_STD_THRESHOLD,
) -> Tuple[Optional[float], Optional[float]]:
    """
    pearsonr의 안전 래퍼.
    x 또는 y가 상수일 때 (None, None) 반환 — ValueError 방지.

    Returns:
        (r, p) 또는 (None, None)
    """
    from scipy import stats
    if is_constant(x, threshold) or is_constant(y, threshold):
        return None, None
    r, p = stats.pearsonr(x, y)
    return float(r), float(p)


def safe_linregress(
    x: np.ndarray,
    y: np.ndarray,
    threshold: float = _ZERO_STD_THRESHOLD,
) -> Optional[dict]:
    """
    linregress의 안전 래퍼.
    x가 상수일 때 None 반환 (기울기 계산 불가).

    Returns:
        {"slope", "intercept", "r", "p", "stderr"} 또는 None
    """
    from scipy import stats
    if is_constant(x, threshold):
        return None
    slope, intercept, r, p, se = stats.linregress(x, y)
    return {
        "slope":     float(slope),
        "intercept": float(intercept),
        "r":         float(r),
        "p":         float(p),
        "stderr":    float(se),
    }
