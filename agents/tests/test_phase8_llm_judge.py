# -*- coding: utf-8 -*-
"""
Phase 8 회귀 테스트: LLM-as-Judge QN-1 / QR-1 (7개)

T-8-1: pm_quality_checks에 QN-1 항목 존재
T-8-2: pm_quality_checks에 QR-1 항목 존재
T-8-3: _llm_score_narrative — API 키 없으면 (0, 'SKIP') 반환
T-8-4: _llm_score_decision  — API 키 없으면 (0, 'SKIP') 반환
T-8-5: score < 3 → QN-1 pass=True + WARN prefix (advisory, 파이프라인 불차단)
T-8-6: QN-1 reader가 실제 FINAL_REPORT_v2.md prose를 LLM에 전달 (FIX-G 계약 검증)
T-8-7: QR-1 reader가 실제 position_note/composite_score를 prompt에 포함 (FIX-G 계약 검증)
"""
import json
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_NARR = _REPO_ROOT / "output" / "narrative_context.json"
_REAL_REPORT = _REPO_ROOT / "output" / "FINAL_REPORT_v2.md"
_REAL_DEC = _REPO_ROOT / "output" / "decision.json"


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
    """T-8-5: score < 3 → QN-1 pass=True (advisory WARN, 파이프라인 불차단).

    FIX-G: 합성 fixture가 아니라 실제 출력 파일을 복사해 사용 — 계약 drift 재발 방지.
    """
    import pm_quality as _pq

    if not _REAL_NARR.exists() or not _REAL_REPORT.exists():
        pytest.skip("실제 output/ 파일 없음 — 파이프라인 실행 후 재시도")

    # Copy real outputs into tmp so OUT_DIR mock works
    (tmp_path / "narrative_context.json").write_bytes(_REAL_NARR.read_bytes())
    (tmp_path / "FINAL_REPORT_v2.md").write_bytes(_REAL_REPORT.read_bytes())
    monkeypatch.setattr(_pq, "OUT_DIR", tmp_path)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-mock")
    monkeypatch.setattr(_pq, "_llm_score_narrative", lambda text: (2, "낮은 품질"))

    checks = _pq.pm_quality_checks()
    qn1 = next((c for c in checks if "QN-1" in c["check"]), None)
    assert qn1 is not None, "T-8-5 FAIL: QN-1 없음"
    assert qn1["pass"] is True, f"T-8-5 FAIL: pass={qn1['pass']} (WARN은 True여야 함)"
    assert "WARN" in qn1["detail"], f"T-8-5 FAIL: 'WARN' 없음 — {qn1['detail']}"


def test_T_8_6_qn1_passes_real_prose_to_llm(monkeypatch, tmp_path):
    """T-8-6 (FIX-G): QN-1 reader가 실제 FINAL_REPORT_v2.md prose를 LLM에 전달.

    narrative_context.json은 data-prep only이므로 narrative/report 키가 없음 —
    reader는 FINAL_REPORT_v2.md로 폴백해야 한다. 합성 fixture로는 검증 불가능.
    """
    import pm_quality as _pq

    if not _REAL_NARR.exists() or not _REAL_REPORT.exists():
        pytest.skip("실제 output/ 파일 없음 — 파이프라인 실행 후 재시도")

    (tmp_path / "narrative_context.json").write_bytes(_REAL_NARR.read_bytes())
    (tmp_path / "FINAL_REPORT_v2.md").write_bytes(_REAL_REPORT.read_bytes())
    monkeypatch.setattr(_pq, "OUT_DIR", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-mock")

    captured = {}

    def _spy(text):
        captured["text"] = text
        return (4, "OK")

    monkeypatch.setattr(_pq, "_llm_score_narrative", _spy)

    _pq.pm_quality_checks()
    txt = captured.get("text", "")
    assert len(txt) >= 500, (
        f"T-8-6 FAIL: reader가 LLM에 전달한 prose가 너무 짧음 ({len(txt)}자) — "
        f"FINAL_REPORT_v2.md 폴백 실패 의심"
    )
    # 실제 리포트는 Markdown 헤더 + 한국어 표제를 포함해야 함
    assert "#" in txt and ("리포트" in txt or "분석" in txt), (
        f"T-8-6 FAIL: prose에 Markdown/한국어 마커 없음 — stringified dict 폴백 의심: {txt[:120]!r}"
    )


def test_T_8_7_qr1_prompt_includes_real_fields(monkeypatch):
    """T-8-7 (FIX-G): QR-1 prompt가 실제 position_note/composite_score를 포함.

    `reason`/`signal_score`는 decision.json에 존재하지 않음 — 빈 prompt가 LLM에 가면 안 됨.
    """
    import pm_quality as _pq

    if not _REAL_DEC.exists():
        pytest.skip("output/decision.json 없음 — 파이프라인 실행 후 재시도")

    decision = json.loads(_REAL_DEC.read_text(encoding="utf-8"))
    if not decision.get("sp500", {}).get("position_note") or "composite_score" not in decision:
        pytest.skip("decision.json 스키마 변경됨 — 계약 검증 보류")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-mock")

    captured = {}

    class _FakeMsg:
        def create(self, **kw):
            captured["prompt"] = kw["messages"][0]["content"]

            class _R:
                content = [type("X", (), {"text": "SCORE: 4\nREASON: ok"})()]
            return _R()

    class _FakeClient:
        messages = _FakeMsg()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: _FakeClient())

    _pq._llm_score_decision(decision)
    prompt = captured.get("prompt", "")

    expected_note = decision["sp500"]["position_note"]
    expected_score = str(decision["composite_score"])

    assert expected_note[:30] in prompt, (
        f"T-8-7 FAIL: prompt에 sp500.position_note 누락 — reason 키 사용 의심: {prompt[:200]!r}"
    )
    assert expected_score in prompt, (
        f"T-8-7 FAIL: prompt에 composite_score 누락 — signal_score 키 사용 의심: {prompt[:200]!r}"
    )
    assert "시그널 점수: ?" not in prompt, (
        f"T-8-7 FAIL: 시그널 점수가 '?'로 폴백됨 — composite_score 미사용: {prompt[:200]!r}"
    )
