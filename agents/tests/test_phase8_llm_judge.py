# -*- coding: utf-8 -*-
"""
Phase 8 회귀 테스트: LLM-as-Judge QN-1 / QR-1 (5개)

T-8-1: pm_quality_checks에 QN-1 항목 존재
T-8-2: pm_quality_checks에 QR-1 항목 존재
T-8-3: _llm_score_narrative — API 키 없으면 (0, 'SKIP') 반환
T-8-4: _llm_score_decision  — API 키 없으면 (0, 'SKIP') 반환
T-8-5: score < 3 → QN-1 pass=True + WARN prefix (advisory, 파이프라인 불차단)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from pm_quality import (
    pm_quality_checks,
    _llm_score_narrative,
    _llm_score_decision,
)


def test_T_8_1_qn1_exists():
    """T-8-1: QN-1 항목이 pm_quality_checks 결과에 존재."""
    checks = pm_quality_checks()
    names = [c["check"] for c in checks]
    assert any("QN-1" in n for n in names), f"T-8-1 FAIL: QN-1 없음 — {names}"


def test_T_8_2_qr1_exists():
    """T-8-2: QR-1 항목이 pm_quality_checks 결과에 존재."""
    checks = pm_quality_checks()
    names = [c["check"] for c in checks]
    assert any("QR-1" in n for n in names), f"T-8-2 FAIL: QR-1 없음 — {names}"


def test_T_8_3_narrative_no_api_key(monkeypatch):
    """T-8-3: ANTHROPIC_API_KEY 없으면 _llm_score_narrative → (0, 'SKIP')."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    score, reason = _llm_score_narrative("test narrative text")
    assert score == 0, f"T-8-3 FAIL: score={score} (expected 0)"
    assert reason == "SKIP", f"T-8-3 FAIL: reason={reason!r} (expected 'SKIP')"


def test_T_8_4_decision_no_api_key(monkeypatch):
    """T-8-4: ANTHROPIC_API_KEY 없으면 _llm_score_decision → (0, 'SKIP')."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    score, reason = _llm_score_decision({"sp500": {"action": "HOLD"}, "kospi": {"action": "HOLD"}})
    assert score == 0, f"T-8-4 FAIL: score={score} (expected 0)"
    assert reason == "SKIP", f"T-8-4 FAIL: reason={reason!r} (expected 'SKIP')"


def test_T_8_5_warn_on_low_score(monkeypatch, tmp_path):
    """T-8-5: score < 3 → QN-1 pass=True (advisory WARN, 파이프라인 불차단)."""
    import pm_quality as _pq

    # Mock narrative file
    narr_file = tmp_path / "narrative_context.json"
    narr_file.write_text('{"narrative": "테스트 리포트"}', encoding="utf-8")
    monkeypatch.setattr(_pq, "OUT_DIR", tmp_path)

    # Inject API key and mock LLM to return score=2
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-mock")
    monkeypatch.setattr(_pq, "_llm_score_narrative", lambda text: (2, "낮은 품질"))

    checks = _pq.pm_quality_checks()
    qn1 = next((c for c in checks if "QN-1" in c["check"]), None)
    assert qn1 is not None, "T-8-5 FAIL: QN-1 없음"
    assert qn1["pass"] is True, f"T-8-5 FAIL: pass={qn1['pass']} (WARN은 True여야 함)"
    assert "WARN" in qn1["detail"], f"T-8-5 FAIL: 'WARN' 없음 — {qn1['detail']}"
