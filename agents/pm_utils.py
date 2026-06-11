# -*- coding: utf-8 -*-
"""
PM Agent — 공통 유틸리티 (pm_utils.py)
I/O 헬퍼, Telegram 전송, subprocess 실행.
pm_quality / pm_orchestrator / run_pm_agent 에서 공통 사용.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

BASE_DIR          = Path(__file__).parent.parent
AGENTS_DIR        = Path(__file__).parent
OUT_DIR           = BASE_DIR / "output"
PROC_DIR          = BASE_DIR / "data" / "processed"
RESULTS_FILE      = OUT_DIR / "final_results.json"
BASELINE_FILE     = PROC_DIR / "pm_baseline.json"
FIX_REQUEST_FILE  = BASE_DIR / "fix_request.md"
PENDING_FILE      = BASE_DIR / "pending_requests.json"


# ── pending_requests.json 헬퍼 ────────────────────────────────────

def _load_pending() -> dict:
    """pending_requests.json 로드. 파일 없으면 빈 구조 반환."""
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": [], "pending": []}


def _save_pending(data: dict) -> None:
    """updated 필드를 현재 시각으로 갱신 후 저장."""
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def register_pending(req_id: str, request: str, status: str = "pending",
                     details: str = "", completed_at: str | None = None) -> None:
    """
    pending_requests.json에 항목 추가 또는 갱신.
    이미 같은 id가 있으면 업데이트, 없으면 삽입.
    completed_at이 있으면 completed 배열로 이동.
    """
    data = _load_pending()
    entry: dict = {
        "id": req_id,
        "request": request,
        "status": status,
        "details": details,
    }
    if completed_at:
        entry["completed_at"] = completed_at

    target_list = "completed" if status == "done" else "pending"
    other_list  = "pending"   if status == "done" else "completed"

    data[target_list] = [e for e in data[target_list] if e["id"] != req_id]
    data[other_list]  = [e for e in data[other_list]  if e["id"] != req_id]

    data[target_list].append(entry)
    _save_pending(data)
    print(f"[PM] pending_requests 등록: {req_id} ({status})")


# ── 데이터 로드 ───────────────────────────────────────────────────

def _load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_validation() -> dict:
    vf = PROC_DIR / "validation_report.json"
    if vf.exists():
        try:
            return json.loads(vf.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_audit() -> dict:
    af = PROC_DIR / "audit_report.json"
    if af.exists():
        try:
            return json.loads(af.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── Telegram 전송 ─────────────────────────────────────────────────

# SD-9: 중복 전송 방지 — 동일 메시지 해시 60초 내 재전송 차단
_tg_last_sent: dict[str, float] = {}


def _tg_send(text: str) -> None:
    """텔레그램 메시지 전송 (run_telegram_agent 임포트 없이 직접)."""
    import hashlib
    msg_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    now = time.time()
    if now - _tg_last_sent.get(msg_hash, 0.0) < 60.0:
        print(f"  [TG] 중복 메시지 차단 (60s 이내 동일 해시)")
        return
    _tg_last_sent[msg_hash] = now
    try:
        import urllib.request
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat  = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        req  = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  [TG] 전송 실패: {e}")


def _tg_step(step: int, total: int, name: str, detail: str = "") -> None:
    filled = "█" * step + "░" * (total - step)
    pct    = round(step / total * 100)
    msg    = f"⚙ <b>[{step}/{total}] {name} 완료</b>\n<code>{filled}</code>  {pct}%"
    if detail:
        msg += f"\n{detail}"
    _tg_send(msg)
    print(f"[PM] TG 단계 보고: {step}/{total} {name}")


# ── Agent 실행 헬퍼 ───────────────────────────────────────────────

def _run(script: str, label: str, timeout: int = 600) -> tuple[bool, str]:
    """Agent 스크립트 실행 → (ok, stdout+stderr)."""
    path = AGENTS_DIR / script
    cmd  = [sys.executable, "-X", "utf8", str(path)]
    print(f"[PM] 실행: {script}")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", timeout=timeout, cwd=str(BASE_DIR)
        )
        output = (r.stdout or "") + (r.stderr or "")
        ok     = r.returncode == 0
        if not ok:
            print(f"  [FAIL] {label} exit={r.returncode}")
            print(f"  {output[-500:]}")
        else:
            print(f"  [OK] {label}")
        return ok, output
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {label} ({timeout}s)")
        return False, f"TimeoutExpired after {timeout}s"
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        return False, str(e)
