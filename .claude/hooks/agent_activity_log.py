# -*- coding: utf-8 -*-
"""
agent_activity_log.py — SubagentStop hook (visibility)

목적: subagent spawn 완료 시 한 줄 stderr 출력 + jsonl append.
- stderr: "🤖 [audit-agent] done · 47.2s · 12 tools" → 메인 터미널 즉시 가시
- file: data/agent_activity.jsonl append (영구 기록, on-demand 조회 가능)

stdin: SubagentStop hook payload (agent_type, agent_id, session_id, transcript_path)
종료 코드: 항상 0 (non-blocking). tf_schema_check 와 병행 등록.

Phase 13-D-1 (사용자 visibility 권고, 2026-06-30).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
OUT_FILE = BASE_DIR / "data" / "agent_activity.jsonl"


def _parse_stdin(raw: str) -> dict:
    """FIX-E pattern: json.loads 우선, JSONL 줄 단위 폴백."""
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


# Phase 13-D-2 (2026-07-01): runtime cap — transcript_path 가 main session 전체 jsonl
# 일 때 timestamps 첫~끝 차이가 시간 단위가 됨. 신뢰 가능한 subagent runtime 은
# 일반적으로 < 1h (3600s). 초과 시 신뢰 안 함 표시.
_RUNTIME_CAP_SEC = 3600


def _extract_metrics(hook_input: dict) -> dict | None:
    """transcript_path 에서 runtime / tools_used 추출.

    Phase 13-D-2 (2026-07-01) 진단:
    - SubagentStop hook 이 main session Stop 에서도 fire (agent_type 빈 string)
    - .* matcher 가 main + subagent 양쪽 잡음
    - agent_type 빈 → return None → main() skip (jsonl pollution 차단)
    """
    agent_type = (hook_input.get("agent_type") or
                  hook_input.get("subagent_type") or "").strip()
    if not agent_type:
        # main session Stop 이 .* matcher 에 잡힌 noise — skip
        return None

    tools = set()
    timestamps = []
    transcript_path = hook_input.get("transcript_path")
    if transcript_path:
        p = Path(transcript_path)
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = obj.get("timestamp")
                    if ts:
                        timestamps.append(ts)
                    msg = obj.get("message", obj) if isinstance(obj, dict) else {}
                    content = msg.get("content", []) if isinstance(msg, dict) else []
                    if isinstance(content, list):
                        for blk in content:
                            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                                tn = blk.get("name")
                                if tn:
                                    tools.add(tn)
            except OSError:
                pass
    runtime_sec = None
    if len(timestamps) >= 2:
        try:
            t0 = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            runtime_sec = round((t1 - t0).total_seconds(), 1)
            # transcript 가 main session 전체일 때 runtime > cap → None (신뢰 안 함)
            if runtime_sec > _RUNTIME_CAP_SEC:
                runtime_sec = None
        except (TypeError, ValueError):
            pass
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent_type": agent_type,
        "agent_id": hook_input.get("agent_id", ""),
        "session_id": hook_input.get("session_id", ""),
        "runtime_sec": runtime_sec,
        "tools_used": sorted(tools),
        "tools_count": len(tools),
    }


def _log(metrics: dict, out_file: Path = None) -> None:
    out_file = out_file or OUT_FILE
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")


def _stderr_line(metrics: dict) -> str:
    a = metrics["agent_type"]
    r = metrics.get("runtime_sec")
    t = metrics.get("tools_count", 0)
    r_s = f"{r}s" if r is not None else "?s"
    return f"🤖 [{a}] done · {r_s} · {t} tools"


def _selftest() -> int:
    fake = {
        "agent_type": "selftest-agent",
        "agent_id": "abc123",
        "session_id": "sid-selftest",
        "transcript_path": "",
    }
    m = _extract_metrics(fake)
    line = _stderr_line(m)
    ok = (
        m["agent_type"] == "selftest-agent"
        and m["tools_count"] == 0
        and "selftest-agent" in line
    )
    print(f"selftest: {ok} | line: {line}", file=sys.stderr)
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        raw = ""
    try:
        hook_input = _parse_stdin(raw)
        metrics = _extract_metrics(hook_input)
        if metrics is None:
            # main session Stop event 등 noise — silent skip
            return 0
        _log(metrics)
        print(_stderr_line(metrics), file=sys.stderr)
    except Exception as e:
        print(f"[agent_activity_log] error (non-blocking): {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
