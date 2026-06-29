# -*- coding: utf-8 -*-
"""
Phase 13-B-5 회귀: stop_hook TF Peer Review digest 섹션 (DC-10).

Tests:
T-TFD-1: tf_root 미존재 → 빈 문자열 (조건부 비표기)
T-TFD-2: tf_root 존재 but empty → 빈 문자열
T-TFD-3: aggregate.md 존재 → 응답 수 + consensus 추출
T-TFD-4: Meta-Patterns / Minority Dissent 섹션 보유 시 flag 표기
T-TFD-5: 다중 세션 디렉토리 시 가장 최근 mtime 선택
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "stop_hook.py"


@pytest.fixture(scope="module")
def stop_hook_mod():
    spec = importlib.util.spec_from_file_location("stop_hook_for_tfd", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AGG_BASIC = """# TF Peer Review Aggregate — 13 responses

## 1. Consensus Matrix
...

## 2. Urgency Revote

**Consensus most urgent**: item 3 (8/13 votes)

## 3. New Items Surfaced

_none_

## 4. Recommended Action Order

1. Item 3 — 8 votes
"""

_AGG_RICH = _AGG_BASIC + """

## 5. Meta-Patterns

_files referenced by ≥5 agents_

- `agents/foo.py` (5 agents: a, b, c, d, e)

## 6. Minority Dissent

_direct-relevance agents who voted differently_

- **stock-agent** (vote 7): some long reason
"""


def test_T_TFD_1_no_tf_root(stop_hook_mod, tmp_path):
    section = stop_hook_mod.get_tf_digest_section(tf_root=tmp_path / "missing")
    assert section == ""


def test_T_TFD_2_empty_tf_root(stop_hook_mod, tmp_path):
    (tmp_path / "peer_review").mkdir()
    section = stop_hook_mod.get_tf_digest_section(tf_root=tmp_path / "peer_review")
    assert section == ""


def test_T_TFD_3_basic_aggregate(stop_hook_mod, tmp_path):
    sess = tmp_path / "peer_review" / "sess-001"
    sess.mkdir(parents=True)
    (sess / "aggregate.md").write_text(_AGG_BASIC, encoding="utf-8")
    section = stop_hook_mod.get_tf_digest_section(tf_root=tmp_path / "peer_review")
    assert "TF Peer Review" in section
    assert "sess-001" in section
    assert "응답 13개" in section
    assert "item 3 (8/13)" in section
    # No Meta/Dissent flags in basic aggregate
    assert "Meta" not in section
    assert "Dissent" not in section


def test_T_TFD_4_rich_aggregate_flags(stop_hook_mod, tmp_path):
    sess = tmp_path / "peer_review" / "sess-rich"
    sess.mkdir(parents=True)
    (sess / "aggregate.md").write_text(_AGG_RICH, encoding="utf-8")
    section = stop_hook_mod.get_tf_digest_section(tf_root=tmp_path / "peer_review")
    assert "Meta" in section
    assert "Dissent" in section


def test_T_TFD_5_latest_dir_selected(stop_hook_mod, tmp_path):
    root = tmp_path / "peer_review"
    older = root / "sess-old"
    newer = root / "sess-new"
    older.mkdir(parents=True)
    (older / "aggregate.md").write_text(
        "# TF Peer Review Aggregate — 5 responses\n", encoding="utf-8"
    )
    time.sleep(0.05)
    newer.mkdir(parents=True)
    (newer / "aggregate.md").write_text(
        "# TF Peer Review Aggregate — 13 responses\n", encoding="utf-8"
    )
    section = stop_hook_mod.get_tf_digest_section(tf_root=root)
    assert "sess-new" in section
    assert "sess-old" not in section
    assert "응답 13개" in section
