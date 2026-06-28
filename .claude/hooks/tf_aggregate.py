#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TF PostToolBatch hook — peer review response aggregator.

Fires after a parallel batch of Task tool calls resolves (13 peer reviewer
spawn results). Aggregates responses into `output/peer_review/<id>/aggregate.md`
with 4 fixed sections + 2 conditional sections, then injects summary into PM
context via `additionalContext`.

Sections:
  1. Consensus Matrix       (per-agent relevance/agreement/vote table)
  2. Urgency Revote         (vote distribution + mode)
  3. New Items Surfaced     (per-agent additions, grouped by file)
  4. Recommended Action     (vote-weighted priority order)
  5. Meta-Patterns          (conditional: ≥5 agents reference same file in addition)
  6. Minority Dissent       (conditional: ≥1 lone direct-relevance dissent with reason ≥50 chars)

Activation gate:
- `<repo>/output/peer_review/.active` must exist.
- File content = review session ID (subdirectory under output/peer_review/).
- Created by `agents/peer_review.py` (Phase 13-B-3), removed on completion.

Fail-open (exit 0 with no work) on:
- .active missing, schema missing, jsonschema missing, payload empty,
  no Task tool outputs, no schema-valid JSON responses.

Selftest:
    python .claude/hooks/tf_aggregate.py --selftest

Phase 13-B-2 (2026-06-28).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "peer_review_response.schema.json"
_OUTPUT_DIR = _REPO_ROOT / "output" / "peer_review"
_ACTIVE_FLAG = _OUTPUT_DIR / ".active"

_META_PATTERN_MIN_AGENTS = 5
_MINORITY_REASON_MIN_LEN = 50


# ── stdin / activation ─────────────────────────────────────────────

def _parse_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _read_active_session_id() -> str:
    try:
        return _ACTIVE_FLAG.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# ── JSON extraction ────────────────────────────────────────────────

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


def _collect_task_outputs(hook_input: dict) -> list[str]:
    """Extract text from Task tool outputs in the batch.
    Defensive: handles multiple possible payload shapes."""
    outputs: list[str] = []
    # Shape A: tool_calls = [{tool_name, tool_input, tool_output}, ...]
    for call in hook_input.get("tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        if call.get("tool_name") != "Task":
            continue
        out = call.get("tool_output", "")
        if isinstance(out, str) and out:
            outputs.append(out)
        elif isinstance(out, list):
            outputs.append("".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out))
    # Shape B: tool_outputs = [str|list, ...] parallel to tool_inputs
    if not outputs:
        inputs = hook_input.get("tool_inputs", []) or []
        results = hook_input.get("tool_outputs", []) or []
        for i, out in enumerate(results):
            inp = inputs[i] if i < len(inputs) else {}
            name = inp.get("tool_name") if isinstance(inp, dict) else None
            if name and name != "Task":
                continue
            if isinstance(out, str):
                outputs.append(out)
            elif isinstance(out, list):
                outputs.append("".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out))
            elif isinstance(out, dict):
                outputs.append(out.get("text", "") or json.dumps(out, ensure_ascii=False))
    return outputs


def _validate_response(payload: dict, schema: dict) -> bool:
    try:
        from jsonschema import Draft202012Validator
        Draft202012Validator(schema).validate(payload)
        return True
    except Exception:
        return False


# ── Section builders ───────────────────────────────────────────────

def _section_consensus_matrix(responses: list[dict]) -> str:
    lines = ["## 1. Consensus Matrix", "",
             "| Agent | Relevance | Agreement | Urgency Vote | Addition |",
             "|---|---|---|---|---|"]
    for r in responses:
        has_add = "✓" if r.get("addition") else "—"
        lines.append(
            f"| {r['agent']} | {r['domain_relevance']} | {r['agreement']} "
            f"| {r['urgency_vote']} | {has_add} |"
        )
    return "\n".join(lines) + "\n"


