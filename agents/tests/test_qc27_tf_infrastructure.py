# -*- coding: utf-8 -*-
"""
Phase 13-B-5 회귀: QC-27 TF Framework 인프라 파일 존재 검증 (DC-11).

배경: TF 핵심 파일 5개 + regression_baseline.json 부재 시 hook lifecycle /
dogfood 자동 실패 → 사전 게이트.

Tests:
T-QC27-1: 모든 TF 파일 존재 + 비-empty → PASS
T-QC27-2: 1 파일 missing → CRITICAL
T-QC27-3: 1 파일 empty (size=0) → CRITICAL
T-QC27-4: 다중 missing + empty 동시 → CRITICAL + 양쪽 모두 보고
T-QC27-5: QC-27 항목이 pm_quality_checks 결과에 포함
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "agents"))


_TF_FILES = [
    "schemas/peer_review_response.schema.json",
    "schemas/peer_review_concerns.schema.json",
    ".claude/hooks/tf_schema_check.py",
    ".claude/hooks/tf_aggregate.py",
    ".claude/commands/tf-review.md",
    "regression_baseline.json",
]


def _make_tf_infra(tmp_path: Path, missing: list[str] = None, empty: list[str] = None) -> None:
    """tmp_path에 TF 파일 6개 생성. missing/empty 명시 시 그 파일은 생략/0바이트."""
    missing = missing or []
    empty = empty or []
    for rel in _TF_FILES:
        if rel in missing:
            continue
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel in empty:
            p.touch()
        else:
            p.write_text("// non-empty stub\n", encoding="utf-8")


def _run_qc27(monkeypatch, tmp_path) -> dict:
    """pm_quality_checks를 mocked BASE_DIR로 실행, QC-27 결과 반환."""
    import pm_quality
    monkeypatch.setattr(pm_quality, "BASE_DIR", tmp_path)
    results = pm_quality.pm_quality_checks()
    qc27 = next((r for r in results if r["check"].startswith("QC-27")), None)
    assert qc27 is not None, "QC-27 항목이 pm_quality_checks 결과에 없음"
    return qc27


def test_T_QC27_1_all_files_present_passes(monkeypatch, tmp_path):
    """모든 TF 파일 존재 + 비-empty → PASS."""
    _make_tf_infra(tmp_path)
    qc27 = _run_qc27(monkeypatch, tmp_path)
    assert qc27["pass"] is True, f"All files present should pass, got: {qc27}"
    assert "OK" in qc27["detail"]
    assert "6/6" in qc27["detail"]


def test_T_QC27_2_single_missing_critical(monkeypatch, tmp_path):
    """1 파일 missing → CRITICAL."""
    _make_tf_infra(tmp_path, missing=["schemas/peer_review_response.schema.json"])
    qc27 = _run_qc27(monkeypatch, tmp_path)
    assert qc27["pass"] is False
    assert "CRITICAL" in qc27["detail"]
    assert "missing" in qc27["detail"]
    assert "peer_review_response.schema.json" in qc27["detail"]


def test_T_QC27_3_single_empty_critical(monkeypatch, tmp_path):
    """1 파일 size=0 → CRITICAL."""
    _make_tf_infra(tmp_path, empty=[".claude/hooks/tf_aggregate.py"])
    qc27 = _run_qc27(monkeypatch, tmp_path)
    assert qc27["pass"] is False
    assert "CRITICAL" in qc27["detail"]
    assert "empty" in qc27["detail"]
    assert "tf_aggregate.py" in qc27["detail"]


def test_T_QC27_4_multi_missing_and_empty(monkeypatch, tmp_path):
    """다중 missing + empty → CRITICAL + 양쪽 보고."""
    _make_tf_infra(
        tmp_path,
        missing=["regression_baseline.json"],
        empty=[".claude/commands/tf-review.md"]
    )
    qc27 = _run_qc27(monkeypatch, tmp_path)
    assert qc27["pass"] is False
    assert "missing" in qc27["detail"]
    assert "empty" in qc27["detail"]
    assert "regression_baseline.json" in qc27["detail"]
    assert "tf-review.md" in qc27["detail"]


def test_T_QC27_5_appears_in_pm_quality_checks(monkeypatch, tmp_path):
    """QC-27 항목이 pm_quality_checks 결과에 반드시 포함됨."""
    _make_tf_infra(tmp_path)
    import pm_quality
    monkeypatch.setattr(pm_quality, "BASE_DIR", tmp_path)
    results = pm_quality.pm_quality_checks()
    qc27_checks = [r for r in results if r["check"].startswith("QC-27")]
    assert len(qc27_checks) == 1, (
        f"QC-27 must appear exactly once in pm_quality_checks, got: {len(qc27_checks)}"
    )
    assert "TF Framework" in qc27_checks[0]["check"]
