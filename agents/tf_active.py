# -*- coding: utf-8 -*-
"""
TF Active flag lifecycle helpers.

`.active` flag at `<repo>/output/peer_review/.active` gates hooks
(tf_schema_check, tf_aggregate) so they fire only during TF reviews.

Content of `.active` file = session ID (timestamp). Used by:
- `.claude/commands/tf-review.md` (via Bash) to set/clear during review
- `tf_aggregate.py` to determine target subdirectory
- pytest tests for lifecycle verification

Phase 13-B-3 (2026-06-29). C안: slash command 패턴 — peer_review.py 미생성,
tf-review.md slash command가 set/clear 호출.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FLAG_PATH = _REPO_ROOT / "output" / "peer_review" / ".active"


def set_active(session_id: str) -> Path:
    """Create `.active` flag with given session ID. Idempotent."""
    _FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FLAG_PATH.write_text(str(session_id), encoding="utf-8")
    return _FLAG_PATH


def clear_active() -> None:
    """Remove `.active` flag if present. No-op if absent."""
    if _FLAG_PATH.exists():
        try:
            _FLAG_PATH.unlink()
        except Exception:
            pass


def is_active() -> bool:
    return _FLAG_PATH.exists()


def get_session_id() -> str:
    """Return current session ID from `.active`, empty string if absent."""
    try:
        return _FLAG_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
