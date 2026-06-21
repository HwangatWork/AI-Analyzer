# -*- coding: utf-8 -*-
"""
QI-1 신뢰도 로직 회귀 테스트 (mock 고정 데이터 기반)

실제 파이프라인 출력(decision.json)에 의존하지 않고
pm_quality_checks()의 QI-1 판단 로직이 정확한지 검증한다.

T-QI-1: BUY/SELL + 신뢰도 ≥20% → OK
T-QI-2: BUY/SELL + 신뢰도 <20% → WARN (모니터링, pass=True)
T-QI-3: HOLD → 신뢰도 무관하게 OK
T-QI-4: WARN 시에도 pass=True (회귀 기준선 제외 확인)
T-QI-5: check 이름에 [모니터링] 포함 확인
"""
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

BASE = Path(__file__).resolve().parent.parent.parent

SELL_LOW = {
    "sp500":  {"action": "SELL/AVOID", "confidence_pct": 18.8, "confidence_tier": "warn"},
    "kospi":  {"action": "HOLD",       "confidence_pct": 11.8, "confidence_tier": "hold"},
}
SELL_HIGH = {
    "sp500":  {"action": "SELL/AVOID", "confidence_pct": 22.5, "confidence_tier": "normal"},
    "kospi":  {"action": "HOLD",       "confidence_pct": 15.0, "confidence_tier": "hold"},
}
HOLD_BOTH = {
    "sp500":  {"action": "HOLD", "confidence_pct": 6.7,  "confidence_tier": "hold"},
    "kospi":  {"action": "HOLD", "confidence_pct": 6.6,  "confidence_tier": "hold"},
}
BUY_HIGH = {
    "sp500":  {"action": "BUY",  "confidence_pct": 35.0, "confidence_tier": "normal"},
    "kospi":  {"action": "BUY",  "confidence_pct": 30.0, "confidence_tier": "normal"},
}


def _run_qi1(decision_data: dict) -> dict:
    """pm_quality_checks()에서 QI-1 결과만 추출."""
    with tempfile.TemporaryDirectory() as tmp:
        dec_file = Path(tmp) / "decision.json"
        dec_file.write_text(json.dumps(decision_data), encoding="utf-8")

        # OUT_DIR을 tmp로 패치
        import pm_quality as pq
        orig_out = pq.OUT_DIR
        try:
            pq.OUT_DIR = Path(tmp)
            results = pq.pm_quality_checks()
        finally:
            pq.OUT_DIR = orig_out

    return next(r for r in results if "QI-1" in r["check"])


# ── T-QI-1 ────────────────────────────────────────────────────────────────

def test_T_QI_1_sell_high_confidence_ok():
    """T-QI-1: SELL/AVOID + 신뢰도 ≥20% → OK."""
    r = _run_qi1(SELL_HIGH)
    assert r["pass"] is True, f"T-QI-1 FAIL: {r}"
    assert "WARN" not in r["detail"], f"T-QI-1 FAIL: WARN 오탐 — {r['detail']}"
    assert "OK" in r["detail"], f"T-QI-1 FAIL: OK 미포함 — {r['detail']}"


# ── T-QI-2 ────────────────────────────────────────────────────────────────

def test_T_QI_2_sell_low_confidence_warn():
    """T-QI-2: SELL/AVOID + 신뢰도 <20% → WARN (모니터링 전용)."""
    r = _run_qi1(SELL_LOW)
    assert "WARN" in r["detail"], f"T-QI-2 FAIL: WARN 미출력 — {r['detail']}"
    assert "모니터링" in r["detail"], f"T-QI-2 FAIL: 모니터링 표기 없음 — {r['detail']}"
    assert "18.8" in r["detail"], f"T-QI-2 FAIL: 실제 신뢰도 값 미출력 — {r['detail']}"


# ── T-QI-3 ────────────────────────────────────────────────────────────────

def test_T_QI_3_hold_always_ok():
    """T-QI-3: HOLD → 신뢰도 무관하게 OK."""
    r = _run_qi1(HOLD_BOTH)
    assert r["pass"] is True, f"T-QI-3 FAIL: {r}"
    assert "WARN" not in r["detail"], f"T-QI-3 FAIL: HOLD인데 WARN — {r['detail']}"


# ── T-QI-4 ────────────────────────────────────────────────────────────────

def test_T_QI_4_warn_still_passes():
    """T-QI-4: 신뢰도 미달 WARN에도 pass=True (회귀 기준선 미포함)."""
    r = _run_qi1(SELL_LOW)
    assert r["pass"] is True, (
        f"T-QI-4 FAIL: WARN 상황인데 pass=False — 회귀 기준선 오염\n{r}"
    )


# ── T-QI-5 ────────────────────────────────────────────────────────────────

def test_T_QI_5_check_name_has_monitoring_tag():
    """T-QI-5: check 이름에 [모니터링] 포함 — 모니터링 전용임을 명시."""
    r = _run_qi1(HOLD_BOTH)
    assert "모니터링" in r["check"], (
        f"T-QI-5 FAIL: check 이름에 [모니터링] 없음 — '{r['check']}'"
    )
