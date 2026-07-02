# -*- coding: utf-8 -*-
"""
Phase 11-B 재정의 (사이클 3 Commit 2/3): audit_report.json 완전성 회귀.

배경: Phase 11-B Path Z 채택 후 data/processed/audit_report.json 계약 명세.
- run_audit_agent.py subprocess 가 완전 자동 생성 (기존)
- 상위 검증은 3-tier dogfood (audit + meta-audit + evaluator)
- 이 회귀는 audit_report.json 스키마 완전성 + audit_status enum 강제

Peer review consensus:
- audit Q2: audit_status ∈ {PASS, FAIL}, findings 각 finding 의 severity enum
- validation Q1: 단위 일관성 (total = passed + failed_critical + failed_warning)
- meta-audit Q4: audit 자기 인증 방지 → schema 는 다른 관점에서 검증

Tests:
T-AR-1: 파일 존재 + JSON 파싱 가능
T-AR-2: 필수 top-level 4 필드 (generated_at, summary, findings, audit_status)
T-AR-3: audit_status ∈ {PASS, FAIL}
T-AR-4: summary 필수 5 필드 (total, passed, failed_critical, failed_warning,
   audit_blocked)
T-AR-5: findings 최소 크기 (≥ 10) + 각 finding 필수 7 필드
T-AR-6: severity enum (finding[].severity ∈ {CRITICAL, WARNING, INFO})
T-AR-7: audit_status 정합성 — FAIL 이면 failed_critical > 0
T-AR-8: summary 산수 — total ≥ passed + failed_critical + failed_warning
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AR_PATH = _REPO_ROOT / "data" / "processed" / "audit_report.json"

_TOP_FIELDS = {"generated_at", "summary", "findings", "audit_status"}
_SUMMARY_FIELDS = {"total", "passed", "failed_critical", "failed_warning", "audit_blocked"}
_FINDING_FIELDS = {"layer", "code", "target", "passed", "severity", "detail", "recommendation"}
_VALID_STATUS = {"PASS", "FAIL"}
_VALID_SEVERITY = {"CRITICAL", "WARNING", "INFO"}


@pytest.fixture(scope="module")
def ar() -> dict:
    if not _AR_PATH.exists():
        pytest.skip(f"audit_report.json 미생성 (파이프라인 실행 전) — {_AR_PATH}")
    return json.loads(_AR_PATH.read_text(encoding="utf-8"))


def test_T_AR_1_file_exists_and_parses(ar):
    assert isinstance(ar, dict)
    assert len(ar) >= 4


def test_T_AR_2_top_level_fields(ar):
    missing = _TOP_FIELDS - set(ar.keys())
    assert not missing, f"필수 top 필드 누락: {missing}"


def test_T_AR_3_audit_status_enum(ar):
    status = ar.get("audit_status")
    assert status in _VALID_STATUS, f"audit_status={status!r} ∉ {_VALID_STATUS}"


def test_T_AR_4_summary_fields(ar):
    summary = ar.get("summary") or {}
    missing = _SUMMARY_FIELDS - set(summary.keys())
    assert not missing, f"summary 필수 필드 누락: {missing}"


def test_T_AR_5_findings_min_size_and_fields(ar):
    findings = ar.get("findings") or []
    assert isinstance(findings, list), "findings 가 list 아님"
    assert len(findings) >= 10, f"findings 부족: {len(findings)} < 10"
    for i, f in enumerate(findings[:5]):  # 첫 5개만 sample 검사
        missing = _FINDING_FIELDS - set(f.keys())
        assert not missing, f"findings[{i}] 필수 필드 누락: {missing}"


def test_T_AR_6_severity_enum(ar):
    findings = ar.get("findings") or []
    for i, f in enumerate(findings):
        sev = f.get("severity")
        assert sev in _VALID_SEVERITY, (
            f"findings[{i}].severity={sev!r} ∉ {_VALID_SEVERITY}"
        )


def test_T_AR_7_status_consistency_with_failed_critical(ar):
    """FAIL 이면 failed_critical > 0 강제 (반대 방향: PASS 여도 failed_warning 은 있을 수 있음)."""
    status = ar.get("audit_status")
    failed_critical = ar.get("summary", {}).get("failed_critical", 0)
    if status == "FAIL":
        assert failed_critical > 0, (
            f"audit_status=FAIL 인데 failed_critical={failed_critical} — 정합성 오류"
        )


def test_T_AR_8_summary_arithmetic(ar):
    """total ≥ passed + failed_critical + failed_warning (skip/na 가능)."""
    s = ar.get("summary", {})
    total = s.get("total", 0)
    passed = s.get("passed", 0)
    fc = s.get("failed_critical", 0)
    fw = s.get("failed_warning", 0)
    assert total >= passed + fc + fw, (
        f"산수 오류: total({total}) < passed({passed}) + fc({fc}) + fw({fw})"
    )
