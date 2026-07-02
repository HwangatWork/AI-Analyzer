# -*- coding: utf-8 -*-
"""Consensus Revision Tracker — Phase 14-0-A2 Static robots.txt analyzer.

Zero-network 정적 분석. 캐시된 robots.txt 파일 (fixture / config path) 을 파싱해
allow/disallow rule, User-agent 별 정책, crawl-delay 위험 감지.

Peer review consensus:
- audit Q2: robots.txt parsing + allow/deny 분기 로그
- validation Q1 (c): TTL 단위 sec, (e) PIT 정책 시점 기록
- meta-audit Q3: 정적 파일 변경 silent → SHA256 등록

사용 예:
    from tools.consensus.static_robots_analyzer import analyze_robots
    result = analyze_robots(cached_path, path_to_check="/", user_agent="*")
    # → {"allowed": True, "disallow_rules": [...], "crawl_delay": None,
    #    "risk_flags": [], "sha256": "...", "analyzed_at": "..."}

Exit codes (CLI):
    0 - analyzed
    1 - invalid args
    2 - file not found
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import robotparser


EXIT_OK = 0
EXIT_INVALID_ARGS = 1
EXIT_FILE_MISSING = 2

# 위험 rule 패턴 (문자열 매칭 heuristic)
_RISK_PATTERNS = [
    "Disallow: /",   # 전체 disallow (모든 UA)
]


def _compute_sha256(path: Path) -> str:
    """캐시 파일 SHA256 (meta-audit Q3 traceability)."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _extract_disallow_rules(text: str, target_ua: str = "*") -> list[str]:
    """target_ua 그룹의 Disallow rules 추출 (사람이 읽는 로그용)."""
    rules = []
    in_target = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("user-agent:"):
            ua = line.split(":", 1)[1].strip()
            in_target = (ua == target_ua or ua == "*")
            continue
        if in_target and line.lower().startswith("disallow:"):
            rule = line.split(":", 1)[1].strip()
            if rule:
                rules.append(rule)
    return rules


def _extract_crawl_delay(text: str, target_ua: str = "*") -> float | None:
    """crawl-delay 값 (sec, PIT 시점 단위 명시)."""
    in_target = False
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("user-agent:"):
            in_target = line.split(":", 1)[1].strip() in (target_ua, "*")
            continue
        if in_target and line.lower().startswith("crawl-delay:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
    return None


def _detect_risk_flags(text: str) -> list[str]:
    """위험 패턴 감지 (전체 disallow, sitemap 부재 등)."""
    flags = []
    # 전체 disallow with User-agent: *
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    ua_star_disallow_all = False
    ua_star = False
    for line in lines:
        low = line.lower()
        if low.startswith("user-agent:") and line.split(":", 1)[1].strip() == "*":
            ua_star = True
            continue
        if ua_star:
            if low.startswith("disallow: /") and line.strip().split(":", 1)[1].strip() == "/":
                ua_star_disallow_all = True
                break
            if low.startswith("user-agent:"):
                ua_star = False
    if ua_star_disallow_all:
        flags.append("full_disallow_for_all_ua")
    # sitemap 부재
    if not any(l.lower().startswith("sitemap:") for l in lines):
        flags.append("no_sitemap_declared")
    return flags


def analyze_robots(
    cached_path: Path,
    path_to_check: str = "/",
    user_agent: str = "*",
) -> dict[str, Any]:
    """정적 robots.txt 분석. zero-network.

    반환 스키마:
        allowed: bool (target path 접근 가능 여부)
        disallow_rules: list[str] (사람 판독용)
        crawl_delay: float | None (sec, PIT 명시)
        risk_flags: list[str] (위험 패턴)
        sha256: str (파일 fingerprint, meta-audit Q3)
        analyzed_at: str (ISO UTC)
        path_checked: str
        user_agent: str
    """
    if not cached_path.exists():
        raise FileNotFoundError(f"robots cache 부재: {cached_path}")

    text = cached_path.read_text(encoding="utf-8", errors="replace")

    parser = robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    allowed = parser.can_fetch(user_agent, "http://example.com" + path_to_check)

    return {
        "allowed": allowed,
        "disallow_rules": _extract_disallow_rules(text, user_agent),
        "crawl_delay": _extract_crawl_delay(text, user_agent),
        "risk_flags": _detect_risk_flags(text),
        "sha256": _compute_sha256(cached_path),
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path_checked": path_to_check,
        "user_agent": user_agent,
        "cached_path": str(cached_path),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Static robots.txt analyzer (Phase 14-0-A2, zero-network)"
    )
    ap.add_argument("--cached", required=True, help="robots.txt 캐시 파일 경로")
    ap.add_argument("--path", default="/", help="검사할 경로 (default /)")
    ap.add_argument("--ua", default="*", help="User-agent (default *)")
    ap.add_argument("--out", help="결과 JSON 저장 경로 (선택)")
    args = ap.parse_args(argv)

    cached = Path(args.cached)
    if not cached.exists():
        print(f"[ERROR] robots cache 부재: {cached}", file=sys.stderr)
        return EXIT_FILE_MISSING

    try:
        result = analyze_robots(cached, path_to_check=args.path, user_agent=args.ua)
    except Exception as e:
        print(f"[ERROR] 분석 실패: {e}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
