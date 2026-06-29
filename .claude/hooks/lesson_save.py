# -*- coding: utf-8 -*-
"""
lesson_save.py — SessionEnd hook (Phase 13-B-2 DC-9)

목적: 세션 종료 시 lesson 후보를 추출해 `data/lesson_candidates.jsonl` 에 append.
다음 세션 시작 시 claude-code 가 큐를 읽고 memory_lesson_save MCP 호출 (loop closure).

stdin 입력 (FIX-E/F 패턴 준수):
  - JSON object 또는 JSONL 형태 모두 처리
  - `transcript_path` 또는 직접 transcript array 지원

탐지 마커 (정규식):
  - FIX-[A-Z]
  - lsn_[a-f0-9]+
  - Anti-Pattern / RCA / Root cause
  - 재발 / 회귀

출력 파일: `data/lesson_candidates.jsonl` — 한 줄 = 한 후보
  {"ts": ..., "session_id": ..., "marker": ..., "excerpt": ..., "msg_index": ...}

종료 코드: 항상 0 (non-blocking hook). selftest 모드는 별도.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
OUT_FILE = BASE_DIR / "data" / "lesson_candidates.jsonl"

_MARKERS = [
    (re.compile(r"\bFIX-[A-Z]\b"),               "FIX"),
    (re.compile(r"\blsn_[a-f0-9]{6,}\b"),        "lesson_id"),
    (re.compile(r"Anti-?Pattern", re.IGNORECASE), "anti_pattern"),
    (re.compile(r"\bRCA\b|Root\s*cause", re.IGNORECASE), "rca"),
    (re.compile(r"재발|회귀"),                   "regression_kr"),
]


def _parse_stdin(raw: str) -> dict:
    """FIX-E pattern: try json.loads, fallback JSONL → list."""
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    entries = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"transcript": entries} if entries else {}


def _load_transcript(hook_input: dict) -> list:
    """FIX-F: prefer transcript_path file, fallback to in-payload transcript array."""
    path = hook_input.get("transcript_path")
    if path:
        p = Path(path)
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            out = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return out
    return list(hook_input.get("transcript") or [])


def _msg_text(msg: dict) -> str:
    """Coerce arbitrary Claude Code message structure into plain text."""
    if isinstance(msg, str):
        return msg
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content") or msg.get("text") or msg.get("message")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, str):
                parts.append(blk)
            elif isinstance(blk, dict):
                t = blk.get("text") or blk.get("content") or ""
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _detect(text: str) -> list[tuple[str, str]]:
    found = []
    for pat, label in _MARKERS:
        for m in pat.finditer(text):
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 220)
            excerpt = text[start:end].replace("\n", " ").strip()
            found.append((label, excerpt[:300]))
    return found


def extract_candidates(hook_input: dict) -> list[dict]:
    """Public entry — return lesson candidate dicts (no I/O)."""
    transcript = _load_transcript(hook_input)
    session_id = hook_input.get("session_id") or hook_input.get("session") or "unknown"
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for i, msg in enumerate(transcript[-50:]):  # 마지막 50 메시지만 스캔
        text = _msg_text(msg)
        if not text:
            continue
        for marker, excerpt in _detect(text):
            out.append({
                "ts": now,
                "session_id": session_id,
                "marker": marker,
                "excerpt": excerpt,
                "msg_index": i,
            })
    return out


def write_candidates(candidates: list[dict], out_file: Path = OUT_FILE) -> int:
    if not candidates:
        return 0
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("a", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return len(candidates)


def _selftest() -> int:
    fake_input = {
        "session_id": "selftest",
        "transcript": [
            {"role": "assistant", "content": "FIX-X 패턴 발견, lsn_abc123def 저장"},
            {"role": "user", "content": "RCA 정리 필요 — 재발 방지."},
        ],
    }
    cands = extract_candidates(fake_input)
    expected = 4  # FIX-X, lsn_abc123def, RCA, 재발
    ok = len(cands) >= expected
    print(f"selftest: {len(cands)} candidates extracted (expected >= {expected}) → "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        raw = ""
    hook_input = _parse_stdin(raw)
    try:
        cands = extract_candidates(hook_input)
        n = write_candidates(cands)
        # SessionEnd 는 non-blocking — stderr 로만 보고
        if n:
            print(f"[lesson_save] {n} candidates → {OUT_FILE.name}", file=sys.stderr)
    except Exception as e:
        print(f"[lesson_save] error (non-blocking): {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
