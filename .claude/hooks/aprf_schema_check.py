#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
APRF SubagentStop hook — peer review response schema enforcement.

Fires when a peer review subagent (one of 13 worker agents) is about to finish.
Validates the subagent's last assistant message JSON against
`schemas/peer_review_response.schema.json`.

Behavior:
- Valid response → exit 0 with `additionalContext` "APRF schema PASS"
- Invalid response → exit 2 with stderr feedback → Claude Code keeps the
  subagent running so it can fix and resubmit (Anthropic native retry).

Activation gate:
- Hook only does work when `<repo>/output/peer_review/.active` exists.
  Flag is created by `agents/peer_review.py` when launching a peer review,
  removed when complete. Prevents this hook from firing for non-APRF subagent
  calls (existing data/analysis subagents are untouched).

Failure modes (fail-open: exit 0):
- jsonschema missing: warn to stderr, exit 0
- schema file missing/broken: warn to stderr, exit 0
- transcript missing / no JSON in message: exit 0
  (these are not subagent fault — don't penalize)

Selftest:
    python .claude/hooks/aprf_schema_check.py --selftest

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


def _is_aprf_active() -> bool:
    return _ACTIVE_FLAG.exists()


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
            "additionalContext": f"APRF schema PASS for {agent_type or 'unknown'}",
        }
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def _emit_failure(error: str) -> None:
    feedback = (
        f"APRF schema validation FAIL: {error}\n\n"
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

    print("aprf_schema_check selftest: PASS")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_run_selftest())

    if not _is_aprf_active():
        sys.exit(0)

    hook_input = _parse_stdin()
    if not hook_input:
        sys.exit(0)

    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"APRF schema load failed (fail open): {e}", file=sys.stderr)
        sys.exit(0)

    msg = _get_last_message(hook_input)
    if not msg:
        sys.exit(0)

    payload = _extract_json_block(msg)
    if payload is None:
        sys.exit(0)

    ok, err = _validate(payload, schema)
    if ok:
        _emit_success(hook_input.get("agent_type", ""))
    else:
        _emit_failure(err)


if __name__ == "__main__":
    main()
