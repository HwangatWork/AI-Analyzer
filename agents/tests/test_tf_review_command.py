# -*- coding: utf-8 -*-
"""
Phase 13-B-3 (C안) 회귀: /tf-review slash command + .active 라이프사이클.

DC-2 재정의: command 파일 존재 + .active lifecycle 동작.
(원안 'peer_review.py --dry-run' 폐기 — Task tool은 subprocess에서 호출 불가)

Tests:
T_TF_CMD_1: .claude/commands/tf-review.md 존재
T_TF_CMD_2: tf-review.md 필수 키워드 포함 (set_active, Task, clear_active)
T_TF_CMD_3: settings.json CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 등록
T_TF_AF_1: set_active로 .active 생성
T_TF_AF_2: clear_active로 .active 삭제
T_TF_AF_3: get_session_id가 저장된 ID 반환
T_TF_AF_4: get_session_id가 .active 부재 시 빈 문자열 반환
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from agents.tf_active import (  # noqa: E402
    _FLAG_PATH,
    clear_active,
    get_session_id,
    is_active,
    set_active,
)


@pytest.fixture(autouse=True)
def _preserve_active_state():
    """Save/restore .active state so tests don't disrupt a real TF session."""
    had = _FLAG_PATH.exists()
    saved = _FLAG_PATH.read_text(encoding="utf-8") if had else None
    yield
    if had and saved is not None:
        _FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FLAG_PATH.write_text(saved, encoding="utf-8")
    elif _FLAG_PATH.exists():
        _FLAG_PATH.unlink()


def test_T_TF_CMD_1_command_file_exists():
    cmd = _REPO_ROOT / ".claude" / "commands" / "tf-review.md"
    assert cmd.exists(), f"{cmd} missing"


def test_T_TF_CMD_2_command_has_required_lifecycle_keywords():
    cmd = _REPO_ROOT / ".claude" / "commands" / "tf-review.md"
    text = cmd.read_text(encoding="utf-8")
    for keyword in ("set_active", "Task", "clear_active",
                    "peer_review_response.schema.json"):
        assert keyword in text, f"tf-review.md missing keyword: {keyword!r}"


def test_T_TF_CMD_3_settings_has_team_env_var():
    settings = _REPO_ROOT / ".claude" / "settings.json"
    cfg = json.loads(settings.read_text(encoding="utf-8"))
    assert cfg.get("env", {}).get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1", \
        "settings.json env block must enable Agent Teams"


def test_T_TF_AF_1_set_active_creates_flag():
    clear_active()
    assert not is_active()
    path = set_active("test-session-13b3")
    assert is_active()
    assert path == _FLAG_PATH


def test_T_TF_AF_2_clear_active_removes_flag():
    set_active("temp")
    assert is_active()
    clear_active()
    assert not is_active()
    # Idempotent: second clear is no-op
    clear_active()
    assert not is_active()


def test_T_TF_AF_3_get_session_id_returns_saved_value():
    set_active("20260629_140000")
    assert get_session_id() == "20260629_140000"


def test_T_TF_AF_4_get_session_id_empty_when_inactive():
    clear_active()
    assert get_session_id() == ""
