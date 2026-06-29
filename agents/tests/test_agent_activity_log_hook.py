# -*- coding: utf-8 -*-
"""
Phase 13-D-1 회귀: agent_activity_log SubagentStop hook.

Tests:
T-AAL-1: transcript 없을 때 metrics 추출 — tools_count 0, runtime_sec None
T-AAL-2: transcript jsonl 에서 tool_use + timestamps 추출 → runtime/tools_used
T-AAL-3: _log 가 jsonl append (덮어쓰기 X)
T-AAL-4: stderr 한 줄 포맷 — agent_type/runtime/tools 모두 포함
T-AAL-5: stdin json_object 파싱
T-AAL-6: stdin jsonl 폴백 파싱
T-AAL-7: --selftest exit 0
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "agent_activity_log.py"


@pytest.fixture(scope="module")
def hook_mod():
    spec = importlib.util.spec_from_file_location("agent_activity_log", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_AAL_1_extract_no_transcript(hook_mod):
    m = hook_mod._extract_metrics({"agent_type": "x", "agent_id": "y", "session_id": "z"})
    assert m["agent_type"] == "x"
    assert m["tools_count"] == 0
    assert m["runtime_sec"] is None
    assert m["tools_used"] == []


def test_T_AAL_2_extract_with_transcript(hook_mod, tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text(
        json.dumps({
            "timestamp": "2026-06-30T10:00:00Z",
            "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
        }) + "\n"
        + json.dumps({
            "timestamp": "2026-06-30T10:00:45Z",
            "message": {"content": [{"type": "tool_use", "name": "Read"}]},
        }) + "\n",
        encoding="utf-8",
    )
    m = hook_mod._extract_metrics({"agent_type": "x", "transcript_path": str(tp)})
    assert m["tools_count"] == 2
    assert "Bash" in m["tools_used"]
    assert "Read" in m["tools_used"]
    assert m["runtime_sec"] == 45.0


def test_T_AAL_3_log_appends(hook_mod, tmp_path):
    out = tmp_path / "act.jsonl"
    hook_mod._log({"agent_type": "a", "tools_count": 0}, out_file=out)
    hook_mod._log({"agent_type": "b", "tools_count": 1}, out_file=out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["agent_type"] == "a"
    assert json.loads(lines[1])["agent_type"] == "b"


def test_T_AAL_4_stderr_line_format(hook_mod):
    line = hook_mod._stderr_line({
        "agent_type": "audit-agent",
        "runtime_sec": 47.2,
        "tools_count": 12,
    })
    assert "audit-agent" in line
    assert "47.2s" in line
    assert "12 tools" in line


def test_T_AAL_5_parse_stdin_json_object(hook_mod):
    obj = hook_mod._parse_stdin('{"agent_type":"x","session_id":"abc"}')
    assert obj["agent_type"] == "x"
    assert obj["session_id"] == "abc"


def test_T_AAL_6_parse_stdin_jsonl(hook_mod):
    obj = hook_mod._parse_stdin('{"agent_type":"x"}\n{"foo":1}\n')
    assert obj.get("agent_type") == "x"


def test_T_AAL_7_selftest_exits_zero(hook_mod):
    rc = hook_mod._selftest()
    assert rc == 0
