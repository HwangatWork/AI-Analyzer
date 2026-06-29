# -*- coding: utf-8 -*-
"""
Phase 13-D-1 회귀: scripts/agent_log.py session jsonl 파서.

Tests:
T-AL-1: _encode_project_path 가 윈도우 경로를 Claude 컨벤션으로 인코딩
T-AL-2: parse_session 이 Agent() 호출만 추출 (다른 tool_use 무시)
T-AL-3: parse_session --since 필터 적용
T-AL-4: parse_activity_log 가 hook jsonl 로드
T-AL-5: render_table 포맷 (no/ts/agent/desc)
T-AL-6: render_counts (Counter most_common)
T-AL-7: main() --activity 모드 통합 (tmp_path 사용)
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "agent_log.py"


@pytest.fixture(scope="module")
def script_mod():
    spec = importlib.util.spec_from_file_location("agent_log", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_AL_1_encode_project_path(script_mod, tmp_path):
    encoded = script_mod._encode_project_path(Path("C:/Users/JY Hwang/Desktop/AI Analyzer"))
    # `:` + `/` 각각 `-` → `C:/` = `C--` (Claude Code 컨벤션, double dash 유지)
    assert "C--Users" in encoded, f"expected double-dash 'C--Users', got: {encoded}"
    assert "JY-Hwang" in encoded
    assert ":" not in encoded
    assert " " not in encoded


def test_T_AL_2_parse_session_filters_agent_tool(script_mod, tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(
        json.dumps({
            "timestamp": "2026-06-30T10:00:00Z",
            "message": {"content": [
                {"type": "tool_use", "name": "Agent",
                 "input": {"subagent_type": "audit-agent", "description": "check X"}},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            ]},
        }) + "\n"
        + json.dumps({
            "timestamp": "2026-06-30T10:01:00Z",
            "message": {"content": [
                {"type": "tool_use", "name": "Agent",
                 "input": {"subagent_type": "pm-agent", "description": "plan"}},
            ]},
        }) + "\n",
        encoding="utf-8",
    )
    invs = script_mod.parse_session(jsonl)
    assert len(invs) == 2
    assert invs[0]["subagent_type"] == "audit-agent"
    assert invs[1]["subagent_type"] == "pm-agent"


def test_T_AL_3_parse_session_since_filter(script_mod, tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(
        json.dumps({
            "timestamp": "2026-06-29T10:00:00Z",
            "message": {"content": [
                {"type": "tool_use", "name": "Agent",
                 "input": {"subagent_type": "old-agent"}},
            ]},
        }) + "\n"
        + json.dumps({
            "timestamp": "2026-06-30T10:00:00Z",
            "message": {"content": [
                {"type": "tool_use", "name": "Agent",
                 "input": {"subagent_type": "new-agent"}},
            ]},
        }) + "\n",
        encoding="utf-8",
    )
    since = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)
    invs = script_mod.parse_session(jsonl, since=since)
    assert len(invs) == 1
    assert invs[0]["subagent_type"] == "new-agent"


def test_T_AL_4_parse_activity_log(script_mod, tmp_path):
    act = tmp_path / "agent_activity.jsonl"
    act.write_text(
        json.dumps({"ts": "2026-06-30T10:00:00+00:00", "agent_type": "audit-agent",
                    "tools_count": 5, "runtime_sec": 12.3}) + "\n"
        + json.dumps({"ts": "2026-06-30T10:05:00+00:00", "agent_type": "pm-agent",
                      "tools_count": 8, "runtime_sec": 30.0}) + "\n",
        encoding="utf-8",
    )
    entries = script_mod.parse_activity_log(act)
    assert len(entries) == 2
    assert entries[0]["agent_type"] == "audit-agent"


def test_T_AL_5_render_table_format(script_mod):
    invs = [{"ts": "2026-06-30T10:00:00", "subagent_type": "audit-agent",
             "description": "check"}]
    out = script_mod.render_table(invs)
    assert "audit-agent" in out
    assert "check" in out
    assert "2026-06-30" in out


def test_T_AL_6_render_counts(script_mod):
    invs = [
        {"subagent_type": "audit-agent"},
        {"subagent_type": "audit-agent"},
        {"subagent_type": "pm-agent"},
    ]
    out = script_mod.render_counts(invs)
    assert "audit-agent" in out
    assert "2회" in out
    assert "pm-agent" in out
    assert "1회" in out


def test_T_AL_8_force_utf8_stdio(script_mod):
    """Audit 5차 CRITICAL-C1: Windows cp949 환경에서 em-dash/한글 print 크래시 방지."""
    # 함수 존재 + 호출 시 raise 없음
    assert hasattr(script_mod, "_force_utf8_stdio")
    script_mod._force_utf8_stdio()  # idempotent + no-raise


def test_T_AL_9_render_table_em_dash_safe(script_mod):
    """em-dash 가 description 에 있어도 render_table 정상 동작."""
    invs = [{
        "ts": "2026-06-30T10:00:00",
        "subagent_type": "audit-agent",
        "description": "Audit 4차 — 옵션 C 3 commits cross-check",  # em-dash 포함
    }]
    out = script_mod.render_table(invs)
    assert "—" in out  # em-dash 보존
    assert "audit-agent" in out


def test_T_AL_7_main_activity_mode(script_mod, tmp_path, monkeypatch, capsys):
    act = tmp_path / "data" / "agent_activity.jsonl"
    act.parent.mkdir(parents=True, exist_ok=True)
    act.write_text(
        json.dumps({"ts": "2026-06-30T10:00:00+00:00", "agent_type": "data-agent",
                    "tools_count": 3, "runtime_sec": 5.0}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    rc = script_mod.main(["--activity"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "data-agent" in captured.out
