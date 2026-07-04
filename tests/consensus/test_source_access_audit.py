# -*- coding: utf-8 -*-
"""Mock-only tests for Phase 0-A1 Source Access Audit.

NO test in this file may make an external network call. The audit tool's
network guard hard-fails on socket access. Tests rely entirely on local
filesystem and parsed JSON.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus import source_access_audit as saa  # noqa: E402


def _good_sources_cfg() -> dict:
    return {
        "schema_version": "0.1",
        "target": {"ticker": "000660", "company": "SK hynix"},
        "sources": [
            {
                "source_provider": f"P{i}",
                "source_type": "official_api",
                "homepage_url": f"https://p{i}.example",
                "robots_url": f"https://p{i}.example/robots.txt",
                "terms_url": f"https://p{i}.example/terms",
                "requires_login": False,
                "requires_api_key": (i % 2 == 0),
                "expected_data_roles": ["consensus_target_price"],
                "live_audit_allowed": False,
                "financial_data_fetch_allowed": False,
                "notes": f"synthetic source {i}",
            }
            for i in range(7)
        ],
    }


def _good_policy_cfg() -> dict:
    return {
        "schema_version": "0.1",
        "categories": {
            cat: {"ko": [f"{cat}-ko"], "en": [f"{cat}-en"]}
            for cat in saa.REQUIRED_POLICY_CATEGORIES
        },
    }


def _write(tmp_path: Path, name: str, obj: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _run(tmp_path: Path, sources: dict, policy: dict, extra_argv=()) -> tuple[int, Path]:
    cfg_path = _write(tmp_path, "sources.json", sources)
    pol_path = _write(tmp_path, "policy.json", policy)
    out_path = tmp_path / "out" / "audit.json"
    code = saa.main(
        [
            "--config",
            str(cfg_path),
            "--policy",
            str(pol_path),
            "--out",
            str(out_path),
            *extra_argv,
        ]
    )
    return code, out_path


# -------------------------- required tests --------------------------


def test_dry_run_makes_zero_network_calls(tmp_path):
    code, out_path = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
    assert code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["network_calls_made"] == 0
    assert data["mode"] == "dry_run_static_audit"


def test_valid_config_generates_summary_json(tmp_path):
    code, out_path = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
    assert code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["total_sources"] == 7
    assert isinstance(data["summary"]["ready_for_smoke_test"], list)


def test_missing_required_source_field_fails(tmp_path):
    cfg = _good_sources_cfg()
    del cfg["sources"][0]["robots_url"]
    code, _ = _run(tmp_path, cfg, _good_policy_cfg())
    assert code == saa.EXIT_INVALID_SOURCES


def test_duplicate_source_provider_fails(tmp_path):
    cfg = _good_sources_cfg()
    cfg["sources"][1]["source_provider"] = cfg["sources"][0]["source_provider"]
    code, _ = _run(tmp_path, cfg, _good_policy_cfg())
    assert code == saa.EXIT_INVALID_SOURCES


def test_invalid_policy_keywords_fails(tmp_path):
    pol = _good_policy_cfg()
    del pol["categories"]["automation"]
    code, _ = _run(tmp_path, _good_sources_cfg(), pol)
    assert code == saa.EXIT_INVALID_POLICY


def test_financial_data_fetch_allowed_true_blocks(tmp_path):
    cfg = _good_sources_cfg()
    cfg["sources"][2]["financial_data_fetch_allowed"] = True
    code, _ = _run(tmp_path, cfg, _good_policy_cfg())
    assert code == saa.EXIT_INVALID_SOURCES


def test_live_flag_rejected_with_exit_code_4(tmp_path):
    code, _ = _run(
        tmp_path, _good_sources_cfg(), _good_policy_cfg(), extra_argv=("--live",)
    )
    assert code == saa.EXIT_UNSAFE_FLAG


def test_fetch_data_flag_rejected_with_exit_code_4(tmp_path):
    code, _ = _run(
        tmp_path,
        _good_sources_cfg(),
        _good_policy_cfg(),
        extra_argv=("--fetch-data",),
    )
    assert code == saa.EXIT_UNSAFE_FLAG


def test_output_schema_has_required_top_level_fields(tmp_path):
    code, out_path = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
    assert code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    for field in saa.REQUIRED_OUTPUT_TOP_LEVEL:
        assert field in data, f"missing top-level field: {field}"


def test_output_source_entries_have_required_fields(tmp_path):
    code, out_path = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
    assert code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["sources"], "expected non-empty sources list"
    for idx, entry in enumerate(data["sources"]):
        for f in saa.REQUIRED_OUTPUT_SOURCE_FIELDS:
            assert f in entry, f"sources[{idx}] missing field {f}"


def test_output_write_failure_returns_exit_code_2(tmp_path, monkeypatch):
    cfg_path = _write(tmp_path, "sources.json", _good_sources_cfg())
    pol_path = _write(tmp_path, "policy.json", _good_policy_cfg())
    out_path = tmp_path / "out" / "audit.json"

    real_open = open

    def _refusing_open(path, mode="r", *a, **kw):
        if "w" in mode and str(path).endswith("audit.json"):
            raise OSError("simulated write failure")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", _refusing_open)
    code = saa.main(
        ["--config", str(cfg_path), "--policy", str(pol_path), "--out", str(out_path)]
    )
    assert code == saa.EXIT_WRITE_FAILED


def test_success_stdout_is_cp949_safe(tmp_path, capsys):
    """Regression guard for the CP949 stdout encoding bug.

    Windows default console (CP949) cannot encode characters such as the
    em dash U+2014. The CLI success line must therefore be limited to
    characters that survive cp949 encoding. This test asserts both: (a)
    explicit absence of U+2014, and (b) that the success line round-trips
    through cp949.
    """
    code, _ = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
    assert code == 0
    captured = capsys.readouterr().out
    success_lines = [ln for ln in captured.splitlines() if "DONE_CRITERIA" in ln]
    assert success_lines, "expected DONE_CRITERIA line in stdout"
    success_line = success_lines[0]
    assert "—" not in success_line, "U+2014 em dash must not appear in success line"
    # Must round-trip through cp949 (Windows default console codepage).
    success_line.encode("cp949")


def test_network_block_does_not_break_dry_run(tmp_path):
    """A successful dry-run must not invoke socket.socket or create_connection.

    We verify by replacing the socket primitives with raising stubs BEFORE
    invoking main and confirming the audit still exits 0. main() also
    installs its own guard; this test confirms it does not violate any
    pre-existing guard either.
    """
    import socket

    original_socket = socket.socket
    original_create = socket.create_connection

    def _fail(*_a, **_kw):
        raise AssertionError("dry-run must not touch the network")

    socket.socket = _fail  # type: ignore[assignment]
    socket.create_connection = _fail  # type: ignore[assignment]
    try:
        code, out_path = _run(tmp_path, _good_sources_cfg(), _good_policy_cfg())
        assert code == 0
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["network_calls_made"] == 0
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create  # type: ignore[assignment]
