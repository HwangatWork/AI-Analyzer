#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TF SubagentStop hook — peer review response schema enforcement.

Fires when a peer review subagent (one of 13 worker agents) is about to finish.
Validates the subagent's last assistant message JSON against
`schemas/peer_review_response.schema.json`.

Behavior:
- Valid response → exit 0 with `additionalContext` "TF schema PASS"
- Invalid response → exit 2 with stderr feedback → Claude Code keeps the
  subagent running so it can fix and resubmit (Anthropic native retry).

Activation gate:
- Hook only does work when `<repo>/output/peer_review/.active` exists.
  Flag is created by `agents/peer_review.py` when launching a peer review,
  removed when complete. Prevents this hook from firing for non-TF subagent
  calls (existing data/analysis subagents are untouched).

Failure modes (fail-open: exit 0):
- jsonschema missing: warn to stderr, exit 0
- schema file missing/broken: warn to stderr, exit 0
- transcript missing / no JSON in message: exit 0
  (these are not subagent fault — don't penalize)

Selftest:
    python .claude/hooks/tf_schema_check.py --selftest

Phase 13-B-2 (2026-06-28).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "peer_review_response.schema.json"
_ACTIVE_FLAG = _REPO_ROOT / "output" / "peer_review" / ".active"
_OUTPUT_DIR = _REPO_ROOT / "output" / "peer_review"


def _is_tf_active() -> bool:
    return _ACTIVE_FLAG.exists()


# ── Phase 13-B-7-2: 실측 layer (강제 NOT, 측정만) ──────────────────────

def _collect_metrics(hook_input: dict, schema_ok: bool, schema_err: str = "") -> dict:
    """Collect agent execution metrics for AI Harness 12-Metric framework.
    측정 only — 강제 차단 없음. 향후 Behavioral Contract 강제의 기반 데이터.
    """
    from datetime import datetime
    metrics = {
        "agent_type": hook_input.get("agent_type", "unknown"),
        "agent_id": hook_input.get("agent_id", ""),
        "session_id": hook_input.get("session_id", ""),
        "timestamp_end": datetime.now().isoformat(timespec="seconds"),
        "schema_ok": schema_ok,
        "schema_err": schema_err[:200] if schema_err else "",
        "tools_used": [],
        "runtime_sec": None,
    }
    transcript_path = hook_input.get("transcript_path")
    if not transcript_path or not Path(transcript_path).exists():
        return metrics
    tools = set()
    timestamps = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get("timestamp") or obj.get("created_at")
                if ts:
                    timestamps.append(ts)
                msg = obj.get("message", obj)
                content = msg.get("content", [])
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tn = b.get("name")
                            if tn:
                                tools.add(tn)
    except Exception:
        return metrics
    metrics["tools_used"] = sorted(tools)
    if len(timestamps) >= 2:
        try:
            from datetime import datetime as _dt
            t0 = _dt.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            t1 = _dt.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            metrics["runtime_sec"] = round((t1 - t0).total_seconds(), 1)
        except Exception:
            pass
    return metrics


def _read_session_id_from_active() -> str:
    """Read session ID from .active flag (written by /tf-review Step 1)."""
    try:
        return _ACTIVE_FLAG.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_metrics(metrics: dict) -> Path | None:
    """Write metrics to output/peer_review/<session>/metrics/<agent>.json.
    Fail-open: 어떤 IO 오류도 hook 실행 차단 안 함."""
    session_id = _read_session_id_from_active()
    if not session_id:
        return None
    try:
        out_dir = _OUTPUT_DIR / session_id / "metrics"
        out_dir.mkdir(parents=True, exist_ok=True)
        agent_type = metrics.get("agent_type") or "unknown"
        out_path = out_dir / f"{agent_type}.json"
        out_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return out_path
    except Exception:
        return None


def _parse_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _last_assistant_from_transcript(path: str) -> str:
    """Read JSONL transcript file, return last assistant text content."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        msg = obj.get("message") or obj
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            return "".join(b.get("text", "") for b in content if isinstance(b, dict))
        return str(content)
    return ""


def _get_last_message(hook_input: dict) -> str:
    msg = hook_input.get("last_assistant_message", "")
    if msg:
        return str(msg)
    tp = hook_input.get("transcript_path")
    if tp:
        return _last_assistant_from_transcript(tp)
    return ""


def _extract_json_block(text: str) -> dict | None:
    """Extract first JSON object from text. Handles ```json fenced blocks
    and raw braces. Returns None if no parseable JSON found."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    raw = re.search(r"(\{[\s\S]*\})", text)
    if raw:
        try:
            return json.loads(raw.group(1))
        except Exception:
            pass
    return None


def _validate(payload: dict, schema: dict) -> tuple[bool, str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return True, "jsonschema not available — fail open"
    try:
        Draft202012Validator(schema).validate(payload)
        return True, ""
    except Exception as e:
        return False, str(e).split("\n")[0][:400]


def _emit_success(agent_type: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "additionalContext": f"TF schema PASS for {agent_type or 'unknown'}",
        }
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def _emit_failure(error: str) -> None:
    feedback = (
        f"TF schema validation FAIL: {error}\n\n"
        "응답이 schemas/peer_review_response.schema.json 과 불일치합니다. "
        "필수 필드 (agent, domain_relevance, agreement, urgency_vote, reason) + "
        "enum/길이/타입 제약을 확인해 단일 JSON 객체로 재제출해주세요."
    )
    print(feedback, file=sys.stderr)
    sys.exit(2)


def _run_selftest() -> int:
    """Inline selftest with synthetic valid/invalid fixtures."""
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"SELFTEST FAIL: schema load: {e}", file=sys.stderr)
        return 1

    valid_msg = (
        'Here is the response:\n```json\n'
        '{\n'
        '  "agent": "news-agent",\n'
        '  "domain_relevance": "direct",\n'
        '  "agreement": "agree",\n'
        '  "urgency_vote": 1,\n'
        '  "reason": "RSS empty case에서도 mtime이 갱신되어 false positive 발생 가능"\n'
        '}\n'
        '```'
    )
    payload = _extract_json_block(valid_msg)
    if payload is None:
        print("SELFTEST FAIL: valid fixture extraction returned None", file=sys.stderr)
        return 1
    ok, err = _validate(payload, schema)
    if not ok:
        print(f"SELFTEST FAIL: valid fixture rejected: {err}", file=sys.stderr)
        return 1

    invalid_msg = (
        '```json\n'
        '{\n'
        '  "agent": "news-agent",\n'
        '  "domain_relevance": "tangent",\n'
        '  "agreement": "agree",\n'
        '  "urgency_vote": 1,\n'
        '  "reason": "valid reason text here for testing"\n'
        '}\n'
        '```'
    )
    payload = _extract_json_block(invalid_msg)
    ok, err = _validate(payload, schema)
    if ok:
        print("SELFTEST FAIL: invalid fixture (enum violation) accepted", file=sys.stderr)
        return 1

    print("tf_schema_check selftest: PASS")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_run_selftest())

    if not _is_tf_active():
        sys.exit(0)

    hook_input = _parse_stdin()
    if not hook_input:
        sys.exit(0)

    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"TF schema load failed (fail open): {e}", file=sys.stderr)
        sys.exit(0)

    msg = _get_last_message(hook_input)
    if not msg:
        sys.exit(0)

    payload = _extract_json_block(msg)
    if payload is None:
        sys.exit(0)

    ok, err = _validate(payload, schema)

    # Phase 13-B-7-2: 실측 layer — schema 결과와 무관하게 metrics 기록
    # (강제 NOT, 측정만. fail-open IO).
    try:
        metrics = _collect_metrics(hook_input, schema_ok=ok, schema_err=err)
        _write_metrics(metrics)
    except Exception:
        pass

    if ok:
        _emit_success(hook_input.get("agent_type", ""))
    else:
        _emit_failure(err)


if __name__ == "__main__":
    main()
