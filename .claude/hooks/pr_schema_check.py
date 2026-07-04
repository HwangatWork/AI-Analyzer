#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
/pr SubagentStop hook — peer review round response schema enforcement.

Fires when a /pr review subagent (worker agents + critic-agent) finishes.
Validates the subagent's last assistant message JSON against
`schemas/pr_round_response.schema.json`.

Behavior:
- Valid response → exit 0 with `additionalContext` "PR schema PASS"
- Invalid response → exit 2 with stderr feedback → subagent revises and
  resubmits (Anthropic native live retry, same mechanism as tf_schema_check)

Activation gate:
- Only does work when `<repo>/output/peer_review_pr/.active` exists.
  Flag is created by the /pr skill Phase 0, removed at Phase 5.
  Prevents firing for non-/pr subagent calls. Independent from the TF flag
  (`output/peer_review/.active`) — the two review systems never interfere.

Failure modes (fail-open: exit 0, same policy as tf_schema_check):
- jsonschema missing / schema file broken / transcript missing / no JSON
  block in message → exit 0 (not the subagent's fault; the /pr skill
  orchestrator separately verifies saved round JSON files exist)

Selftest:
    python .claude/hooks/pr_schema_check.py --selftest
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_stdio()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "pr_round_response.schema.json"
_ACTIVE_FLAG = _REPO_ROOT / "output" / "peer_review_pr" / ".active"


def _is_pr_active() -> bool:
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
            "additionalContext": f"PR schema PASS for {agent_type or 'unknown'}",
        }
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def _emit_failure(error: str) -> None:
    feedback = (
        f"PR schema validation FAIL: {error}\n\n"
        "Your response does not conform to schemas/pr_round_response.schema.json. "
        "Required fields: agent, round(1-5), stance(support|oppose|conditional), "
        "key_points(>=1 items, each >=10 chars), risks, consensus_ready(bool). "
        "When round >= 2, feedback_addressed with >=2 items "
        "({to_agent, point, response}) is required. Resubmit as a single JSON object."
    )
    print(feedback, file=sys.stderr)
    sys.exit(2)


def _run_selftest() -> int:
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"SELFTEST FAIL: schema load: {e}", file=sys.stderr)
        return 1

    valid_r1 = {
        "agent": "critic-agent",
        "round": 1,
        "stance": "conditional",
        "key_points": ["walk-forward 구간 분할 근거가 코드에 없음 (파일:라인 미제시)"],
        "risks": ["표본 30 미만이면 p-value 신뢰 불가", "lookahead 누출 검증 테스트 부재"],
        "consensus_ready": False,
    }
    ok, err = _validate(valid_r1, schema)
    if not ok:
        print(f"SELFTEST FAIL: valid round-1 fixture rejected: {err}", file=sys.stderr)
        return 1

    invalid_r2 = dict(valid_r1, round=2)  # round 2 without feedback_addressed
    ok, err = _validate(invalid_r2, schema)
    if ok:
        print("SELFTEST FAIL: round-2 without feedback_addressed accepted", file=sys.stderr)
        return 1

    valid_r2 = dict(
        valid_r1,
        round=2,
        feedback_addressed=[
            {"to_agent": "analysis-agent", "point": "표본 60개 확보 주장", "response": "output 파일 실측 결과 58개 — 근거 보강 필요"},
            {"to_agent": "evaluator-agent", "point": "p<0.05 충족", "response": "다중비교 보정 미적용 지적 유지"},
        ],
    )
    ok, err = _validate(valid_r2, schema)
    if not ok:
        print(f"SELFTEST FAIL: valid round-2 fixture rejected: {err}", file=sys.stderr)
        return 1

    extracted = _extract_json_block("결과입니다:\n```json\n" + json.dumps(valid_r1, ensure_ascii=False) + "\n```")
    if extracted != valid_r1:
        print("SELFTEST FAIL: fenced JSON extraction mismatch", file=sys.stderr)
        return 1

    print("pr_schema_check selftest: PASS")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_run_selftest())

    if not _is_pr_active():
        sys.exit(0)

    hook_input = _parse_stdin()
    if not hook_input:
        sys.exit(0)

    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"PR schema load failed (fail open): {e}", file=sys.stderr)
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
