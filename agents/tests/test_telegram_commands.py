# -*- coding: utf-8 -*-
"""
2026-07-03 사용자 요청: 텔레그램 /report 명령어 방식 회귀.

Tests:
T-TC-1: detect_commands — /report 감지
T-TC-2: detect_commands — /status + /help 감지
T-TC-3: detect_commands — 잡담 (명령어 없음) 무시
T-TC-4: detect_commands — 명령어가 첫 토큰 아니면 무시 (예: "안녕 /report" X)
T-TC-5: register_pending — 신규 등록
T-TC-6: register_pending — 중복 방지
T-TC-7: register_pending — 빈 pending file 신규 생성
T-TC-8: check_and_register — 통합 (mock fetch)
T-TC-9: _selftest exit 0
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "agents"))


@pytest.fixture(scope="module")
def cmd_mod():
    spec = importlib.util.spec_from_file_location(
        "check_telegram_commands",
        _REPO_ROOT / "agents" / "check_telegram_commands.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_TC_1_detect_report(cmd_mod):
    upd = [{"update_id": 1, "message": {"text": "/report"}}]
    hits = cmd_mod.detect_commands(upd)
    assert len(hits) == 1
    assert hits[0]["command"] == "/report"
    assert hits[0]["req_id"] == "REQ-USER-REPORT"


def test_T_TC_2_detect_status_and_help(cmd_mod):
    upd = [
        {"update_id": 1, "message": {"text": "/status"}},
        {"update_id": 2, "message": {"text": "/help 사용법 알려줘"}},
    ]
    hits = cmd_mod.detect_commands(upd)
    assert len(hits) == 2
    ids = {h["req_id"] for h in hits}
    assert "REQ-USER-STATUS" in ids
    assert "REQ-USER-HELP" in ids


def test_T_TC_3_ignore_chatter(cmd_mod):
    upd = [
        {"update_id": 1, "message": {"text": "안녕 오늘 뭐해"}},
        {"update_id": 2, "message": {"text": ""}},
        {"update_id": 3},  # message 없음
    ]
    hits = cmd_mod.detect_commands(upd)
    assert hits == []


def test_T_TC_4_command_only_at_start(cmd_mod):
    """첫 토큰이 명령어인 경우만 감지 (오탐 방지)."""
    upd = [
        {"update_id": 1, "message": {"text": "안녕 /report 해줘"}},  # 명령어 중간 → 무시
        {"update_id": 2, "message": {"text": "/report"}},  # 첫 토큰 → 감지
    ]
    hits = cmd_mod.detect_commands(upd)
    assert len(hits) == 1
    assert hits[0]["update_id"] == 2


def test_T_TC_5_register_new(cmd_mod, tmp_path):
    pending = tmp_path / "pending_requests.json"
    hits = [{
        "command": "/report", "req_id": "REQ-USER-REPORT",
        "description": "test", "update_id": 99, "text": "/report",
    }]
    result = cmd_mod.register_pending(hits, pending_path=pending)
    assert result["registered"] == 1
    data = json.loads(pending.read_text(encoding="utf-8"))
    ids = [i["id"] for i in data["pending"]]
    assert "REQ-USER-REPORT" in ids
    # source 필드 확인
    item = next(i for i in data["pending"] if i["id"] == "REQ-USER-REPORT")
    assert item["source"] == "telegram_command"


def test_T_TC_6_duplicate_prevention(cmd_mod, tmp_path):
    pending = tmp_path / "pending_requests.json"
    hits = [{
        "command": "/report", "req_id": "REQ-USER-REPORT",
        "description": "test", "update_id": 99, "text": "/report",
    }]
    r1 = cmd_mod.register_pending(hits, pending_path=pending)
    r2 = cmd_mod.register_pending(hits, pending_path=pending)
    assert r1["registered"] == 1
    assert r2["registered"] == 0
    assert r2["skipped"] == 1
    data = json.loads(pending.read_text(encoding="utf-8"))
    count = sum(1 for i in data["pending"] if i["id"] == "REQ-USER-REPORT")
    assert count == 1


def test_T_TC_7_new_pending_file_created(cmd_mod, tmp_path):
    """pending_requests.json 미존재 시 신규 생성."""
    pending = tmp_path / "pending_requests.json"
    assert not pending.exists()
    hits = [{
        "command": "/status", "req_id": "REQ-USER-STATUS",
        "description": "test", "update_id": 1, "text": "/status",
    }]
    result = cmd_mod.register_pending(hits, pending_path=pending)
    assert result["registered"] == 1
    assert pending.exists()


def test_T_TC_8_check_and_register_integrated(cmd_mod, tmp_path, monkeypatch):
    """통합: fetch mock → detect → register."""
    pending = tmp_path / "pending_requests.json"
    fake_updates = [
        {"update_id": 100, "message": {"text": "/report"}},
        {"update_id": 101, "message": {"text": "잡담"}},
    ]
    monkeypatch.setattr(cmd_mod, "fetch_recent_updates", lambda lookback=5: fake_updates)

    result = cmd_mod.check_and_register(pending_path=pending)
    assert result["fetched"] == 2
    assert result["hits"] == 1
    assert result["registered"] == 1


def test_T_TC_9_selftest_exit_zero(cmd_mod):
    rc = cmd_mod._selftest()
    assert rc == 0