def _section_urgency_revote(responses: list[dict]) -> str:
    votes = Counter(r["urgency_vote"] for r in responses)
    if not votes:
        return "## 2. Urgency Revote\n\n_no votes_\n"
    mode_item, mode_count = votes.most_common(1)[0]
    lines = ["## 2. Urgency Revote", "",
             f"**Consensus most urgent**: item {mode_item} ({mode_count}/{len(responses)} votes)",
             "", "| Item | Vote Count |", "|---|---|"]
    for item, count in sorted(votes.items()):
        lines.append(f"| {item} | {count} |")
    return "\n".join(lines) + "\n"


def _section_new_items(responses: list[dict]) -> str:
    additions = [(r["agent"], r["addition"]) for r in responses if r.get("addition")]
    lines = ["## 3. New Items Surfaced", ""]
    if not additions:
        lines.append("_none_")
        return "\n".join(lines) + "\n"
    by_file: dict[str, list[tuple[str, dict]]] = {}
    for agent, add in additions:
        f = add.get("file", "<unspecified>")
        by_file.setdefault(f, []).append((agent, add))
    for f, items in sorted(by_file.items()):
        lines.append(f"### {f}")
        for agent, add in items:
            fn = add.get("function") or "—"
            lines.append(f"- **{agent}** ({fn}): {add.get('change', '')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _section_recommended_actions(responses: list[dict]) -> str:
    votes = Counter(r["urgency_vote"] for r in responses)
    lines = ["## 4. Recommended Action Order", ""]
    if not votes:
        lines.append("_no votes_")
        return "\n".join(lines) + "\n"
    for rank, (item, count) in enumerate(votes.most_common(), start=1):
        lines.append(f"{rank}. Item {item} — {count} votes")
    return "\n".join(lines) + "\n"


def _section_meta_patterns(responses: list[dict]) -> str | None:
    """Conditional: ≥5 agents reference same file in addition."""
    file_refs = Counter()
    file_to_agents: dict[str, list[str]] = {}
    for r in responses:
        add = r.get("addition")
        if not add:
            continue
        f = add.get("file")
        if not f:
            continue
        file_refs[f] += 1
        file_to_agents.setdefault(f, []).append(r["agent"])
    hot = [(f, c) for f, c in file_refs.items() if c >= _META_PATTERN_MIN_AGENTS]
    if not hot:
        return None
    lines = ["## 5. Meta-Patterns", "",
             f"_files referenced by ≥{_META_PATTERN_MIN_AGENTS} agents_", ""]
    for f, count in sorted(hot, key=lambda x: -x[1]):
        agents = ", ".join(file_to_agents[f])
        lines.append(f"- `{f}` ({count} agents: {agents})")
    return "\n".join(lines) + "\n"


def _section_minority_dissent(responses: list[dict]) -> str | None:
    """Conditional: ≥1 agent with direct relevance + disagree + reason ≥50."""
    votes = Counter(r["urgency_vote"] for r in responses)
    if not votes:
        return None
    mode_vote = votes.most_common(1)[0][0]
    dissenters = [
        r for r in responses
        if r.get("domain_relevance") == "direct"
        and r.get("urgency_vote") != mode_vote
        and len(r.get("reason", "")) >= _MINORITY_REASON_MIN_LEN
    ]
    if not dissenters:
        return None
    lines = ["## 6. Minority Dissent", "",
             f"_direct-relevance agents who voted differently from majority "
             f"(item {mode_vote}), reason ≥{_MINORITY_REASON_MIN_LEN} chars_", ""]
    for r in dissenters:
        lines.append(f"- **{r['agent']}** (vote {r['urgency_vote']}): {r['reason']}")
    return "\n".join(lines) + "\n"


def _build_aggregate(responses: list[dict]) -> str:
    parts = [
        f"# TF Peer Review Aggregate — {len(responses)} responses",
        "",
        _section_consensus_matrix(responses),
        _section_urgency_revote(responses),
        _section_new_items(responses),
        _section_recommended_actions(responses),
    ]
    meta = _section_meta_patterns(responses)
    if meta:
        parts.append(meta)
    minority = _section_minority_dissent(responses)
    if minority:
        parts.append(minority)
    return "\n".join(parts)


# ── Output ─────────────────────────────────────────────────────────

def _emit_additional_context(text: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolBatch",
            "additionalContext": text[:9500],
        }
    }
    print(json.dumps(out, ensure_ascii=False))


