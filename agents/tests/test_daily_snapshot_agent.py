# -*- coding: utf-8 -*-
"""
Phase 14-0-C 파이프라인 통합 회귀 (사용자 요청 2026-07-03).

meta-audit 9차 Q3/Q5 CRITICAL fix 검증:
- Q5 integration: run_daily_snapshot.py PIPELINE_STAGES 등록
- Q3 traceability: agent_activity.jsonl 에 snapshot_written 이벤트 append

Tests:
T-DS-1: 입력 파일 없음 → DS-1 FAIL
T-DS-2: decision.json 만 있어도 snapshot 생성 성공
T-DS-3: 3 소스 (decision + audit + narrative) 모두 있으면 3 rows
T-DS-4: agent_activity.jsonl 에 snapshot_written 이벤트 append (traceability)
T-DS-5: 미래 as_of → SnapshotIntegrityError → FAIL 반환 (PIT invariant)
T-DS-6: PIPELINE_STAGES 에 run_daily_snapshot.py 등록 확인
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "agents"))


@pytest.fixture(scope="module")
def script_mod():
    spec = importlib.util.spec_from_file_location(
        "run_daily_snapshot",
        _REPO_ROOT / "agents" / "run_daily_snapshot.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup_dirs(tmp_path: Path):
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)


def _write_decision(tmp_path: Path, as_of: str = "2026-07-02T09:00:00+00:00"):
    (tmp_path / "output" / "decision.json").write_text(
        json.dumps({
            "computed_at": as_of,
            "composite_score": 30.1,
            "sp500": {"action": "HOLD"},
            "kospi": {"action": "HOLD"},
        }, ensure_ascii=False), encoding="utf-8"
    )


def _write_audit(tmp_path: Path, as_of: str = "2026-07-02T10:00:00+00:00"):
    (tmp_path / "data" / "processed" / "audit_report.json").write_text(
        json.dumps({
            "generated_at": as_of,
            "audit_status": "PASS",
            "summary": {"total": 65, "passed": 65, "failed_critical": 0,
                        "failed_warning": 0},
        }, ensure_ascii=False), encoding="utf-8"
    )


def _write_narrative(tmp_path: Path, as_of: str = "2026-07-02T11:00:00+00:00"):
    (tmp_path / "output" / "narrative_context.json").write_text(
        json.dumps({
            "generated_at": as_of,
            "signal": "HOLD",
            "confidence_pct": 12.8,
            "total_signals": 13,
        }, ensure_ascii=False), encoding="utf-8"
    )


def test_T_DS_1_no_input_fails(script_mod, tmp_path, monkeypatch):
    _setup_dirs(tmp_path)
    monkeypatch.setattr(script_mod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(script_mod, "PROCESSED_DIR", tmp_path / "data" / "processed")
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    result = script_mod.run_daily_snapshot(
        now=now, base_dir=tmp_path,
        log_path=tmp_path / "data" / "agent_activity.jsonl",
    )
    assert result["status"] == "FAIL"
    assert any("DS-1" in f for f in result["fails"])


def test_T_DS_2_decision_only_succeeds(script_mod, tmp_path, monkeypatch):
    _setup_dirs(tmp_path)
    _write_decision(tmp_path)
    monkeypatch.setattr(script_mod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(script_mod, "PROCESSED_DIR", tmp_path / "data" / "processed")
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    result = script_mod.run_daily_snapshot(
        now=now, base_dir=tmp_path,
        log_path=tmp_path / "data" / "agent_activity.jsonl",
    )
    assert result["status"] == "PASS"
    assert result["rows_count"] == 1
    assert Path(result["snapshot_path"]).exists()


def test_T_DS_3_three_sources_three_rows(script_mod, tmp_path, monkeypatch):
    _setup_dirs(tmp_path)
    _write_decision(tmp_path)
    _write_audit(tmp_path)
    _write_narrative(tmp_path)
    monkeypatch.setattr(script_mod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(script_mod, "PROCESSED_DIR", tmp_path / "data" / "processed")
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    result = script_mod.run_daily_snapshot(
        now=now, base_dir=tmp_path,
        log_path=tmp_path / "data" / "agent_activity.jsonl",
    )
    assert result["status"] == "PASS"
    assert result["rows_count"] == 3


def test_T_DS_4_activity_log_appended(script_mod, tmp_path, monkeypatch):
    """meta-audit Q3 fix: snapshot 후 agent_activity.jsonl 에 이벤트 append."""
    _setup_dirs(tmp_path)
    _write_decision(tmp_path)
    monkeypatch.setattr(script_mod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(script_mod, "PROCESSED_DIR", tmp_path / "data" / "processed")
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    log_path = tmp_path / "data" / "agent_activity.jsonl"
    result = script_mod.run_daily_snapshot(now=now, base_dir=tmp_path, log_path=log_path)
    assert result["logged"] is True
    assert log_path.exists()
    entries = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    snap_events = [e for e in entries if e.get("event") == "snapshot_written"]
    assert len(snap_events) == 1
    assert snap_events[0]["agent_type"] == "daily-snapshot"
    assert "sha256" in snap_events[0]
    assert "path" in snap_events[0]


def test_T_DS_5_future_as_of_pit_fail(script_mod, tmp_path, monkeypatch):
    """PIT invariant (Ljungqvist 2009): 미래 as_of → DS-2 FAIL."""
    _setup_dirs(tmp_path)
    _write_decision(tmp_path, as_of="2026-07-10T00:00:00+00:00")  # 미래
    monkeypatch.setattr(script_mod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(script_mod, "PROCESSED_DIR", tmp_path / "data" / "processed")
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    result = script_mod.run_daily_snapshot(
        now=now, base_dir=tmp_path,
        log_path=tmp_path / "data" / "agent_activity.jsonl",
    )
    assert result["status"] == "FAIL"
    assert any("DS-2" in f for f in result["fails"])


def test_T_DS_6_pipeline_stage_registered():
    """PIPELINE_STAGES 에 run_daily_snapshot.py 등록 확인."""
    orch = _REPO_ROOT / "agents" / "pm_orchestrator.py"
    text = orch.read_text(encoding="utf-8")
    assert "run_daily_snapshot.py" in text, (
        "run_daily_snapshot.py 가 pm_orchestrator.PIPELINE_STAGES 에 등록 안 됨"
    )
