# -*- coding: utf-8 -*-
"""
Phase 13-B-7-2 회귀: tf_schema_check.py 실측 layer (tools_used / runtime_sec).

강제 NOT — 측정 only. AI Harness 12-Metric 기반 데이터.

Tests:
T-TF-MET-1: _collect_metrics 가 transcript 없으면 기본 메트릭 반환
T-TF-MET-2: _collect_metrics 가 tool_use 블록 수집 (정렬된 unique)
T-TF-MET-3: _collect_metrics 가 timestamp 2개 이상 시 runtime_sec 계산
T-TF-MET-4: _write_metrics 가 .active 부재 시 None 반환 (fail-open)
T-TF-MET-5: _write_metrics 가 .active 있을 때 파일 생성
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "tf_schema_check.py"


def _import_hook():
    spec = importlib.util.spec_from_file_location("tf_schema_check", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _preserve_active_state():
    """Save/restore .active flag so tests don't disrupt a real TF session."""
    mod = _import_hook()
    flag = mod._ACTIVE_FLAG
    had = flag.exists()
    saved = flag.read_text(encoding="utf-8") if had else None
    yield
    if had and saved is not None:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(saved, encoding="utf-8")
    elif flag.exists():
        flag.unlink()


def test_T_TF_MET_1_collect_no_transcript_returns_default():
    mod = _import_hook()
    metrics = mod._collect_metrics(
        {"agent_type": "news-agent", "agent_id": "abc"},
        schema_ok=True
    )
    assert metrics["agent_type"] == "news-agent"
    assert metrics["agent_id"] == "abc"
    assert metrics["schema_ok"] is True
    assert metrics["tools_used"] == []
    assert metrics["runtime_sec"] is None


def test_T_TF_MET_2_collect_tools_unique_sorted(tmp_path):
    mod = _import_hook()
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        {"message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"message": {"content": [{"type": "text", "text": "hello"}]}},
    ]
    transcript.write_text(
        "\n".join(json.dumps(l) for l in lines), encoding="utf-8"
    )
    metrics = mod._collect_metrics(
        {"agent_type": "x", "transcript_path": str(transcript)},
        schema_ok=True
    )
    assert metrics["tools_used"] == ["Bash", "Read"]


def test_T_TF_MET_3_collect_runtime_from_timestamps(tmp_path):
    mod = _import_hook()
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        {"timestamp": "2026-06-29T10:00:00Z", "message": {"content": []}},
        {"timestamp": "2026-06-29T10:00:30Z", "message": {"content": []}},
    ]
    transcript.write_text(
        "\n".join(json.dumps(l) for l in lines), encoding="utf-8"
    )
    metrics = mod._collect_metrics(
        {"agent_type": "x", "transcript_path": str(transcript)},
        schema_ok=True
    )
    assert metrics["runtime_sec"] == 30.0


def test_T_TF_MET_4_write_no_active_returns_none():
    mod = _import_hook()
    if mod._ACTIVE_FLAG.exists():
        mod._ACTIVE_FLAG.unlink()
    result = mod._write_metrics({"agent_type": "x"})
    assert result is None


def test_T_TF_MET_5_write_with_active_creates_file():
    mod = _import_hook()
    session_id = "test_session_metrics_5"
    mod._ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    mod._ACTIVE_FLAG.write_text(session_id, encoding="utf-8")

    target_dir = mod._OUTPUT_DIR / session_id / "metrics"
    target_file = target_dir / "fake-agent.json"

    try:
        result = mod._write_metrics({
            "agent_type": "fake-agent",
            "schema_ok": True,
            "tools_used": ["Bash"],
            "runtime_sec": 12.5,
        })
        assert result is not None
        assert target_file.exists()
        content = json.loads(target_file.read_text(encoding="utf-8"))
        assert content["agent_type"] == "fake-agent"
        assert content["tools_used"] == ["Bash"]
        assert content["runtime_sec"] == 12.5
    finally:
        if target_file.exists():
            target_file.unlink()
        if target_dir.exists():
            try:
                target_dir.rmdir()
                target_dir.parent.rmdir()
            except OSError:
                pass
