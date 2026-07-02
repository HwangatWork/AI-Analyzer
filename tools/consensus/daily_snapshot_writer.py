# -*- coding: utf-8 -*-
"""Consensus Revision Tracker — Phase 14-0-C Daily Snapshot Writer.

Point-in-time (PIT) invariant 강제. Ljungqvist (2009) survivorship bias 회피:
snapshot 안의 모든 row 의 as_of ≤ snapshot_date (미래 정보 누출 차단).

Peer review consensus (validation 필수 5/5):
- (a) UTC date partition: data/snapshots/YYYY-MM-DD/<source>.json
- (c) base_currency + base_timezone 명시
- (e) PIT invariant: as_of ≤ snapshot_date (핵심)
- meta-audit Q2 traceability: sha256 fingerprint + mtime

API:
    write_snapshot(rows, source, now, base_dir=None) -> {"path", "sha256", ...}

Raises SnapshotIntegrityError on:
- rows 중 as_of 부재
- as_of 파싱 실패
- 미래 as_of (Ljungqvist 위반)

Idempotency (T-DSW-3 + T-DSW-7): 동일 rows + 동일 시각 → 동일 sha256
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BASE_CURRENCY = "KRW"
BASE_TIMEZONE = "UTC"
DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshots"


class SnapshotIntegrityError(RuntimeError):
    """PIT invariant 위반 (Ljungqvist 2009 회피)."""


def _parse_as_of(row: dict) -> datetime:
    v = row.get("as_of")
    if not v:
        raise SnapshotIntegrityError(f"as_of 부재: {row}")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as e:
        raise SnapshotIntegrityError(f"as_of 파싱 실패 ({v!r}): {e}") from e


def _normalize_row(row: dict) -> dict:
    """as_of 를 ISO UTC string 으로 정규화 (idempotent hash 위해)."""
    parsed = _parse_as_of(row)
    normalized = dict(row)
    normalized["as_of"] = parsed.isoformat(timespec="seconds")
    return normalized


def _canonical_payload_bytes(payload: dict) -> bytes:
    """정렬된 canonical JSON bytes (sha256 재현성용)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def write_snapshot(
    rows: Iterable[dict],
    source: str,
    now: datetime | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """PIT snapshot 저장.

    Args:
        rows: 각 row 는 dict, 최소 `as_of` 필드 필수 (ISO or datetime)
        source: source identifier (예: "wisereport", "consensus_kr")
        now: 기준 시각 (test 시 override, default now UTC)
        base_dir: 저장 root (default data/snapshots)

    Returns:
        {"path": str, "sha256": str, "row_count": int,
         "snapshot_date": "YYYY-MM-DD", "base_currency": str,
         "base_timezone": str}

    Raises:
        SnapshotIntegrityError: PIT 위반 / as_of 부재 / 파싱 실패
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    base_dir = base_dir or DEFAULT_BASE_DIR

    rows_list = list(rows)

    # 각 row 검증 + 정규화
    normalized = []
    for r in rows_list:
        parsed = _parse_as_of(r)
        # PIT invariant: as_of ≤ now (Ljungqvist 2009 회피)
        if parsed > now:
            raise SnapshotIntegrityError(
                f"미래 as_of ({parsed.isoformat()}) > now ({now.isoformat()}). "
                f"Ljungqvist 2009 point-in-time invariant 위반."
            )
        normalized.append(_normalize_row(r))

    # 순서 무관 idempotency (T-DSW-7): as_of asc 정렬
    normalized.sort(key=lambda r: r["as_of"])

    snapshot_date = now.date().isoformat()
    payload = {
        "snapshot_date": snapshot_date,
        "source": source,
        "base_currency": BASE_CURRENCY,
        "base_timezone": BASE_TIMEZONE,
        "row_count": len(normalized),
        "rows": normalized,
    }

    canonical = _canonical_payload_bytes(payload)
    sha256 = hashlib.sha256(canonical).hexdigest()

    out_dir = base_dir / snapshot_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{source}.json"
    out_path.write_bytes(canonical)

    return {
        "path": str(out_path),
        "sha256": sha256,
        "row_count": len(normalized),
        "snapshot_date": snapshot_date,
        "base_currency": BASE_CURRENCY,
        "base_timezone": BASE_TIMEZONE,
    }
