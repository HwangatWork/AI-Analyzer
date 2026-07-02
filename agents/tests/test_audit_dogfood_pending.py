# -*- coding: utf-8 -*-
"""
Phase 11-B 재정의 (사이클 3 Commit 3/3): _register_dogfood_audit_pending 회귀.

배경: Path Z Group E 대체 (11-A 패턴 재사용).
- pending 등록 + marker sentinel sweep + duplicate 방지 + I/O 안전
- Sentinel: data/processed/audit_dogfood_verified.marker (사용자 3-tier 완료 후 생성)

Tests:
T-ADF-1: marker 부재 → 신규 pending 등록
T-ADF-2: 이미 등록됨 → 중복 방지
T-ADF-3: marker 존재 + pending 있음 → sweep (completed 로 이동)
T-ADF-4: marker 존재 + pending 없음 → skipped
T-ADF-5: sweeper idempotent (반복 실행 안전)
T-ADF-6: pending 스키마 정합성 (id/request/status/details/registered_at + 3-tier 언급)
T-ADF-7: I/O 오류 non-blocking (파이프라인 차단 X)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "agents" / "run_audit_agent.py"
sys.path.insert(0, str(_REPO_ROOT / "agents"))


@pytest.fixture(scope="module")
def script_mod():
    spec = importlib.util.spec_from_file_location("run_audit_agent", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_ar(tmp_path: Path) -> Path:
    """audit_report.json 더미 생성 (경로 fixture 용)."""
    p = tmp_path / "data" / "processed" / "audit_report.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"audit_status":"PASS"}', encoding="utf-8")
    return p


def _make_marker(tmp_path: Path) -> Path:
    """sentinel marker 생성 (3-tier 완료 시뮬레이션)."""
    m = tmp_path / "data" / "processed" / "audit_dogfood_verified.marker"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text("verified: 2026-07-02", encoding="utf-8")
    return m


def test_T_ADF_1_new_registration(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    r = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    assert r == "registered"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    ids = [i["id"] for i in data["pending"]]
    assert "REQ-DOGFOOD-AUDIT" in ids


def test_T_ADF_2_duplicate_prevention(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    r1 = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    r2 = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    assert r1 == "registered"
    assert r2 == "already_registered"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    count = sum(1 for i in data["pending"] if i["id"] == "REQ-DOGFOOD-AUDIT")
    assert count == 1


def test_T_ADF_3_marker_sweeps_pending(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    script_mod._register_dogfood_audit_pending(tmp_path, ar)  # 등록
    _make_marker(tmp_path)  # 3-tier 완료
    r = script_mod._register_dogfood_audit_pending(tmp_path, ar)  # sweep
    assert r == "swept"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    pending_ids = [i["id"] for i in data["pending"]]
    completed_ids = [i["id"] for i in data["completed"]]
    assert "REQ-DOGFOOD-AUDIT" not in pending_ids
    assert "REQ-DOGFOOD-AUDIT" in completed_ids
    swept = next(i for i in data["completed"] if i["id"] == "REQ-DOGFOOD-AUDIT")
    assert "3-tier" in swept["completed_by"]


def test_T_ADF_4_marker_no_pending_skipped(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    _make_marker(tmp_path)
    r = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    assert r == "skipped"


def test_T_ADF_5_sweeper_idempotent(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    script_mod._register_dogfood_audit_pending(tmp_path, ar)
    _make_marker(tmp_path)
    r1 = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    r2 = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    assert r1 == "swept"
    assert r2 == "skipped"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    count = sum(1 for i in data["completed"] if i["id"] == "REQ-DOGFOOD-AUDIT")
    assert count == 1


def test_T_ADF_6_schema_and_3tier_mention(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    script_mod._register_dogfood_audit_pending(tmp_path, ar)
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    item = next(i for i in data["pending"] if i["id"] == "REQ-DOGFOOD-AUDIT")
    for f in ("id", "request", "status", "details", "registered_at"):
        assert f in item, f"필수 필드 누락: {f}"
    # 3-tier 명시적 언급 (self-cert 회피 강제)
    assert "audit-agent" in item["details"]
    assert "meta-audit-agent" in item["details"]
    assert "evaluator-agent" in item["details"]
    assert "self-cert" in item["details"]


def test_T_ADF_7_io_error_non_blocking(script_mod, tmp_path):
    ar = _make_ar(tmp_path)
    # pending_requests.json 을 디렉토리로 만들어 write 실패 유도
    fake = tmp_path / "pending_requests.json"
    fake.mkdir()
    r = script_mod._register_dogfood_audit_pending(tmp_path, ar)
    assert r == "error"  # exception 재raise 안 함
