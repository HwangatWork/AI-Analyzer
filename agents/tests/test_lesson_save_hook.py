# -*- coding: utf-8 -*-
"""
Phase 13-B-2 회귀: lesson_save SessionEnd hook (DC-9).

Tests:
T-LS-1: empty transcript → 0 candidates
T-LS-2: FIX-X / lsn_xxx / Anti-Pattern / RCA / 재발 마커 5종 모두 탐지
T-LS-3: transcript_path 파일 경로로 읽기 성공
T-LS-4: 잘못된 JSON stdin → 빈 candidates, 비-차단
T-LS-5: write_candidates 가 jsonl 형식으로 append (덮어쓰기 X)
T-LS-6: --selftest mode → exit 0
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "lesson_save.py"


@pytest.fixture(scope="module")
def hook_mod():
    spec = importlib.util.spec_from_file_location("lesson_save", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_LS_1_empty_transcript(hook_mod):
    cands = hook_mod.extract_candidates({"session_id": "t1", "transcript": []})
    assert cands == []


def test_T_LS_2_all_markers_detected(hook_mod):
    text = (
        "FIX-G 패턴 발견. lsn_a1b2c3d4ef 저장 완료. "
        "Anti-Pattern 회피. RCA 정리. 재발 방지 필요."
    )
    cands = hook_mod.extract_candidates({
        "session_id": "t2",
        "transcript": [{"role": "assistant", "content": text}],
    })
    labels = {c["marker"] for c in cands}
    assert "FIX" in labels
    assert "lesson_id" in labels
    assert "anti_pattern" in labels
    assert "rca" in labels
    assert "regression_kr" in labels


def test_T_LS_3_transcript_path_file(hook_mod, tmp_path):
    transcript_file = tmp_path / "session.jsonl"
    transcript_file.write_text(
        json.dumps({"role": "assistant", "content": "FIX-Z root cause 확인"}) + "\n",
        encoding="utf-8",
    )
    cands = hook_mod.extract_candidates({
        "session_id": "t3",
        "transcript_path": str(transcript_file),
    })
    assert any(c["marker"] == "FIX" for c in cands)
    assert any(c["marker"] == "rca" for c in cands)


def test_T_LS_4_malformed_stdin_graceful(hook_mod):
    parsed = hook_mod._parse_stdin("이건 JSON 아님 {{{")
    assert parsed == {}
    cands = hook_mod.extract_candidates(parsed)
    assert cands == []


def test_T_LS_5_write_appends_jsonl(hook_mod, tmp_path):
    out = tmp_path / "lesson_candidates.jsonl"
    c1 = [{"ts": "x", "session_id": "a", "marker": "FIX", "excerpt": "first", "msg_index": 0}]
    c2 = [{"ts": "y", "session_id": "b", "marker": "rca", "excerpt": "second", "msg_index": 1}]
    n1 = hook_mod.write_candidates(c1, out)
    n2 = hook_mod.write_candidates(c2, out)
    assert n1 == 1 and n2 == 1
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["marker"] == "FIX"
    assert json.loads(lines[1])["marker"] == "rca"


def test_T_LS_6_selftest_exits_zero(hook_mod):
    rc = hook_mod._selftest()
    assert rc == 0
