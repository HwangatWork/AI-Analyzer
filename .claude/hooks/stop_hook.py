# -*- coding: utf-8 -*-
"""
Claude Code Stop Hook  v5 (2026-06-12)
  1. 자가 검증 3개 체크 (Evidence / 정적분석전용 / CLAUDE.md 업데이트)
  2. 작업 완료 전체 보고 + 체크 결과 Telegram 전송 (4096자 분할)
  3. --selftest 모드: 실제 transcript 파일로 3개 체크 검증

개선 (TQ-1~TQ-5 해결):
  TQ-1: type="text" 블록만 추출 (tool_use/tool_result 제외)
  TQ-2: 섹션 1~4 완료 보고 섹션 자동 탐지 후 전송
  TQ-3: Markdown → Telegram HTML 변환 (_md_to_tg_html)
  TQ-4: 단일 통합 메시지 전송 (완료 보고 + 체크 결과)
  TQ-5: 터미널 출력 ↔ Telegram 내용 동일성 보장 (HTML 태그 제거 후 비교)

수정 이력:
  FIX-A (2026-06-11): _last_messages — 공백/개행 전용 user 메시지 truthy 버그
          (last_user="\\n" → if last_user and last_asst 조기 종료)
          → .strip() 기준으로 판단 변경
  FIX-B (2026-06-11): recent_level_ctx 스캔 — 빈 메시지 카운트 포함 버그
          → 빈 메시지 건너뜀 + 한도 20개로 상향
  FIX-C (2026-06-11): check_static_only — 한국어 '레벨'만 인식, 영어 'Level 10' SKIP 오반환
          → '(?:레벨|Level)' 패턴으로 수정
  FIX-D (2026-06-11): _last_messages — 실제 Claude Code JSONL 형식 ({type, message: {role,
          content}}) 미지원 버그. Claude Code가 hook stdin에 보내는 transcript는 각 항목이
          {"type":"user","message":{"role":"user","content":"..."}} 형식이지만
          코드가 msg.get("role","")로 최상위에서 role을 찾아 항상 ""를 반환.
          → _normalize_msg() 헬퍼로 두 가지 형식 모두 지원:
             (a) 클린 형식: {role, content} 직접 (selftest/합성 트랜스크립트)
             (b) JSONL 형식: {type, message: {role, content}, ...} (실제 Claude Code)
  FIX-E (2026-06-12): stdin JSONL 폴백 — Claude Code가 raw JSONL(1줄=1 JSON)로
          stdin을 전달하는 경우 json.loads(raw)가 JSONDecodeError를 발생시켜
          except Exception: hook_input={} 로 조용히 실패 → transcript=[] →
          Check1/Check2=SKIP, task_hint="(작업 내용 없음)".
          수정: json.loads 실패 시 줄 단위 JSONL 파싱 폴백.
          추가: stdin_debug.txt에 raw 앞 600자 덤프 (형식 확인용).
          _selftest()도 동일 JSONL 폴백 적용.

입력: JSON via stdin  {"session_id": str, "stop_hook_active": bool, "transcript": [...]}
      또는 raw JSONL (1줄=1 JSON) — FIX-E로 양형식 모두 지원
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# .claude/hooks/stop_hook.py → .claude/hooks/ → .claude/ → project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE  = BASE_DIR / ".env"

# ── 환경변수 로드 ────────────────────────────────────────────────────────────

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("\"'")
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env

# ── Telegram 분할 전송 ───────────────────────────────────────────────────────

def _tg_send(token: str, chat_id: str, text: str,
             parse_mode: str = "HTML", max_len: int = 4096) -> tuple[int, int]:
    """최대 max_len 자로 분할 전송. (성공청크, 전체청크) 반환."""
    if not token or not chat_id or not text:
        return 0, 0

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len - 40)
        if split_at < max_len // 2:
            split_at = max_len - 40
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    chunks.append(remaining)

    total   = len(chunks)
    success = 0
    for i, chunk in enumerate(chunks, 1):
        suffix = f"\n\n<i>({i}/{total})</i>" if total > 1 else ""
        payload: dict[str, str] = {
            "chat_id":                  chat_id,
            "text":                     chunk + suffix,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": "true",
        }
        try:
            safe_payload = {k: v.encode("utf-8", errors="replace").decode("utf-8")
                            for k, v in payload.items()}
            data = urllib.parse.urlencode(safe_payload).encode("utf-8")
            req  = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    success += 1
        except Exception as e:
            print(f"[STOP_HOOK] TG chunk {i}/{total} 실패: {e}", file=sys.stderr)
    return success, total

# ── TQ-1: text 블록 전용 추출 (tool_use/tool_result 제외) ────────────────────

def _extract_text_only(content) -> str:
    """Content 배열에서 type='text' 블록만 추출 — tool_use/tool_result/thinking 제외."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            block_type = b.get("type", "")
            if block_type == "text":
                parts.append(b.get("text", ""))
            elif block_type == "":  # 구버전 포맷 (type 필드 없음)
                if "text" in b:
                    parts.append(b["text"])
            # tool_use / tool_result / thinking 는 건너뜀
        return "\n".join(p for p in parts if p.strip())
    return str(content)

