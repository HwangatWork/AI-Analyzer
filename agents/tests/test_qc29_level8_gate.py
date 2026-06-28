# -*- coding: utf-8 -*-
"""
Phase 13-B-7-3 회귀: QC-29 Level 8 동적 게이트 (DC evidence 검증).

배경: FIX-G + 라운드 14 "DONE_CRITERIA: PASS 위장" 패턴 재발 방지.
룰: level_claimed >= 8 인데 evidence_files 빈/null → CRITICAL.

Tests:
T-QC29-1: baseline 부재 시 SKIP (advisory, 비차단)
T-QC29-2: Level 8+ PASS + evidence 보유 → PASS
T-QC29-3: Level 8+ PASS + evidence 빈 → CRITICAL (qc29_pass=False)
T-QC29-4: Level 7 이하 PASS + evidence 빈 → 게이트 대상 외 (PASS 유지)
T-QC29-5: PENDING status → 게이트 대상 외 (검증 스킵)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "agents"))


def _make_baseline(tmp_path: Path, dc_evidence: dict) -> Path:
    """Create temporary regression_baseline.json with given dc_evidence."""
    baseline = {
        "schema_version": "1.0",
        "baseline": {"pass_count": 108, "skip_count": 0, "fail_count": 0},
        "dc_evidence": dc_evidence,
        "level_gate_rules": {
            "min_level_for_gate": 8,
            "rule": "level_claimed >= 8 AND evidence_files empty → CRITICAL"
        }
    }
    p = tmp_path / "regression_baseline.json"
    p.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _run_qc29(monkeypatch, tmp_path, dc_evidence: dict | None) -> dict:
    """Run pm_quality_checks with mocked BASE_DIR. Return QC-29 result."""
    import pm_quality
    if dc_evidence is not None:
        _make_baseline(tmp_path, dc_evidence)
    monkeypatch.setattr(pm_quality, "BASE_DIR", tmp_path)
    results = pm_quality.pm_quality_checks()
    qc29 = next((r for r in results if r["check"].startswith("QC-29")), None)
    assert qc29 is not None, "QC-29 항목이 pm_quality_checks 결과에 없음"
    return qc29


def test_T_QC29_1_baseline_missing_skip(monkeypatch, tmp_path):
    """baseline 부재 → SKIP (pass=True, advisory)."""
    qc29 = _run_qc29(monkeypatch, tmp_path, dc_evidence=None)
    assert qc29["pass"] is True
    assert "SKIP" in qc29["detail"] or "미존재" in qc29["detail"]


def test_T_QC29_2_level8_with_evidence_passes(monkeypatch, tmp_path):
    """Level 8 PASS + evidence 보유 → PASS."""
    qc29 = _run_qc29(monkeypatch, tmp_path, dc_evidence={
        "DC-A": {
            "level_claimed": 8,
            "status": "PASS",
            "evidence_files": ["schemas/test.json"],
            "dynamic_test": "pytest test_x.py = 5 PASS"
        }
    })
    assert qc29["pass"] is True
    assert "OK" in qc29["detail"]


def test_T_QC29_3_level8_without_evidence_critical(monkeypatch, tmp_path):
    """Level 8 PASS + evidence 빈 → CRITICAL (qc29_pass=False)."""
    qc29 = _run_qc29(monkeypatch, tmp_path, dc_evidence={
        "DC-FAKE": {
            "level_claimed": 8,
            "status": "PASS",
            "evidence_files": [],
            "dynamic_test": None
        }
    })
    assert qc29["pass"] is False, f"Level 8 PASS without evidence should fail, got: {qc29}"
    assert "CRITICAL" in qc29["detail"]
    assert "DC-FAKE" in qc29["detail"]


def test_T_QC29_4_level7_without_evidence_not_gated(monkeypatch, tmp_path):
    """Level 7 이하는 게이트 대상 외 — evidence 빈이어도 PASS."""
    qc29 = _run_qc29(monkeypatch, tmp_path, dc_evidence={
        "DC-LOW": {
            "level_claimed": 7,
            "status": "PASS",
            "evidence_files": [],
            "dynamic_test": None
        }
    })
    assert qc29["pass"] is True, f"Level 7 should not trigger gate, got: {qc29}"


def test_T_QC29_5_pending_status_skipped(monkeypatch, tmp_path):
    """PENDING status는 게이트 대상 외 (PASS만 검증 대상)."""
    qc29 = _run_qc29(monkeypatch, tmp_path, dc_evidence={
        "DC-PEND": {
            "level_claimed": 10,
            "status": "PENDING",
            "evidence_files": [],
            "dynamic_test": None
        }
    })
    assert qc29["pass"] is True, f"PENDING should be skipped, got: {qc29}"
