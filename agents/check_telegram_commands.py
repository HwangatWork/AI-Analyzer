# -*- coding: utf-8 -*-
"""Telegram 명령어 감지 (2026-07-03 사용자 요청).

사용자가 텔레그램에 `/report`, `/status` 같은 명령을 치면
`pending_requests.json` 에 REQ-USER-* 항목 자동 등록.
다음 파이프라인 실행 시 pm-agent 가 pending 확인 → 재실행 또는 상태 응답.

지원 명령어:
    /report   — 다음 실행 시 narrative-agent 재spawn (FINAL_REPORT_v2.md 갱신)
    /status   — 현재 파이프라인 상태 텔레그램 회신 (pending count / 마지막 실행)
    /help     — 사용 가능 명령어 목록

실행 방법:
    python agents/check_telegram_commands.py                   # 최근 5 메시지 확인
    python agents/check_telegram_commands.py --lookback 20     # 최근 20 확인
    python agents/check_telegram_commands.py --selftest        # mock 자체검사

파이프라인 통합:
    pm_orchestrator 시작 시 호출 → 있으면 REQ 등록 후 진행
    또는 cron 매시간 (`0 * * * *`) 실행

⚠️ Webhook 아님. Polling 방식이라 5분~1시간 지연 있음.
즉시 응답 원하면 Cloudflare Workers webhook 별도 phase.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
PENDING_PATH = BASE_DIR / "pending_requests.json"

# 지원 명령어 → REQ ID + description
_COMMAND_MAP = {
    "/report": (
        "REQ-USER-REPORT",
        "[텔레그램 /report] 다음 파이프라인 실행 시 narrative-agent 재spawn 필요"
    ),
    "/status": (
        "REQ-USER-STATUS",
        "[텔레그램 /status] 현재 상태 응답 요청"
    ),
    "/help": (
        "REQ-USER-HELP",
        "[텔레그램 /help] 사용 가능 명령어 안내 요청"
    ),
}


def fetch_recent_updates(lookback: int = 5) -> list[dict]:
    """Telegram getUpdates 로 최근 N 개 메시지 조회.

    Returns updates list (dict). 실패 시 빈 list (advisory).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return []
    try:
        url = (
            f"https://api.telegram.org/bot{token}/getUpdates"
            f"?offset=-{lookback}&limit={lookback}"
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data.get("result", []) or []
    except Exception:
        return []


def detect_commands(updates: list[dict]) -> list[dict]:
    """updates 에서 지원 명령어 감지. 각 hit 은 dict.

    Returns:
        [{"command": "/report", "req_id": "REQ-USER-REPORT",
          "description": "...", "update_id": 123, "text": "..."}]
    """
    hits = []
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        # 첫 토큰이 명령어인 경우만 감지 (오탐 방지)
        first_token = text.split()[0].lower() if text.split() else ""
        if first_token in _COMMAND_MAP:
            req_id, desc = _COMMAND_MAP[first_token]
            hits.append({
                "command": first_token,
                "req_id": req_id,
                "description": desc,
                "update_id": upd.get("update_id"),
                "text": text[:200],
            })
    return hits


def register_pending(
    hits: list[dict],
    pending_path: Path | None = None,
) -> dict:
    """감지된 명령어를 pending_requests.json 에 등록. 중복 방지."""
    pending_path = pending_path or PENDING_PATH
    if not hits:
        return {"registered": 0, "skipped": 0, "reason": "no_hits"}

    try:
        if pending_path.exists():
            data = json.loads(pending_path.read_text(encoding="utf-8"))
        else:
            data = {"updated": "", "completed": [], "pending": []}
    except (OSError, json.JSONDecodeError):
        return {"registered": 0, "skipped": 0, "reason": "pending file read fail"}

    pending_list = data.get("pending", [])
    existing = {i.get("id"): i for i in pending_list}
    now = datetime.now().isoformat(timespec="seconds")

    registered = 0
    skipped = 0
    for hit in hits:
        req_id = hit["req_id"]
        if req_id in existing and existing[req_id].get("status") == "pending":
            skipped += 1
            continue
        pending_list.append({
            "id": req_id,
            "request": hit["description"],
            "status": "pending",
            "details": (
                f"텔레그램 명령어: {hit['command']} "
                f"(update_id={hit['update_id']}). "
                f"원문: {hit['text']}"
            ),
            "registered_at": now,
            "source": "telegram_command",
        })
        registered += 1

    if registered:
        data["pending"] = pending_list
        data["updated"] = now
        try:
            pending_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            return {"registered": 0, "skipped": skipped, "reason": f"write fail: {e}"}

    return {"registered": registered, "skipped": skipped}


def check_and_register(
    lookback: int = 5,
    pending_path: Path | None = None,
) -> dict:
    """공개 API. lookback 만큼 확인 → 명령어 감지 → pending 등록."""
    updates = fetch_recent_updates(lookback=lookback)
    hits = detect_commands(updates)
    result = register_pending(hits, pending_path=pending_path)
    result["hits"] = len(hits)
    result["fetched"] = len(updates)
    return result


def _selftest() -> int:
    """mock 명령어로 detect + register 로직 검증."""
    fake_updates = [
        {"update_id": 1, "message": {"text": "/report 지금 리포트 만들어줘"}},
        {"update_id": 2, "message": {"text": "안녕 그냥 잡담"}},
        {"update_id": 3, "message": {"text": "/status"}},
    ]
    hits = detect_commands(fake_updates)
    ok = len(hits) == 2 and hits[0]["command"] == "/report"
    print(f"selftest: detected {len(hits)} commands (expected 2) → "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Telegram 명령어 감지 + pending 등록")
    ap.add_argument("--lookback", type=int, default=5,
                    help="최근 N 개 메시지 확인 (default 5)")
    ap.add_argument("--selftest", action="store_true", help="mock 자체검사")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    result = check_and_register(lookback=args.lookback)
    print(f"[Telegram] fetched={result['fetched']} hits={result['hits']} "
          f"registered={result['registered']} skipped={result['skipped']}")
    if result.get("reason"):
        print(f"  reason: {result['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