# ── FIX-D: JSONL / 클린 양식 정규화 ─────────────────────────────────────────

def _normalize_msg(msg: dict) -> tuple[str, str]:
    """transcript 항목에서 (role, content) 추출.

    FIX-D (2026-06-11): 실제 Claude Code가 hook stdin에 전달하는 transcript는
    각 항목이 JSONL 형식 {type, message: {role, content}, ...} 이다.

    지원 형식:
      (a) JSONL 형식 (실제 Claude Code 트랜스크립트):
          {"type": "user", "message": {"role": "user", "content": "..."}, ...}
      (b) 클린 형식 (selftest/합성 트랜스크립트):
          {"role": "user", "content": "..."}
    """
    if isinstance(msg.get("message"), dict):
        inner = msg["message"]
        return inner.get("role", ""), inner.get("content", "")
    return msg.get("role", ""), msg.get("content", "")

def _last_messages(transcript: list) -> tuple[str, str, str]:
    """(last_user_text, last_assistant_text, recent_level_ctx) 반환.
    recent_level_ctx: 최근 user 메시지 중 '레벨/Level 7+' 언급이 있는 가장 최근 것.

    FIX-A (2026-06-11): 공백/개행 전용 user 메시지를 truthy로 처리하지 않음.
    FIX-B (2026-06-11): recent_level_ctx 스캔에서 빈 메시지를 카운트 제외.
    FIX-C (2026-06-11): 영어 'Level' 및 한국어 '레벨' 모두 인식.
    FIX-D (2026-06-11): JSONL 형식 지원 — _normalize_msg() 경유.
    """
    last_user = last_asst = recent_level_ctx = ""
    for msg in reversed(transcript):
        role, content = _normalize_msg(msg)
        text = _extract_text_only(content) if isinstance(content, list) else str(content)
        if role == "assistant" and not last_asst.strip():
            last_asst = text
        elif role == "user" and not last_user.strip():
            last_user = text
        if last_user.strip() and last_asst.strip():
            break
    scanned = 0
    for msg in reversed(transcript):
        role, _ = _normalize_msg(msg)
        if role != "user":
            continue
        _, content = _normalize_msg(msg)
        text = _extract_text_only(content) if isinstance(content, list) else str(content)
        if not text.strip():
            continue
        if re.search(r"(?:레벨|Level)\s*([789]|10)", text, re.I):
            recent_level_ctx = text
            break
        scanned += 1
        if scanned >= 20:
            break
    return last_user, last_asst, recent_level_ctx

# ── FIX-E: JSONL 줄 단위 파싱 헬퍼 ──────────────────────────────────────────

def _parse_stdin(raw: str) -> tuple[dict, str]:
    """stdin raw 문자열을 파싱. (hook_input, format_tag) 반환.

    FIX-E (2026-06-12): Claude Code가 raw JSONL 형식(1줄=1 JSON)으로 stdin을
    전달하는 경우 json.loads(raw)가 JSONDecodeError를 발생시켜 hook_input={}
    로 조용히 실패한다. 폴백으로 줄 단위 JSONL 파싱을 시도한다.

    반환:
      hook_input: {"transcript": [...], ...} 형태의 dict
      format_tag: "json_object" | "jsonl" | "empty" | "error"
    """
    if not raw.strip():
        return {}, "empty"
    try:
        obj = json.loads(raw)
        return obj, "json_object"
    except json.JSONDecodeError:
        pass
    except Exception:
        return {}, "error"

    # JSONL 폴백: 줄 단위로 파싱
    entries = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if entries:
        return {"transcript": entries}, "jsonl"
    return {}, "error"

# ── TQ-2: 섹션 1~4 완료 보고 섹션 추출 ─────────────────────────────────────

