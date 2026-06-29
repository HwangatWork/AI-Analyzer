# -*- coding: utf-8 -*-
"""
agent_log.py — Claude Code session jsonl 에서 Agent() 호출 추출.

Phase 13-D-1 Commit 2/2 — 사용자 visibility 권고 (옵션 B).

사용법:
    python scripts/agent_log.py                # 현재 프로젝트 최신 세션 summary
    python scripts/agent_log.py --all          # 프로젝트 모든 세션
    python scripts/agent_log.py --since 1d     # 최근 24시간 (1d/24h 지원)
    python scripts/agent_log.py --json         # raw JSON 출력
    python scripts/agent_log.py --activity     # data/agent_activity.jsonl (실측 hook log) 우선

source of truth:
- session jsonl: ~/.claude/projects/<encoded-path>/<session_id>.jsonl
- activity log: data/agent_activity.jsonl (Phase 13-D-1 hook 출력)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _encode_project_path(repo: Path) -> str:
    """C:/Users/JY Hwang/Desktop/AI Projects/AI Analyzer
    → C--Users-JY-Hwang-Desktop-AI-Projects-AI-Analyzer

    NOTE: Claude Code 가 `:` + `/` 를 각각 `-` 로 변환 → `C:/` = `C--`.
    더블 dash 유지 (collapse 금지). 공백만 단일 dash 로 정규화.
    """
    s = str(repo.resolve())
    s = s.replace(":", "-")
    s = s.replace("\\", "-").replace("/", "-")
    s = re.sub(r"\s+", "-", s)
    return s.strip("-")


def _find_project_dir(repo: Optional[Path] = None) -> Optional[Path]:
    repo = repo or Path.cwd()
    encoded = _encode_project_path(repo)
    target = PROJECTS_DIR / encoded
    if target.exists():
        return target
    # 폴백: PROJECTS_DIR 안에서 substring 매칭
    if PROJECTS_DIR.exists():
        for d in PROJECTS_DIR.iterdir():
            if d.is_dir() and encoded.endswith(d.name.lstrip("-")):
                return d
    return None


def _list_sessions(proj_dir: Path) -> list[Path]:
    if not proj_dir or not proj_dir.exists():
        return []
    return sorted(
        proj_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _parse_since(s: str) -> Optional[datetime]:
    """'1d' / '24h' / '30m' → datetime in UTC."""
    if not s:
        return None
    m = re.match(r"^(\d+)\s*([dhm]|day|hour|min)", s.lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    now = datetime.now(timezone.utc)
    if unit.startswith("d"):
        return now - timedelta(days=n)
    if unit.startswith("h"):
        return now - timedelta(hours=n)
    if unit.startswith("m"):
        return now - timedelta(minutes=n)
    return None


def parse_session(jsonl_path: Path, since: Optional[datetime] = None) -> list[dict]:
    """session jsonl 에서 Agent() 호출 추출."""
    invocations = []
    if not jsonl_path.exists():
        return invocations
    try:
        text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return invocations
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts_str = obj.get("timestamp", "")
        ts = None
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if since and ts and ts < since:
            continue
        msg = obj.get("message", {})
        content = msg.get("content", []) if isinstance(msg, dict) else []
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "tool_use" and blk.get("name") == "Agent":
                inp = blk.get("input") or {}
                invocations.append({
                    "ts": ts_str[:19],
                    "subagent_type": inp.get("subagent_type", "?"),
                    "description": (inp.get("description", "") or "")[:80],
                    "session": jsonl_path.stem,
                })
    return invocations


def parse_activity_log(activity_path: Path, since: Optional[datetime] = None) -> list[dict]:
    """data/agent_activity.jsonl 에서 hook 실측 로그 추출."""
    out = []
    if not activity_path.exists():
        return out
    try:
        text = activity_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if since:
            ts_str = obj.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < since:
                    continue
            except ValueError:
                pass
        out.append(obj)
    return out


def render_table(invocations: list[dict]) -> str:
    if not invocations:
        return "(invocations 없음)"
    rows = []
    rows.append(
        f"{'No':>3} | {'timestamp':19} | {'subagent_type':22} | description"
    )
    rows.append("-" * 100)
    for i, inv in enumerate(invocations, 1):
        rows.append(
            f"{i:>3} | {inv.get('ts','?'):19} | "
            f"{inv.get('subagent_type','?'):22} | {inv.get('description','')}"
        )
    return "\n".join(rows)


def render_counts(invocations: list[dict], key: str = "subagent_type") -> str:
    if not invocations:
        return "(counts 없음)"
    rows = ["=== {} counts ===".format(key)]
    for k, c in Counter(x.get(key, "?") for x in invocations).most_common():
        rows.append(f"  {k:22}: {c}회")
    return "\n".join(rows)


def _force_utf8_stdio() -> None:
    """Windows 기본 cp949 환경에서 한글/em-dash 출력 시 UnicodeEncodeError 차단.
    Audit 5차 CRITICAL-C1 (2026-06-30) — 사용자가 PowerShell/cmd 에서 실행 시
    `print(...)` 즉시 크래시했음 (em-dash '—' 등). 모든 main 진입에서 강제 UTF-8.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Claude Code session 의 Agent() 호출 조회")
    ap.add_argument("--all", action="store_true", help="현재 프로젝트의 모든 세션")
    ap.add_argument("--since", default="", help="필터: 1d / 24h / 30m")
    ap.add_argument("--json", action="store_true", help="raw JSON 출력")
    ap.add_argument("--activity", action="store_true",
                    help="data/agent_activity.jsonl (실측 hook 로그) 사용")
    ap.add_argument("--session", help="특정 session jsonl 절대 경로")
    args = ap.parse_args(argv)

    since = _parse_since(args.since)

    if args.activity:
        repo = Path.cwd()
        activity_path = repo / "data" / "agent_activity.jsonl"
        entries = parse_activity_log(activity_path, since=since)
        if args.json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
            return 0
        print(f"activity log: {activity_path} | entries: {len(entries)}")
        print()
        for i, e in enumerate(entries, 1):
            r = e.get("runtime_sec")
            r_s = f"{r}s" if r is not None else "?s"
            print(
                f"  {i:>3} | {e.get('ts','?')[:19]:19} | "
                f"{e.get('agent_type','?'):22} | {r_s:>6} | "
                f"{e.get('tools_count',0)} tools"
            )
        print()
        print(render_counts([{"subagent_type": e.get("agent_type", "?")} for e in entries]))
        return 0

    if args.session:
        sessions = [Path(args.session)]
    else:
        proj = _find_project_dir()
        if not proj:
            print("[error] Claude Code project session 디렉토리 찾을 수 없음", file=sys.stderr)
            return 1
        all_s = _list_sessions(proj)
        sessions = all_s if args.all else all_s[:1]

    invocations = []
    for s in sessions:
        invocations.extend(parse_session(s, since=since))

    if args.json:
        print(json.dumps(invocations, ensure_ascii=False, indent=2))
        return 0

    print(f"sessions: {len(sessions)} | invocations: {len(invocations)}")
    print()
    print(render_table(invocations))
    print()
    print(render_counts(invocations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
