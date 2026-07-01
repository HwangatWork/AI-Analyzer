# -*- coding: utf-8 -*-
"""
Phase 11-A 재정의 (사이클 2 Commit 3/3): _register_dogfood_pending 회귀.

배경: Path Z Group E 대체 — pm_orchestrator 자동 spawn 대신 pending 자동 등록.
FINAL_REPORT_v2.md 존재/부재 상태에 따라 4 branch 검증.

Tests:
T-NDF-1: FINAL_REPORT_v2.md 존재 시 skip (이미 완료)
T-NDF-2: FINAL_REPORT_v2.md 부재 시 신규 등록
T-NDF-3: 이미 등록된 경우 중복 방지
T-NDF-4: pending_requests.json 스키마 정합성 (id/request/status/details 존재)
T-NDF-5: I/O 오류 시 파이프라인 차단 X (error 반환, exception 재raise 안 함)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "agents" / "run_narrative_agent.py"

# utf8_setup import 우회 위해 script path 별도 로드
sys.path.insert(0, str(_REPO_ROOT / "agents"))


@pytest.fixture(scope="module")
def script_mod():
    spec = importlib.util.spec_from_file_location("run_narrative_agent", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_ctx(tmp_path: Path) -> Path:
    """narrative_context.json 더미 생성 (필수 최소)."""
    p = tmp_path / "output" / "narrative_context.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"generated_at":"2026-07-02T00:00:00"}', encoding="utf-8")
    return p


def test_T_NDF_1_skip_when_report_exists(script_mod, tmp_path):
    """FINAL_REPORT_v2.md 존재 시 pending 등록 스킵."""
    ctx = _make_ctx(tmp_path)
    fr = tmp_path / "output" / "FINAL_REPORT_v2.md"
    fr.write_text("# 리포트\n\n실 프로세 500자 이상 " * 20, encoding="utf-8")
    result = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert result == "skipped"
    # pending 파일 미생성 검증
    assert not (tmp_path / "pending_requests.json").exists()


def test_T_NDF_2_new_registration_when_report_missing(script_mod, tmp_path):
    """FINAL_REPORT_v2.md 부재 + 신규 등록."""
    ctx = _make_ctx(tmp_path)
    result = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert result == "registered"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["pending"]]
    assert "REQ-DOGFOOD-NARRATIVE" in ids


def test_T_NDF_3_duplicate_prevention(script_mod, tmp_path):
    """이미 등록된 항목 있으면 중복 등록 안 함."""
    ctx = _make_ctx(tmp_path)
    r1 = script_mod._register_dogfood_pending(tmp_path, ctx)
    r2 = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert r1 == "registered"
    assert r2 == "already_registered"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    count = sum(1 for i in data["pending"] if i["id"] == "REQ-DOGFOOD-NARRATIVE")
    assert count == 1, f"중복 등록됨: {count} 건"


def test_T_NDF_4_schema_fields(script_mod, tmp_path):
    """등록 항목이 pending_requests.json 표준 스키마 준수."""
    ctx = _make_ctx(tmp_path)
    script_mod._register_dogfood_pending(tmp_path, ctx)
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    item = next(i for i in data["pending"] if i["id"] == "REQ-DOGFOOD-NARRATIVE")
    for field in ("id", "request", "status", "details", "registered_at"):
        assert field in item, f"필수 필드 누락: {field}"
    assert item["status"] == "pending"
    assert "narrative-agent" in item["request"]


def test_T_NDF_5_io_error_non_blocking(script_mod, tmp_path, monkeypatch):
    """I/O 오류 시에도 exception 재raise 안 함 (advisory only)."""
    ctx = _make_ctx(tmp_path)
    # pending_requests.json 을 디렉토리로 만들어 write 실패 유도
    fake_pending = tmp_path / "pending_requests.json"
    fake_pending.mkdir()  # 디렉토리로 만들어 write 실패
    result = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert result == "error"  # exception 없이 error 반환


def test_T_NDF_6_sweeper_moves_pending_to_completed(script_mod, tmp_path):
    """meta-audit 7차 Q5 fix: FINAL_REPORT 감지 시 기존 pending → completed sweep."""
    ctx = _make_ctx(tmp_path)
    # 1단계: 등록 (FINAL_REPORT 부재)
    r1 = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert r1 == "registered"

    # 2단계: FINAL_REPORT 생성 (dogfood 완료 시뮬레이션)
    fr = tmp_path / "output" / "FINAL_REPORT_v2.md"
    fr.write_text("# 완료된 리포트\n" + "실제 프로즈 " * 30, encoding="utf-8")

    # 3단계: sweeper 실행
    r2 = script_mod._register_dogfood_pending(tmp_path, ctx)
    assert r2 == "swept"

    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    # pending 에서 제거됨
    pending_ids = [i["id"] for i in data["pending"]]
    assert "REQ-DOGFOOD-NARRATIVE" not in pending_ids
    # completed 로 이동
    completed_ids = [i["id"] for i in data["completed"]]
    assert "REQ-DOGFOOD-NARRATIVE" in completed_ids
    # completed 항목에 completed_at + completed_by 필드 추가됨
    swept_item = next(i for i in data["completed"] if i["id"] == "REQ-DOGFOOD-NARRATIVE")
    assert "completed_at" in swept_item
    assert "dogfood_auto_detect" in swept_item["completed_by"]


def test_T_NDF_7_sweeper_idempotent(script_mod, tmp_path):
    """sweeper 반복 실행 시 이미 completed 상태이면 skip."""
    ctx = _make_ctx(tmp_path)
    script_mod._register_dogfood_pending(tmp_path, ctx)
    fr = tmp_path / "output" / "FINAL_REPORT_v2.md"
    fr.write_text("# 리포트\n" + "실 프로즈 " * 30, encoding="utf-8")
    r1 = script_mod._register_dogfood_pending(tmp_path, ctx)  # swept
    r2 = script_mod._register_dogfood_pending(tmp_path, ctx)  # skipped (더 이상 pending 없음)
    assert r1 == "swept"
    assert r2 == "skipped"
    data = json.loads((tmp_path / "pending_requests.json").read_text(encoding="utf-8"))
    # completed 는 정확히 1건만 (중복 push 안 함)
    count = sum(1 for i in data["completed"] if i["id"] == "REQ-DOGFOOD-NARRATIVE")
    assert count == 1