def _find_completion_section(text: str) -> str:
    """완료 보고(섹션 1~4) 시작점을 찾아 해당 부분부터 반환."""
    m = re.search(r'(?m)^#{0,4}\s*섹션\s*1[\s\.:]', text)
    if m:
        return text[m.start():]
    m2 = re.search(r'(?m)^.{0,20}요청\s*vs\s*결과|^.{0,20}Request\s*vs', text)
    if m2:
        return text[m2.start():]
    m3 = re.search(r'(?m)^\|.+\|\s*$', text)
    if m3:
        start = max(0, text.rfind('\n', 0, m3.start() - 1, ) - 200)
        return text[start:]
    return text

# ── TQ-3: Markdown → Telegram HTML 변환 ──────────────────────────────────────

def _md_to_tg_html(text: str) -> str:
    """Markdown 서식 → Telegram HTML 변환."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r'(?m)^#{1,4}\s+(.+)$', r'<b>\1</b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    text = re.sub(r'(?m)^\|[-| :]+\|\s*$\n?', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _html_to_plain(html: str) -> str:
    """HTML 태그 제거 → 터미널 출력용 plain text."""
    plain = re.sub(r'<[^>]+>', '', html)
    plain = plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return plain

# ── Check 1: Evidence 키워드 확인 ────────────────────────────────────────────

_EVIDENCE_RE: list[tuple[str, str]] = [
    (r"\d+/\d+\s*PASS",                    "N/N PASS 수치"),
    (r"\[TEST\].*PASS",                    "[TEST] PASS 로그"),
    (r"exit[_\s]*(?:code)?[=:]\s*[01]",   "exit code 수치"),
    (r"동적\s*테스트.*PASS",               "동적 테스트 PASS"),
    (r"섹션\s*[1-4]",                      "보고 섹션 형식"),
    (r"L\d+:'?\w",                         "라인번호 참조"),
    (r"\d+개.*(?:PASS|완료|탐지|발견)",    "수치+결과 표현"),
    (r"Evidence.*수치|수치.*Evidence",     "Evidence 수치 언급"),
]

def check_evidence(last_asst: str) -> tuple[str, str]:
    if not last_asst.strip():
        return "SKIP", "assistant 메시지 없음"
    hits = [label for pat, label in _EVIDENCE_RE
            if re.search(pat, last_asst, re.IGNORECASE)]
    if len(hits) >= 3:
        return "PASS", f"{len(hits)}종 탐지: {', '.join(hits[:3])}"
    if hits:
        return "WARN", f"Evidence 부족 ({len(hits)}종만: {hits})"
    return "FAIL", "Evidence 없음 — 수치/로그 없이 완료 보고"

# ── Check 2: 레벨 7+ 작업에 정적 분석만 있는 경우 ────────────────────────────

_EXECUTION_RE = [
    r"python\s+[\w./]",
    r"동적\s*테스트",
    r"\[TEST\]",
    r"exit[_\s]*code\s*=",
    r"\d+/\d+\s*PASS",
    r"실행\s+(?:결과|출력|확인|완료)",
    r"=== .{1,40} ===",
]

def check_static_only(last_user: str, last_asst: str,
                      recent_level_ctx: str = "") -> tuple[str, str]:
    combined = (recent_level_ctx or "") + "\n" + last_user + "\n" + last_asst
    m = re.search(r"(?:레벨|Level)\s*([789]|10)", combined, re.I)
    if not m:
        return "SKIP", "레벨 7+ 작업 없음"
    level = m.group(1)
    has_static = bool(re.search(r"정적\s*분석|코드\s*읽기|grep으로|grep\s+실행", last_asst, re.I))
    has_exec   = any(re.search(p, last_asst, re.I) for p in _EXECUTION_RE)
    if has_static and not has_exec:
        return "WARN", f"레벨 {level} — 정적 분석 언급 있고 실행 로그 없음"
    if has_exec:
        return "PASS", f"레벨 {level} — 실행 Evidence 확인"
    return "WARN", f"레벨 {level} — 실행 Evidence 미확인 (동적 테스트/exit code 없음)"

# ── Check 3: CLAUDE.md 재발 패턴 섹션 업데이트 확인 ──────────────────────────

def _git(*args: str) -> str:
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=str(BASE_DIR),
            capture_output=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""

def check_claude_md() -> tuple[str, str]:
    try:
        diff_out = _git("diff", "HEAD", "--", "CLAUDE.md")
        if diff_out:
            added = len([l for l in diff_out.splitlines()
                         if l.startswith("+") and not l.startswith("+++")])
            return "PASS", f"CLAUDE.md 미커밋 변경 {added}줄 (이번 세션 업데이트)"
        cached_out = _git("diff", "--cached", "--", "CLAUDE.md")
        if cached_out:
            return "PASS", "CLAUDE.md 스테이징된 변경 존재"
        recent = _git("log", "--oneline", "-1", "--", "CLAUDE.md")
        if recent:
            return "WARN", f"이번 세션 변경 없음 — 최근 커밋: {recent[:55]}"
        return "WARN", "CLAUDE.md 변경 없음 — 재발 패턴 섹션 미업데이트 가능성"
    except Exception as e:
        return "WARN", f"git 확인 오류: {e}"

# ── TQ-5: 터미널 ↔ Telegram 동일성 검증 ─────────────────────────────────────

def _sync_verify(html_msg: str, terminal_text: str) -> tuple[bool, str]:
    """HTML 메시지와 터미널 plain text의 핵심 내용 동일성 확인."""
    html_plain = _html_to_plain(html_msg)
    keywords   = re.findall(r'\b(?:PASS|WARN|FAIL|SKIP)\b', html_plain)
    term_kws   = re.findall(r'\b(?:PASS|WARN|FAIL|SKIP)\b', terminal_text)
    match      = sorted(keywords) == sorted(term_kws)
    detail     = (
        f"TG={len(html_msg)}자(HTML), terminal={len(terminal_text)}자, "
        f"키워드 동일: {'YES' if match else 'NO'} "
        f"(TG={sorted(keywords)}, T={sorted(term_kws)})"
    )
    return match, detail

# ── selftest 모드 ────────────────────────────────────────────────────────────

def _selftest(transcript_file: Path) -> int:
    """--selftest: 실제 transcript 파일로 3개 체크가 의도대로 작동하는지 검증.

    FIX-E (2026-06-12): JSONL 파일(1줄=1 JSON)도 지원.
      json.loads(raw) 실패 시 줄 단위 파싱 폴백.
    """
    if not transcript_file.exists():
        print(f"[SELFTEST] 파일 없음: {transcript_file}", file=sys.stderr)
        return 1

    raw = transcript_file.read_text(encoding="utf-8")
    hook_input, fmt = _parse_stdin(raw)
    transcript = hook_input if isinstance(hook_input, list) else hook_input.get("transcript", [])
    print(f"[SELFTEST] 파일: {transcript_file.name} (형식: {fmt}, 항목: {len(transcript)}개)")

    lu, la, rc = _last_messages(transcript)
    c1_st, c1_det = check_evidence(la)
    c2_st, c2_det = check_static_only(lu, la, rc)
    task_hint = (lu[:70].replace("\n", " ").strip() or "(작업 내용 없음)")

    print(f"[SELFTEST] last_user (first 80): {lu[:80]!r}")
    print(f"[SELFTEST] recent_ctx (first 80): {rc[:80]!r}")
    print(f"[SELFTEST] task_hint: {task_hint!r}")
    print(f"[SELFTEST] Check1: {c1_st} — {c1_det}")
    print(f"[SELFTEST] Check2: {c2_st} — {c2_det}")

    fails = []
    if c2_st == "SKIP":
        fails.append("Check2=SKIP (레벨 7+ 미인식 — FIX-A/B/C/D/E 미적용)")
    if task_hint == "(작업 내용 없음)":
        fails.append("task_hint='(작업 내용 없음)' (last_user 빈 문자열)")
    if c1_st == "FAIL":
        fails.append("Check1=FAIL (Evidence 없음)")

    if fails:
        print(f"\n[SELFTEST] FAIL ({len(fails)}개 문제)")
        for f in fails:
            print(f"  - {f}")
        return 1

    print(f"\n[SELFTEST] PASS — 3개 체크 의도대로 작동")
    print(f"  Check1={c1_st}, Check2={c2_st} (not SKIP), task_hint non-empty")
    return 0


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Windows cp949 → UTF-8
    import io as _io
    if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer") and sys.stderr.encoding.lower().replace("-", "") not in ("utf8",):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    # --selftest 모드: python stop_hook.py --selftest [transcript_file]
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        default_tf = BASE_DIR / "agents" / "tests" / "selftest_transcript.json"
        tf = Path(sys.argv[2]) if len(sys.argv) >= 3 else default_tf
        sys.exit(_selftest(tf))

    # stdin 읽기 — UTF-8 명시 (Windows cp949 기본값 방지)
    raw = ""
    try:
        if hasattr(sys.stdin, "buffer"):
            raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        else:
            raw = sys.stdin.read()
    except Exception:
        raw = ""

    # FIX-E: stdin 덤프 — 실제 형식 확인용 (첫 600자)
    try:
        _debug_path = BASE_DIR / ".claude" / "hooks" / "stdin_debug.txt"
        _debug_path.write_text(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] len={len(raw)}\n"
            + (raw[:600] if raw else "(empty)"),
            encoding="utf-8"
        )
    except Exception:
        pass

    # FIX-E: JSON object 우선, JSONL 폴백
    hook_input, stdin_fmt = _parse_stdin(raw)

    # 무한루프 방지
    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    transcript                          = hook_input.get("transcript", [])
    last_user, last_asst, recent_lvl_ctx = _last_messages(transcript)
    env                  = _load_env()
    tg_token             = env.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat              = env.get("TELEGRAM_CHAT_ID", "")
    now_str              = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    ICON                 = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭"}

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ── 3개 체크 실행 ─────────────────────────────────────────────────
    c1_st, c1_det = check_evidence(last_asst)
    c2_st, c2_det = check_static_only(last_user, last_asst, recent_lvl_ctx)
    c3_st, c3_det = check_claude_md()

    warns_fails = [(s, d) for s, d in [(c1_st, c1_det), (c2_st, c2_det), (c3_st, c3_det)]
                   if s in ("WARN", "FAIL")]

    # ── TQ-2: 완료 보고 섹션 추출 ────────────────────────────────────
    completion_text = _find_completion_section(last_asst)
    if len(completion_text) > 2500:
        completion_text = completion_text[:2500] + "\n... (이하 생략)"

    # ── TQ-3: Markdown → Telegram HTML 변환 ──────────────────────────
    task_hint   = (last_user[:70].replace('\n', ' ').strip() or "(작업 내용 없음)")
    report_html = _md_to_tg_html(completion_text)

    # ── 체크 결과 HTML 섹션 ───────────────────────────────────────────
    check_html = (
        f"\n{'─'*20}\n"
        f"🔍 <b>자가 검증 체크</b>  <i>stdin:{stdin_fmt} t={len(transcript)}</i>\n\n"
        f"{ICON[c1_st]} <b>체크1 Evidence</b>: <code>{c1_st}</code>\n"
        f"   {_esc(c1_det)}\n\n"
        f"{ICON[c2_st]} <b>체크2 정적분석</b>: <code>{c2_st}</code>\n"
        f"   {_esc(c2_det)}\n\n"
        f"{ICON[c3_st]} <b>체크3 CLAUDE.md</b>: <code>{c3_st}</code>\n"
        f"   {_esc(c3_det)}"
    )
    if warns_fails:
        items     = "\n".join(f"• {ICON.get(s,'?')} {_esc(d)}" for s, d in warns_fails)
        check_html += f"\n\n⚡ <b>다음 확인 필요</b>\n{items}"
    else:
        check_html += "\n\n✅ 이슈 없음"

    # ── TQ-4: 단일 통합 메시지 빌드 ──────────────────────────────────
    combined_html = (
        f"📋 <b>작업 완료 보고</b>  <i>{now_str}</i>\n"
        f"<code>{_esc(task_hint[:60])}</code>\n\n"
        f"{report_html}"
        f"{check_html}"
    )

    # ── TQ-5: 터미널 ↔ Telegram 동일성 검증 ──────────────────────────
    terminal_text = _html_to_plain(combined_html)
    sync_ok, sync_detail = _sync_verify(combined_html, terminal_text)

    print(f"\n[STOP_HOOK] {now_str}")
    print(terminal_text[:1200])
    if len(terminal_text) > 1200:
        print(f"  ... ({len(terminal_text) - 1200}자 이하 생략)")
    print(f"\n[SYNC] {sync_detail}")
    print(f"[STOP_HOOK] stdin={stdin_fmt} transcript={len(transcript)}항목, HTML={len(combined_html)}자")

    # ── Telegram 전송 ─────────────────────────────────────────────────
    if tg_token and tg_chat:
        ok, tot = _tg_send(tg_token, tg_chat, combined_html, parse_mode="HTML")
        print(f"[STOP_HOOK] Telegram 전송: {ok}/{tot}청크 성공")
    else:
        print("[STOP_HOOK] Telegram 환경변수 없음 — 전송 생략")

    sys.exit(0)


if __name__ == "__main__":
    main()
