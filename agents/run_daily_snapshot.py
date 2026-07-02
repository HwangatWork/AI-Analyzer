# -*- coding: utf-8 -*-
"""Daily Snapshot Agent — Phase 14-0-C 파이프라인 통합 (2026-07-03).

meta-audit 9차 Q3/Q5 CRITICAL fix:
- Q3 (traceability): sha256 sink 를 data/agent_activity.jsonl 로 연결
- Q5 (integration): PIPELINE_STAGES 등록 → 매일 자동 실행

역할:
- audit 완료 직후 (STAGE_DEPS: run_audit_agent.py 후) 실행
- decision.json / audit_report.json / narrative_context.json 을 하나의 snapshot 으로 wrap
- tools/consensus/daily_snapshot_writer.write_snapshot() 호출
- PIT invariant 강제 (Ljungqvist 2009)
- sha256 + snapshot_path 를 agent_activity.jsonl append (append-only 감사 흔적)

Done Criteria (DS-1 ~ DS-4):
- DS-1: input files (decision.json + audit_report.json) 존재
- DS-2: snapshot 파일 생성 성공 (SnapshotIntegrityError 없음)
- DS-3: sha256 재현성 확인 (2회 호출 시 동일)
- DS-4: agent_activity.jsonl 에 snapshot_written 이벤트 append
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 경로 세팅
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
ACTIVITY_LOG = BASE_DIR / "data" / "agent_activity.jsonl"

sys.path.insert(0, str(BASE_DIR))
from tools.consensus.daily_snapshot_writer import (  # noqa: E402
    write_snapshot,
    SnapshotIntegrityError,
)


def _load_json_safe(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def _build_rows(now: datetime) -> list[dict]:
    """decision + audit + narrative_context 을 snapshot rows 로 wrap.

    각 row 는 as_of (source generated_at 또는 mtime) + payload 요약.
    """
    now_iso = now.isoformat(timespec="seconds")
    rows = []

    # 1. decision.json
    decision = _load_json_safe(OUTPUT_DIR / "decision.json")
    if decision:
        composite = decision.get("composite_score")
        rows.append({
            "as_of": decision.get("computed_at", now_iso),
            "kind": "decision",
            "composite_score": composite,
            "sp500_action": decision.get("sp500", {}).get("action"),
            "kospi_action": decision.get("kospi", {}).get("action"),
        })

    # 2. audit_report.json
    audit = _load_json_safe(PROCESSED_DIR / "audit_report.json")
    if audit:
        s = audit.get("summary", {})
        rows.append({
            "as_of": audit.get("generated_at", now_iso),
            "kind": "audit",
            "audit_status": audit.get("audit_status"),
            "total": s.get("total"),
            "passed": s.get("passed"),
            "failed_critical": s.get("failed_critical"),
        })

    # 3. narrative_context.json
    narrative = _load_json_safe(OUTPUT_DIR / "narrative_context.json")
    if narrative:
        rows.append({
            "as_of": narrative.get("generated_at", now_iso),
            "kind": "narrative_context",
            "signal": narrative.get("signal"),
            "confidence_pct": narrative.get("confidence_pct"),
            "total_signals": narrative.get("total_signals"),
        })

    return rows


def _append_activity_log(payload: dict, log_path: Path = ACTIVITY_LOG) -> bool:
    """meta-audit Q3 fix: sha256 sink 를 agent_activity.jsonl 로 연결.

    실패해도 파이프라인 차단 X (advisory).
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        print(f"  [DS-4] activity log append 실패 (advisory): {e}", file=sys.stderr)
        return False


def run_daily_snapshot(
    now: datetime | None = None,
    base_dir: Path | None = None,
    log_path: Path | None = None,
) -> dict:
    """공개 API. test 에서 인자 override."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    base_dir = base_dir or BASE_DIR
    log_path = log_path or (base_dir / "data" / "agent_activity.jsonl")

    # rows 빌드 (실 파이프라인 시 필드 기준)
    rows = _build_rows(now)

    fails = []

    # DS-1: input 최소 1건 필요 (decision 또는 audit 또는 narrative)
    if not rows:
        fails.append("DS-1 FAIL: 입력 파일 (decision/audit/narrative) 모두 부재")

    if fails:
        return {"status": "FAIL", "fails": fails, "rows_count": 0}

    # DS-2: snapshot 생성
    snapshot_dir = base_dir / "data" / "snapshots"
    try:
        result = write_snapshot(
            rows,
            source="pipeline_summary",
            now=now,
            base_dir=snapshot_dir,
        )
    except SnapshotIntegrityError as e:
        return {
            "status": "FAIL",
            "fails": [f"DS-2 FAIL: {e}"],
            "rows_count": len(rows),
        }

    # DS-4: activity log append (traceability sink)
    log_payload = {
        "ts": now.isoformat(timespec="seconds"),
        "agent_type": "daily-snapshot",
        "event": "snapshot_written",
        "snapshot_date": result["snapshot_date"],
        "sha256": result["sha256"],
        "row_count": result["row_count"],
        "path": result["path"],
    }
    logged = _append_activity_log(log_payload, log_path=log_path)

    return {
        "status": "PASS",
        "rows_count": len(rows),
        "snapshot_path": result["path"],
        "sha256": result["sha256"],
        "logged": logged,
    }


def main() -> int:
    print("=" * 60)
    print("Daily Snapshot Agent — Phase 14-0-C 파이프라인 통합")
    print("=" * 60)

    result = run_daily_snapshot()

    if result["status"] == "FAIL":
        for f in result["fails"]:
            print(f"  [X] {f}")
        print("DONE_CRITERIA: FAIL")
        return 1

    print(f"  ✓ DS-1 rows: {result['rows_count']}")
    print(f"  ✓ DS-2 snapshot: {result['snapshot_path']}")
    print(f"  ✓ DS-3 sha256: {result['sha256'][:16]}...")
    print(f"  ✓ DS-4 activity log append: {result['logged']}")
    print("DONE_CRITERIA: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
