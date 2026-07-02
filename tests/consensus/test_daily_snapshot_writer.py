# -*- coding: utf-8 -*-
"""
Phase 14-0-C 회귀: Daily Snapshot Writer (PIT invariant + Ljungqvist 2009 회피).

Peer review consensus (validation 필수 5/5):
- (a) UTC date partition — T-DSW-4 2-day 시퀀스
- (c) 단위 timezone/currency — T-DSW-6 base_currency/base_timezone
- (e) PIT invariant (핵심) — T-DSW-1 (통과), T-DSW-2 (block)
- meta-audit Q2 sha256 재현성 — T-DSW-3

Tests:
T-DSW-1: 정상 PIT (as_of ≤ snapshot_date) → 파일 생성 + payload 정합
T-DSW-2: 미래 as_of → SnapshotIntegrityError (block)
T-DSW-3: idempotent (동일 rows + 동일 시각 → 동일 sha256)
T-DSW-4: 2-day 시퀀스 → 서로 다른 partition 디렉토리
T-DSW-5: as_of 필드 부재 → SnapshotIntegrityError
T-DSW-6: 단위 명시 (base_currency + base_timezone)
T-DSW-7: rows 정렬 (as_of asc) → 순서 무관 idempotent
T-DSW-8: as_of 파싱 실패 → SnapshotIntegrityError
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from tools.consensus import daily_snapshot_writer as dsw


def _mk_rows(as_of_list: list[str]) -> list[dict]:
    return [{"as_of": s, "value": i * 1.1} for i, s in enumerate(as_of_list)]


def test_T_DSW_1_normal_pit_writes_file(tmp_path):
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = _mk_rows(["2026-07-01T09:00:00+00:00", "2026-07-02T08:00:00+00:00"])
    r = dsw.write_snapshot(rows, source="test_src", now=now, base_dir=tmp_path)
    out_path = Path(r["path"])
    assert out_path.exists()
    assert out_path.parent.name == "2026-07-02"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 2
    assert payload["snapshot_date"] == "2026-07-02"


def test_T_DSW_2_future_as_of_blocked(tmp_path):
    """미래 as_of → Ljungqvist 2009 회피 (block)."""
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = _mk_rows(["2026-07-05T00:00:00+00:00"])  # 3일 미래
    with pytest.raises(dsw.SnapshotIntegrityError):
        dsw.write_snapshot(rows, source="test", now=now, base_dir=tmp_path)


def test_T_DSW_3_idempotent_same_input_same_hash(tmp_path):
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = _mk_rows(["2026-07-01T09:00:00+00:00", "2026-07-02T08:00:00+00:00"])
    r1 = dsw.write_snapshot(rows, source="src", now=now, base_dir=tmp_path)
    r2 = dsw.write_snapshot(rows, source="src", now=now, base_dir=tmp_path)
    assert r1["sha256"] == r2["sha256"], "동일 rows + 동일 시각인데 hash 다름"


def test_T_DSW_4_two_day_sequence_different_partitions(tmp_path):
    """2-day 시퀀스 → 서로 다른 partition (mock clock)."""
    day1 = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    rows_d1 = _mk_rows(["2026-07-01T09:00:00+00:00"])
    rows_d2 = _mk_rows(["2026-07-02T09:00:00+00:00"])
    r1 = dsw.write_snapshot(rows_d1, source="src", now=day1, base_dir=tmp_path)
    r2 = dsw.write_snapshot(rows_d2, source="src", now=day2, base_dir=tmp_path)
    assert Path(r1["path"]).parent.name == "2026-07-01"
    assert Path(r2["path"]).parent.name == "2026-07-02"
    assert r1["sha256"] != r2["sha256"]


def test_T_DSW_5_missing_as_of_blocked(tmp_path):
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = [{"value": 100}]  # as_of 부재
    with pytest.raises(dsw.SnapshotIntegrityError):
        dsw.write_snapshot(rows, source="src", now=now, base_dir=tmp_path)


def test_T_DSW_6_units_declared(tmp_path):
    """base_currency + base_timezone 명시 (validation Q1 c)."""
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = _mk_rows(["2026-07-02T08:00:00+00:00"])
    r = dsw.write_snapshot(rows, source="src", now=now, base_dir=tmp_path)
    assert r["base_currency"] == "KRW"
    assert r["base_timezone"] == "UTC"
    payload = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
    assert payload["base_currency"] == "KRW"
    assert payload["base_timezone"] == "UTC"


def test_T_DSW_7_rows_sorted_order_invariant(tmp_path):
    """입력 순서 무관하게 idempotent hash (rows 정렬 후 저장)."""
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows_asc = _mk_rows(["2026-07-01T09:00:00+00:00", "2026-07-02T08:00:00+00:00"])
    rows_desc = list(reversed(rows_asc))
    r1 = dsw.write_snapshot(rows_asc, source="src", now=now, base_dir=tmp_path)
    r2 = dsw.write_snapshot(rows_desc, source="src", now=now, base_dir=tmp_path)
    assert r1["sha256"] == r2["sha256"], "순서만 다른데 hash 다름 → non-idempotent"


def test_T_DSW_8_invalid_as_of_format_blocked(tmp_path):
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    rows = [{"as_of": "not-a-date", "value": 1}]
    with pytest.raises(dsw.SnapshotIntegrityError):
        dsw.write_snapshot(rows, source="src", now=now, base_dir=tmp_path)