def _emit_exit_clean() -> None:
    sys.exit(0)


# ── Selftest ───────────────────────────────────────────────────────

def _synthetic_responses(n: int = 13) -> list[dict]:
    """Build N synthetic responses with embedded patterns:
    - 6 agents reference same file (triggers meta-pattern)
    - 1 lone direct dissenter (triggers minority report)
    """
    agents = ["data", "analysis", "evaluator", "validation", "decision",
              "stock", "sector", "news", "narrative", "ui", "report",
              "audit", "meta-audit"]
    out = []
    for i, name in enumerate(agents[:n]):
        # 6 agents reference output/pm_orchestrator.py
        addition = None
        if i < 6:
            addition = {
                "file": "agents/pm_orchestrator.py",
                "function": "_invoke_peer_review",
                "change": "add evidence verification before completion claim",
            }
        # vote: majority votes 1, one direct dissenter votes 3
        vote = 3 if i == 7 else 1
        relevance = "direct" if i < 8 else "indirect"
        out.append({
            "agent": f"{name}-agent",
            "domain_relevance": relevance,
            "agreement": "agree" if i % 3 else "partial",
            "urgency_vote": vote,
            "addition": addition,
            "reason": (
                "RSS empty case에서도 mtime이 갱신되어 false positive 발생 가능 — "
                "이는 PM의 mtime+키 검증 우회로 더 시급한 문제다 (synthetic dissent)"
            ) if i == 7 else "valid reason text here for synthetic testing purposes",
        })
    return out


def _run_selftest() -> int:
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"SELFTEST FAIL: schema load: {e}", file=sys.stderr)
        return 1

    responses = _synthetic_responses(13)
    # validate each against schema
    for r in responses:
        if not _validate_response(r, schema):
            print(f"SELFTEST FAIL: synthetic response invalid: {r}", file=sys.stderr)
            return 1

    aggregate = _build_aggregate(responses)
    required = [
        "## 1. Consensus Matrix",
        "## 2. Urgency Revote",
        "## 3. New Items Surfaced",
        "## 4. Recommended Action Order",
        "## 5. Meta-Patterns",        # 6 agents on same file → triggered
        "## 6. Minority Dissent",     # 1 lone direct dissenter → triggered
    ]
    for header in required:
        if header not in aggregate:
            print(f"SELFTEST FAIL: missing section: {header}", file=sys.stderr)
            return 1

    print("tf_aggregate selftest: PASS")
    print(f"  responses=13, sections=6 (4 fixed + 2 conditional)")
    return 0


# ── Main ───────────────────────────────────────────────────────────

def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_run_selftest())

    if not _ACTIVE_FLAG.exists():
        _emit_exit_clean()

    hook_input = _parse_stdin()
    if not hook_input:
        _emit_exit_clean()

    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception:
        _emit_exit_clean()

    outputs = _collect_task_outputs(hook_input)
    if not outputs:
        _emit_exit_clean()

    responses: list[dict] = []
    for text in outputs:
        payload = _extract_json_block(text)
        if payload is None:
            continue
        if _validate_response(payload, schema):
            responses.append(payload)

    if not responses:
        _emit_exit_clean()

    aggregate = _build_aggregate(responses)

    session_id = _read_active_session_id() or "unknown"
    out_dir = _OUTPUT_DIR / session_id
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "aggregate.md").write_text(aggregate, encoding="utf-8")
    except Exception as e:
        print(f"TF aggregate write failed (fail open): {e}", file=sys.stderr)
        _emit_exit_clean()

    summary = (
        f"TF Peer Review aggregate ready: {len(responses)} responses\n"
        f"File: output/peer_review/{session_id}/aggregate.md\n\n"
        + aggregate
    )
    _emit_additional_context(summary)
    sys.exit(0)


if __name__ == "__main__":
    main()
