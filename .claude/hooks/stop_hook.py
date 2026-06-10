# -*- coding: utf-8 -*-
"""
Claude Code Stop Hook  v3 (2026-06-11)
  1. 자가 검증 3개 체크 (Evidence / 정적분석전용 / CLAUDE.md 업데이트)
  2. 작업 완료 전체 보고 + 체크 결과 Telegram 전송 (4096자 분할)
  3. --selftest 모드: 실제 transcript 파일로 3개 체크 검증

개선 (TQ-1~TQ-5 해결):
  TQ-1: type="text" 블록만 추출 (tool_use/tool_result 제외)
  TQ-2: 섹션 1~4 완료 보고 섹션 자동 탐지 후 전송
  TQ-3: Markdown → Telegram HTML 변환 (_md_to_tg_html)
  TQ-4: 단일 통합 메시지 전송 (완료 보고 + 체크 결과)
  TQ-5: 터미널 출력 ↔ Telegram 내용 동일성 보장 (HTML 태그 제거 후 비교)

수정 (2026-06-11 — 실전 트리거 버그 수정):
  FIX-A: _last_messages — 공백/개행 전용 user 메시지를 truthy로 처리해 루프 조기 종료하던 버그
          (last_user="\n"이 `if last_user and last_asst` 조건을 True로 통과)
          → .strip() 기준으로 판단 변경
  FIX-B: recent_level_ctx 스캔 — 빈 메시지를 카운트에 포함해 실제 task 메시지를 찾지 못하던 버그
          → 빈 메시지 건너뜀 + 한도 20개로 상향
  FIX-C: check_static_only — 한국어 '레벨'만 인식, 영어 'Level 10'에 SKIP 오반환
          → '(?:레벨|Level)' 패턴으로 수정

입력: JSON via stdin  {"session_id": str, "stop_hook_active": bool, "transcript": [...]}
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
        # 자연스러운 줄바꿈 지점 탐색
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
            # surrogate 문자 제거 후 인코딩
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
    """Content 배열에서 type='text' 블록만 추출 — tool_use/tool_result 제외."""
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
            # tool_use / tool_result 는 건너뜀
        return "\n".join(p for p in parts if p.strip())
    return str(content)

def _last_messages(transcript: list) -> tuple[str, str, str]:
    """(last_user_text, last_assistant_text, recent_level_ctx) 반환.
    recent_level_ctx: 최근 user 메시지 중 '레벨/Level 7+' 언급이 있는 가장 최근 것.

    FIX-A (2026-06-11): 공백/개행 전용 user 메시지를 truthy로 처리하지 않음.
      .strip() 기준으로 "실질 내용 있음"을 판단한다.
      수정 전: last_user="\\n"이 if last_user and last_asst 를 True로 통과 → 조기 종료
      수정 후: last_user.strip() 기준 → 빈 문자열 처럼 취급, 계속 탐색
    FIX-B (2026-06-11): recent_level_ctx 스캔에서 빈 메시지를 카운트 제외.
      수정 전: tool_result 전용 user 메시지(text="")도 카운트 → 10개 한도 초과 후 조기 종료
      수정 후: text.strip()=='' 인 메시지는 건너뜀(카운트 없음) + 한도 20개로 상향
    """
    last_user = last_asst = recent_level_ctx = ""
    for msg in reversed(transcript):
        role    = msg.get("role", "")
        content = msg.get("content", "")
        text    = _extract_text_only(content) if isinstance(content, list) else str(content)
        if role == "assistant" and not last_asst.strip():
            last_asst = text
        elif role == "user" and not last_user.strip():
            last_user = text
        # FIX-A: .strip() 기준으로 "둘 다 실질 내용 있음"을 판단
        if last_user.strip() and last_asst.strip():
            break
    # FIX-B: 최근 레벨 컨텍스트 탐색 — 빈 메시지 건너뜀, 실질 user 최대 20개
    # FIX-C: 영어 'Level' 및 한국어 '레벨' 모두 인식
    scanned = 0
    for msg in reversed(transcript):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        text    = _extract_text_only(content) if isinstance(content, list) else str(content)
        if not text.strip():
            continue  # 빈 메시지는 카운트 없이 건너뜀
        if re.search(r"(?:레벨|Level)\s*([789]|10)", text, re.I):
            recent_level_ctx = text
            break
        scanned += 1
        if scanned >= 20:
            break
    return last_user, last_asst, recent_level_ctx

# ── TQ-2: 섹션 1~4 완료 보고 섹션 추출 ─────────────────────────────────────

def _find_completion_section(text: str) -> str:
    """완료 보고(섹션 1~4) 시작점을 찾아 해당 부분부터 반환."""
    # "### 섹션 1" / "섹션 1." / "섹션1:" 패턴
    m = re.search(r'(?m)^#{0,4}\s*섹션\s*1[\s\.:]', text)
    if m:
        return text[m.start():]
    # 보고 형식 키워드로 탐색
    m2 = re.search(r'(?m)^.{0,20}요청\s*vs\s*결과|^.{0,20}Request\s*vs', text)
    if m2:
        return text[m2.start():]
    # 표 형식 (| 항목 | 상태 |)이 처음 나오는 줄
    m3 = re.search(r'(?m)^\|.+\|\s*$', text)
    if m3:
        # 그 줄의 10줄 전부터
        start = max(0, text.rfind('\n', 0, m3.start() - 1, ) - 200)
        return text[start:]
    return text

# ── TQ-3: Markdown → Telegram HTML 변환 ──────────────────────────────────────

def _md_to_tg_html(text: str) -> str:
    """Markdown 서식 → Telegram HTML 변환."""
    # 1. HTML 이스케이프
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 2. ### Header → <b>Header</b>
    text = re.sub(r'(?m)^#{1,4}\s+(.+)$', r'<b>\1</b>', text)
    # 3. **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    # 4. `code` → <code>code</code>
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    # 5. 마크다운 테이블 구분선 제거 (|---|---|)
    text = re.sub(r'(?m)^\|[-| :]+\|\s*$\n?', '', text)
    # 6. 연속 빈줄 3개 이상 → 2개
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _html_to_plain(html: str) -> str:
    """HTML 태그 제거 → 터미널 출력용 plain text."""
    # 태그 제거
    plain = re.sub(r'<[^>]+>', '', html)
    # HTML 엔티티 복원
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
    # FIX-C (2026-06-11): 영어 'Level' 및 한국어 '레벨' 모두 인식
    # 수정 전: r"레벨\s*([789]|10)" — 영어 'Level 10' 미인식 → SKIP 오반환
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
    # 실행 Evidence 미확인 — 정적/실행 모두 미탐지 → 확인 불가 WARN
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
    # 태그 제거 후 핵심 키워드 비교
    html_plain = _html_to_plain(html_msg)
    # 체크 결과 키워드 (PASS/WARN/FAIL/SKIP) 위치 비교
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

    통과 기준 (FIX-A/B/C 적용 후):
      - Check2: SKIP이 아닌 WARN 또는 PASS (레벨 7+ 인식)
      - task_hint: '(작업 내용 없음)' 아닌 실제 내용 포함
      - Check1: PASS 또는 WARN (FAIL은 허용 안 함)

    수정 전 selftest_transcript.json 사용 시 재현되던 실패:
      (a) Check2=SKIP — 마지막 user 메시지가 "\\n" 이고 영어 'Level 10' 미인식
      (b) task_hint='(작업 내용 없음)' — last_user="\\n".strip()="" 로 빈 task_hint
    """
    if not transcript_file.exists():
        print(f"[SELFTEST] 파일 없음: {transcript_file}", file=sys.stderr)
        return 1

    raw = transcript_file.read_text(encoding="utf-8")
    data = json.loads(raw)
    transcript = data if isinstance(data, list) else data.get("transcript", [])

    lu, la, rc = _last_messages(transcript)
    c1_st, c1_det = check_evidence(la)
    c2_st, c2_det = check_static_only(lu, la, rc)
    task_hint = (lu[:70].replace("\n", " ").strip() or "(작업 내용 없음)")

    print(f"[SELFTEST] 파일: {transcript_file.name}")
    print(f"[SELFTEST] last_user (first 80): {lu[:80]!r}")
    print(f"[SELFTEST] recent_ctx (first 80): {rc[:80]!r}")
    print(f"[SELFTEST] task_hint: {task_hint!r}")
    print(f"[SELFTEST] Check1: {c1_st} — {c1_det}")
    print(f"[SELFTEST] Check2: {c2_st} — {c2_det}")

    fails = []
    if c2_st == "SKIP":
        fails.append("Check2=SKIP (레벨 7+ 미인식 — FIX-A/B/C 미적용)")
    if task_hint == "(작업 내용 없음)":
        fails.append("task_hint='(작업 내용 없음)' (last_user 빈 문자열 — FIX-A 미적용)")
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
    try:
        if hasattr(sys.stdin, "buffer"):
            raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        else:
            raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_input = {}

    # 무한루프 방지
    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    transcript                          = hook_input.get("transcript", [])
    last_user, last_asst, recent_lvl_ctx = _last_messages(transcript)  # TQ-1: type=text only
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
    # 2500자 제한 + 생략 표시
    if len(completion_text) > 2500:
        completion_text = completion_text[:2500] + "\n... (이하 생략)"

    # ── TQ-3: Markdown → Telegram HTML 변환 ──────────────────────────
    task_hint   = (last_user[:70].replace('\n', ' ').strip() or "(작업 내용 없음)")
    report_html = _md_to_tg_html(completion_text)

    # ── 체크 결과 HTML 섹션 ───────────────────────────────────────────
    check_html = (
        f"\n{'─'*20}\n"
        f"🔍 <b>자가 검증 체크</b>\n\n"
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

    # 터미널 출력 (HTML 태그 없이)
    print(f"\n[STOP_HOOK] {now_str}")
    print(terminal_text[:1200])   # 터미널은 최대 1200자 미리보기
    if len(terminal_text) > 1200:
        print(f"  ... ({len(terminal_text) - 1200}자 이하 생략)")
    print(f"\n[SYNC] {sync_detail}")
    print(f"[STOP_HOOK] HTML={len(combined_html)}자, TG분할기준={4096}자")

    # ── Telegram 전송 (단일 통합 메시지) ─────────────────────────────
    if tg_token and tg_chat:
        ok, tot = _tg_send(tg_token, tg_chat, combined_html, parse_mode="HTML")
        print(f"[STOP_HOOK] Telegram 전송: {ok}/{tot}청크 성공")
    else:
        print("[STOP_HOOK] Telegram 환경변수 없음 — 전송 생략")

    sys.exit(0)


if __name__ == "__main__":
    main()
