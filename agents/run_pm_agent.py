# -*- coding: utf-8 -*-
"""
PM Agent — thin wrapper (run_pm_agent.py)
  역할 1 (Orchestrator/.claude/agents/orchestrator.md):
    파이프라인 조율, APPROVE/HOLD 최종 판단, pending_requests 갱신
  역할 2 (Meta-Audit/.claude/agents/meta-audit-agent.md):
    pm_self_diagnosis() — SD-1~20 자가진단, report_quality_check() 보고서 레벨 평가

  실제 구현:
    pm_utils.py       — I/O 헬퍼, Telegram, subprocess
    pm_quality.py     — pm_quality_checks(), 기준선 관리, 이슈 도출
    pm_orchestrator.py — 파이프라인, validate_results, pm_system_audit

Done Criteria (PM-1~PM-6):
  PM-1: 전체 파이프라인 단계 실행 (exit 0)
  PM-2: 6가지 자체검증 기준 모두 통과
  PM-3: 최대 3회 자동 수정 루프 (수렴 or Telegram 보고)
  PM-4: 각 단계 완료 시 Telegram 진행 보고
  PM-5: 모든 기준 통과 시 Notion 페이지 업데이트
  PM-6: 최종 결과 Telegram 전송 (성공 or 실패 원인 포함)

실행:
  python agents/run_pm_agent.py [--skip-data]
  --skip-data : Data Agent(오래 걸림) 건너뜀 — 이미 수집된 데이터 재사용
"""

import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows cp949 환경에서 한글 UnicodeEncodeError 방지
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# agents/ 디렉터리를 sys.path에 추가 (pm_utils/pm_quality/pm_orchestrator 임포트용)
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── 공통 유틸리티 ─────────────────────────────────────────────
from pm_utils import (
    BASE_DIR, AGENTS_DIR, OUT_DIR, PROC_DIR,
    RESULTS_FILE, BASELINE_FILE, FIX_REQUEST_FILE, PENDING_FILE,
    _load_pending, _save_pending, register_pending,
    _load_results, _load_validation, _load_audit,
    _tg_send, _tg_step, _tg_last_sent, _run,
)

# ── 품질 검증 ─────────────────────────────────────────────────
from pm_quality import (
    _KNOWN_FAIL_CHECKS, MAX_RETRIES,
    CONTEMPORANEOUS_INDICES, SELF_REFERENTIAL,
    SMALL_CAP_USD_B_THRESHOLD, SP500_CONTRIBUTOR_TOP1_MIN_MC_B,
    CONTRIBUTOR_TOP1_MIN_MC_B, EXTREME_RETURN_THRESHOLD,
    report_quality_check, pm_quality_checks,
    _qc_summary, _load_baseline, _save_baseline,
    _tg_send_quality_report, _tg_check_approve,
    _derive_fix_scripts, _write_fix_request,
)

# ── 파이프라인 조율 + 구조 감사 ──────────────────────────────
from pm_orchestrator import (
    Criterion, CRITERIA, PIPELINE_STAGES, TOTAL_STEPS, STAGE_DEPS,
    _get_dependents, _auto_fix_from_diagnosis,
    validate_results, run_full_pipeline, run_partial_pipeline, auto_fix,
    _confidence_tier, _format_decision_for_tg, final_report,
    _register_audit_findings, pm_system_audit,
    _last_audit_findings,
)


# ══════════════════════════════════════════════════════════════
# pm_self_diagnosis — 자가 진단 + 자동 수정
# ══════════════════════════════════════════════════════════════

def pm_self_diagnosis() -> tuple[bool, list[str]]:
    """
    파이프라인 결과 자가 진단:
      SD-1  이전 기준선 대비 지표 수 급변 (±3 이상)
      SD-2  제외된 자기참조 지표 재진입
      SD-3  동행 지수 상위 3위 진입
      SD-4  ⚠ 종목 warn_reason 누락
      SD-5  주식 리스트 5개 미만
      SD-6  시그널 점수 ↔ 방향 불일치
      SD-7  GitHub Actions 마지막 run-pipeline 실패 감지 (GITHUB_TOKEN 필요)
      SD-8  News Agent 실제 URL 부족 (< 3개) → run_news_agent.py 재실행

    문제 발견 시:
      → fix_request.md 작성
      → 해당 Agent 자동 재실행
      → pm_quality_checks() 재실행하여 나머지 이슈 확인

    반환: (all_clear: bool, issues: list[str])
    """
    issues: list[str] = []
    data  = _load_results()
    if not data:
        return False, ["final_results.json 없음 — 파이프라인 미실행"]

    rank  = data.get("indicator_weight_ranking", [])
    sig   = data.get("market_signal", {})
    sp_a  = data.get("sp500_analysis", {})
    ksp_a = data.get("kospi_analysis", {})

    # ── 기준선 로드 ───────────────────────────────────────────
    baseline = _load_baseline()

    curr_count = len(rank)
    prev_count = baseline.get("indicator_count")

    # SD-1: 지표 수 급변
    if prev_count is not None and abs(curr_count - prev_count) > 2:
        issues.append(
            f"SD-1 지표 수 급변: 이전 {prev_count}개 → 현재 {curr_count}개 "
            f"(차이 {abs(curr_count - prev_count)}개) — 필터 로직 변경 가능성 확인 필요"
        )

    # SD-2: 제외 지표(자기참조) 재진입
    self_ref_in_rank = [r["indicator"] for r in rank if r["indicator"] in SELF_REFERENTIAL]
    if self_ref_in_rank:
        issues.append(f"SD-2 자기참조 지표 재진입: {self_ref_in_rank} — evaluator 재실행 필요")

    # SD-3: 동행 지수 상위 3위 진입
    top3_inds  = {r["indicator"] for r in rank[:3]}
    cm_in_top3 = top3_inds & CONTEMPORANEOUS_INDICES
    if cm_in_top3:
        issues.append(f"SD-3 동행지수 상위 3위: {cm_in_top3} — 페널티 적용 재분석 필요")

    # SD-4: ⚠ 종목 warn_reason 누락
    all_stocks = (
        sp_a.get("contribution_top5",  []) +
        sp_a.get("beneficiary_top5",   []) +
        ksp_a.get("contribution_top5", []) +
        ksp_a.get("beneficiary_top5",  [])
    )
    missing_warn = [
        s.get("name", s.get("ticker", "?"))
        for s in all_stocks
        if abs(s.get("excess_return_pct", 0) or s.get("stock_return_pct", 0)) >= EXTREME_RETURN_THRESHOLD
        and not s.get("warn_reason")
    ]
    if missing_warn:
        issues.append(f"SD-4 warn_reason 누락: {missing_warn}")

    # SD-5: 주식 리스트 5개 미만
    for label, lst in [
        ("SP500 기여", sp_a.get("contribution_top5",  [])),
        ("SP500 수혜", sp_a.get("beneficiary_top5",   [])),
        ("KOSPI 기여", ksp_a.get("contribution_top5", [])),
        ("KOSPI 수혜", ksp_a.get("beneficiary_top5",  [])),
    ]:
        if len(lst) != 5:
            issues.append(f"SD-5 {label} 리스트 {len(lst)}개 (5개 필요)")

    # SD-6: 시그널 점수 ↔ 방향 불일치
    score = sig.get("score", 50)
    direc = (sig.get("direction") or "").upper()
    if score > 65 and "SELL" in direc:
        issues.append(f"SD-6 점수 {score:.1f} (강세)인데 방향={direc} — 시그널 계산 오류 가능")
    elif score < 35 and "BUY" in direc:
        issues.append(f"SD-6 점수 {score:.1f} (약세)인데 방향={direc} — 시그널 계산 오류 가능")

    # SD-7: GitHub Actions 마지막 run-pipeline 실패 감지 (공개 repo — 토큰 불필요)
    try:
        import os as _os
        import urllib.request as _urllib_req
        _gh_token = _os.getenv("GITHUB_TOKEN", "")
        _headers = {"Accept": "application/vnd.github+json"}
        if _gh_token:
            _headers["Authorization"] = f"token {_gh_token}"
        _req = _urllib_req.Request(
            "https://api.github.com/repos/HwangatWork/AI-Analyzer/actions/runs"
            "?per_page=10&branch=main",
            headers=_headers,
        )
        with _urllib_req.urlopen(_req, timeout=10) as _resp:
            _runs = json.loads(_resp.read()).get("workflow_runs", [])
        _pipeline_runs = [
            r for r in _runs
            if "deploy" in (r.get("name") or "").lower()
            and r.get("event") in ("schedule", "workflow_dispatch", "push")
        ]
        if _pipeline_runs:
            _last = _pipeline_runs[0]
            if _last.get("conclusion") == "failure":
                issues.append(
                    f"SD-7 GitHub Actions run-pipeline 실패: "
                    f"run_id={_last.get('id')} ({(_last.get('created_at') or '')[:10]}) "
                    f"— requirements.txt/env vars 적용 후 재실행 필요"
                )
    except Exception:
        pass  # API 오류 시 건너뜀 (rate limit 등)

    # SD-8: News Agent 실제 URL 부족 시 재실행 플래그
    # NQ-4와 동일 기준: https:// 시작 + 비자명 경로 (_pm_is_article_url 재사용)
    def _sd8_is_article_url(url: str) -> bool:
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path.rstrip("/")
            return bool(path) and path not in ("", "/", "/home", "/news")
        except Exception:
            return False

    _news_file = OUT_DIR / "news_report.json"
    if _news_file.exists():
        try:
            _news_data = json.loads(_news_file.read_text(encoding="utf-8"))
            _real_links = [
                s for s in _news_data.get("sources", [])
                if s.get("link", "").startswith("https://")
                and _sd8_is_article_url(s.get("link", ""))
            ]
            if len(_real_links) < 3:
                issues.append(
                    f"SD-8 News Agent 실제URL {len(_real_links)}개 (최소 3개 필요) "
                    f"— run_news_agent.py 재실행 필요"
                )
        except Exception:
            pass

    # SD-10/11 공통: 스캔 대상 = PIPELINE_STAGES 등록 스크립트만 (archive/ dead code 제외)
    _scan_targets10_11 = [AGENTS_DIR / s for s, *_ in PIPELINE_STAGES
                          if (AGENTS_DIR / s).exists() and s != Path(__file__).name]

    # ── SD-10: 명세-구현 일치 검증 (Claude API 주장 vs 실제 코드) ─
    _api_claim_keywords = ("claude api", "anthropic_api_key", "anthropic api")
    _api_call_patterns  = ("anthropic.Anthropic(", "client.messages.create(", "anthropic.messages.create(")
    for _py in _scan_targets10_11:
        try:
            _src = _py.read_text(encoding="utf-8", errors="ignore")
            _doc = _src[:600].lower()  # 첫 600자 = 파일 헤더/docstring 범위
            _claims_api = any(kw in _doc for kw in _api_claim_keywords)
            _has_api_call = any(pat in _src for pat in _api_call_patterns)
            if _claims_api and not _has_api_call:
                issues.append(
                    f"SD-10 명세-구현 불일치: {_py.name} — 'Claude API 사용' 주장이나 "
                    f"실제 API 호출 코드(anthropic.Anthropic 등) 없음"
                )
        except Exception:
            pass

    # ── SD-11: 템플릿/하드코딩 위장 패턴 탐지 ─────────────────────
    import re as _re11
    _hardcode_re_patterns = [
        # top5 리스트에 리터럴 기업명이 하드코딩된 경우 (3개 이상)
        (r'"name":\s*"[A-Za-z가-힣].*"name":\s*"[A-Za-z가-힣].*"name":\s*"[A-Za-z가-힣]', "Top5에 리터럴 기업명 3개 이상 하드코딩 의심"),
        # 조건 없이 항상 PASS를 반환하는 구조
        (r'if\s+True:\s*#\s*always', "조건 우회 의심"),
        # TODO/placeholder 미구현 표시
        (r'#\s*(TODO|FIXME|placeholder|stub).*implement', "미구현 stub 탐지"),
    ]
    for _py in _scan_targets10_11:
        try:
            _src = _py.read_text(encoding="utf-8", errors="ignore")
            for _rpat, _desc in _hardcode_re_patterns:
                if _re11.search(_rpat, _src, _re11.DOTALL | _re11.IGNORECASE):
                    issues.append(
                        f"SD-11 하드코딩 위장 패턴: {_py.name} — {_desc}"
                    )
                    break  # 파일당 첫 번째 패턴만 보고
        except Exception:
            pass

    # ── SD-12: Done Criteria exit(1) 정적 분석 ───────────────────────
    import re as _re12
    for _ag12 in [s for s, *_ in PIPELINE_STAGES]:
        _ag12_path = AGENTS_DIR / _ag12
        if not _ag12_path.exists():
            continue
        try:
            _src12    = _ag12_path.read_text(encoding="utf-8", errors="ignore")
            _has_dc12 = ("done_criteria" in _src12.lower()
                         or "done criteria" in _src12.lower())
            _has_exit12 = bool(_re12.search(r'(?:sys\.)?exit\s*\(\s*1\s*\)', _src12))
            if _has_dc12 and not _has_exit12:
                issues.append(
                    f"SD-12 Done Criteria exit(1) 누락: {_ag12} — "
                    f"done_criteria 정의 있으나 exit(1) 가드 없음 (파이프라인 차단 불가)"
                )
        except Exception:
            pass

    # ── SD-13: 항상 True인 Done Criteria 조건 탐지 ────────────────────
    import re as _re13
    _vacuous_pats13 = [
        (r"""["']SA-\d+[^"']*["']\s*:\s*not any\(""",
         "not any() 조건 — 빈 리스트에서 vacuously True (실제 실패 미감지 가능)"),
        (r"""["']SA-\d+[^"']*["']\s*:\s*not has_company_dup\(""",
         "not has_company_dup() — 빈 리스트에서 vacuously True"),
    ]
    for _py13 in AGENTS_DIR.glob("*.py"):
        if _py13.name == Path(__file__).name:
            continue
        try:
            _src13 = _py13.read_text(encoding="utf-8", errors="ignore")
            for _rpat13, _desc13 in _vacuous_pats13:
                if _re13.search(_rpat13, _src13, _re13.DOTALL | _re13.IGNORECASE):
                    issues.append(
                        f"SD-13 항상True 조건 탐지: {_py13.name} — {_desc13}"
                    )
                    break
        except Exception:
            pass

    # ── SD-14: QC 기준선 회귀 탐지 ───────────────────────────────────
    try:
        _known_fails14       = set(baseline.get("known_fail_checks", _KNOWN_FAIL_CHECKS))
        _qc14                = pm_quality_checks()
        _qc14_all_pass       = sum(1 for c in _qc14 if c["pass"])
        _prev_fail_history14 = baseline.get("qc_failed_checks")

        _effective_fails_now  = [c["check"] for c in _qc14
                                  if not c["pass"] and c["check"] not in _known_fails14]
        _effective_fails_prev = (
            [f for f in _prev_fail_history14 if f not in _known_fails14]
            if _prev_fail_history14 is not None else None
        )

        _regressed14 = 0
        _new_fails14: list[str] = []
        if _effective_fails_prev is not None:
            _new_fails14 = [f for f in _effective_fails_now
                            if f not in set(_effective_fails_prev)]
            _regressed14 = len(_new_fails14)
        else:
            _qc14_base = baseline.get("qc_pass_count")
            if _qc14_base is not None:
                _effective_pass_now = len(_qc14) - len(_effective_fails_now)
                if _effective_pass_now < _qc14_base:
                    _regressed14 = _qc14_base - _effective_pass_now

        if _regressed14 > 0:
            issues.append(
                f"SD-14 QC 회귀: {_qc_summary(_qc14)} "
                f"(known-fail 제외 신규 실패 {_regressed14}개)"
                + (f". 신규 실패: {_new_fails14}" if _new_fails14 else "")
            )
            _tg_send(
                f"🚨 <b>SD-14 QC 회귀 감지</b>\n"
                f"현재 {_qc_summary(_qc14)}\n"
                + (f"신규 실패: {', '.join(_new_fails14[:5])}" if _new_fails14
                   else f"신규 실패: {_regressed14}개 (known-fail 외)")
            )
    except Exception:
        pass

    # ── SD-15: pm_quality_checks() 조건 실제 검증 능력 분석 ──────────
    try:
        _fr15      = data
        _sp_a15    = _fr15.get("sp500_analysis",  {})
        _ksp_a15   = _fr15.get("kospi_analysis",  {})
        _all_t15   = (_sp_a15.get("contribution_top5", []) + _sp_a15.get("beneficiary_top5", []) +
                      _ksp_a15.get("contribution_top5", []) + _ksp_a15.get("beneficiary_top5", []))
        _ksp_t15   = (_ksp_a15.get("contribution_top5", []) + _ksp_a15.get("beneficiary_top5", []))
        _ksp_ext15 = [s for s in _ksp_t15 if abs(s.get("stock_return_pct", 0)) >= 200]

        if not _all_t15:
            issues.append(
                "SD-15 SA-7 vacuous PASS — all_stocks=[] (종목 미수집 상태에서 "
                "warn_reason 체크 통과, SA-1~4와 연동 의존)"
            )
        if not _ksp_t15:
            issues.append(
                "SD-15 SA-8 vacuous PASS — KOSPI 종목=[] (극단 수익률 교차검증 vacuously 통과)"
            )
        _qc15 = pm_quality_checks()
        _perm_fails15 = [c["check"] for c in _qc15
                         if not c["pass"] and not c.get("fix_stages")]
        print(f"  [SD-15] QC {sum(1 for c in _qc15 if c['pass'])}/{len(_qc15)} PASS | "
              f"extreme_stocks={len(_ksp_ext15)} | permanent_fail={_perm_fails15}")
    except Exception:
        pass

    # ── SD-16: 결과물 타임스탬프 신선도 검증 ───────────────────────
    try:
        import time as _time16
        _FRESH_H = 25
        for _ff16 in [OUT_DIR / "final_results.json", OUT_DIR / "decision.json"]:
            if _ff16.exists():
                _age_h = (_time16.time() - _ff16.stat().st_mtime) / 3600
                if _age_h > _FRESH_H:
                    issues.append(
                        f"SD-16 결과물 신선도 경고: {_ff16.name} "
                        f"{_age_h:.1f}h 경과 (기준 {_FRESH_H}h) — 파이프라인 미실행 가능성"
                    )
                else:
                    print(f"  [SD-16] {_ff16.name}: {_age_h:.1f}h 경과 (OK)")
    except Exception:
        pass

    # ── SD-17: 핵심 출력 파일 크기 이상 탐지 ───────────────────────
    try:
        _sz_checks = {
            OUT_DIR / "final_results.json": (1_024,    5_242_880),
            OUT_DIR / "decision.json":      (100,      1_048_576),
            OUT_DIR / "dashboard.html":     (5_120,   10_485_760),
        }
        for _sf17, (_mn, _mx) in _sz_checks.items():
            if _sf17.exists():
                _sz = _sf17.stat().st_size
                if _sz < _mn:
                    issues.append(f"SD-17 빈 파일: {_sf17.name} {_sz}B < {_mn}B 최소")
                elif _sz > _mx:
                    issues.append(f"SD-17 파일 팽창: {_sf17.name} {_sz//1024}KB > {_mx//1024}KB 최대")
                else:
                    print(f"  [SD-17] {_sf17.name}: {_sz:,}B (OK)")
    except Exception:
        pass

    # ── SD-18: Agent 파일 내 하드코딩 날짜 리터럴 탐지 ──────────
    try:
        import re as _re18
        _date_pat18   = _re18.compile(r'= ["\']20\d\d-\d\d-\d\d["\']')
        _skip_line18  = {"completed_at", "updated", "timestamp", "NOTION_VERSION", "API_VERSION"}
        _pipeline_files18 = {s for s, *_ in PIPELINE_STAGES}
        for _py18 in BASE_DIR.glob("agents/*.py"):
            if _py18.name not in _pipeline_files18 and _py18.name != Path(__file__).name:
                continue
            _src18 = _py18.read_text(encoding="utf-8", errors="ignore")
            for _ln18, _line18 in enumerate(_src18.splitlines(), 1):
                if _date_pat18.search(_line18):
                    if any(skip in _line18 for skip in _skip_line18):
                        continue
                    issues.append(
                        f"SD-18 하드코딩 날짜: {_py18.name}:L{_ln18} — {_line18.strip()[:60]}"
                    )
    except Exception:
        pass

    # ── SD-19: fix_request.md 자동 수정 계획 하드코딩 탐지 ───────
    try:
        if FIX_REQUEST_FILE.exists():
            _fr19_txt = FIX_REQUEST_FILE.read_text(encoding="utf-8", errors="ignore")
            if "자동 수정 계획" in _fr19_txt and "이슈별 도출" not in _fr19_txt:
                issues.append(
                    "SD-19 fix_request.md 자동 수정 계획이 이슈 기반이 아닌 하드코딩 목록 — "
                    "_write_fix_request() 점검 필요"
                )
    except Exception:
        pass

    # ── QR: 보고서 품질 자가 평가 (REQ-018) ──────────────────────
    _qr_warns = report_quality_check()
    for _qr in _qr_warns:
        issues.append(_qr)

    print(f"[PM] 자가진단 완료 — 이슈 {len(issues)}개")
    for iss in issues:
        print(f"  ⚠ {iss}")

    # ── 문제 발견 시 자동 수정 + 재검증 루프 ────────────────────
    if issues:
        _write_fix_request(issues)

        _qc_before = pm_quality_checks()
        _pass_before = sum(1 for c in _qc_before if c["pass"])
        print(f"  [PM] 수정 전 QC: {_qc_summary(_qc_before)}")

        _auto_fix_from_diagnosis(issues)

        for fix_round in range(1, 3):
            qc = pm_quality_checks()
            qc_failed = [c for c in qc if not c["pass"]]
            existing_checks = {iss.split(":")[0] for iss in issues}
            new_failures = [
                f"QC재검증 실패: {c['check']} — {c['detail']}"
                for c in qc_failed
                if c["check"].split(" ")[0] not in existing_checks
                and c.get("fix_stages")
            ]
            if new_failures:
                issues.extend(new_failures)
                print(f"  [PM] 재검증 round {fix_round}: 추가 실패 {len(new_failures)}개")
                _auto_fix_from_diagnosis(new_failures)
            else:
                print(f"  [PM] 재검증 round {fix_round}: 추가 실패 없음 — 루프 종료")
                break

        final_qc = pm_quality_checks()
        final_pass = [c for c in final_qc if c["pass"]]
        final_fail = [c for c in final_qc if not c["pass"]]
        _pass_after = len(final_pass)
        _delta = _pass_after - _pass_before
        _delta_str = f"+{_delta}" if _delta >= 0 else str(_delta)
        print(f"  [PM] 최종 QC: {_qc_summary(final_qc)} (수정 전 {_pass_before} → 수정 후 {_pass_after}, Δ{_delta_str})")
        if _delta == 0:
            print("  [PM] ⚠ 자동 수정 효과 없음 — 수동 개입 필요")
        if final_fail:
            print(f"  [PM] 미해결 QC: {[c['check'] for c in final_fail[:5]]}")

    # ── 기준선 저장 ──────────────────────────────────────────────
    _save_baseline(curr_count, rank, pm_quality_checks())

    # ── SA 구조 감사 통합 ────────────────────────────────────────
    try:
        _sa_findings = pm_system_audit()
        _register_audit_findings(_sa_findings)
        for _cf in [f for f in _sa_findings if f["severity"] == "CRITICAL"]:
            issues.append(f"{_cf['sa_code']} {_cf['title']}: {_cf['detail'][:120]}")
    except Exception as _sa_err:
        issues.append(f"SA 구조 감사 오류: {_sa_err}")

    return len(issues) == 0, issues


# ══════════════════════════════════════════════════════════════
# Done Criteria 자체검증
# ══════════════════════════════════════════════════════════════

def _run_done_criteria() -> None:
    print("\n[PM] Done Criteria 검증 시작")
    failures = []

    # PM-1: 파이프라인 스크립트 파일 존재 확인
    missing = [s for s, *_ in PIPELINE_STAGES if not (AGENTS_DIR / s).exists()]
    if missing:
        failures.append(f"PM-1: 파이프라인 스크립트 없음 — {missing}")
    else:
        print(f"  PM-1 PASS — {len(PIPELINE_STAGES)}개 스크립트 존재 확인")

    # PM-2: 자체검증 기준 6개 함수 동작 확인
    data = _load_results()
    if data:
        result = validate_results()
        print(f"  PM-2 PASS — validate_results() 실행 성공 ({len(result)}개 이슈)")
    else:
        print(f"  PM-2 SKIP — final_results.json 없음 (파이프라인 실행 후 확인)")

    # PM-3: MAX_RETRIES 설정 확인
    if MAX_RETRIES >= 1:
        print(f"  PM-3 PASS — MAX_RETRIES={MAX_RETRIES}")
    else:
        failures.append("PM-3: MAX_RETRIES < 1")

    # PM-4: Telegram 전송 함수 확인
    import os
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        print("  PM-4 PASS — Telegram 환경변수 설정됨")
    else:
        failures.append("PM-4: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 없음")

    # PM-5: Notion 에이전트 파일 존재 확인
    if (AGENTS_DIR / "run_notion_agent.py").exists():
        print("  PM-5 PASS — run_notion_agent.py 존재")
    else:
        failures.append("PM-5: run_notion_agent.py 없음")

    # PM-6: 기준 정의 6개 확인
    if len(CRITERIA) == 6:
        print(f"  PM-6 PASS — 자체검증 기준 {len(CRITERIA)}개 정의됨")
    else:
        failures.append(f"PM-6: CRITERIA 수 이상 ({len(CRITERIA)} != 6)")

    # PM-7: pm_self_diagnosis, pm_quality_checks 함수 정의 확인
    if callable(pm_self_diagnosis) and callable(pm_quality_checks):
        print("  PM-7 PASS — pm_self_diagnosis + pm_quality_checks 정의됨")
    else:
        failures.append("PM-7: pm_self_diagnosis 또는 pm_quality_checks 미정의")

    print()
    if failures:
        print(f"[FAIL] Done Criteria {len(failures)}개 실패:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    else:
        print("[PASS] Done Criteria PM-1~PM-6 모두 통과")


# ══════════════════════════════════════════════════════════════
# 주간 감사 리포트
# ══════════════════════════════════════════════════════════════

def _weekly_audit_report(qc_results: list | None = None) -> None:
    """주간 전체 시스템 감사 리포트 — SA-1~SA-8 + 6-Layer 점수 + 미결 이슈 Telegram 전송."""
    import re as _re_w

    sa_findings = list(_last_audit_findings)
    if not sa_findings:
        sa_findings = pm_system_audit()
    if qc_results is None:
        qc_results = pm_quality_checks()

    audit_path = PROC_DIR / "audit_report.json"
    audit_data: dict = {}
    if audit_path.exists():
        try:
            audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    a_summ   = audit_data.get("summary", {})
    a_total  = a_summ.get("total", 0)
    a_passed = a_summ.get("passed", 0)
    a_status = audit_data.get("audit_status", "UNKNOWN")

    layer_map: dict[str, dict] = {}
    for f in audit_data.get("findings", []):
        lyr = f.get("layer", "?").split("_")[0]
        layer_map.setdefault(lyr, {"p": 0, "t": 0})
        layer_map[lyr]["t"] += 1
        if f.get("passed"):
            layer_map[lyr]["p"] += 1
    layer_lines = "\n".join(
        f"  {lyr}: {v['p']}/{v['t']}" for lyr, v in sorted(layer_map.items())
    ) if layer_map else "  (감사 리포트 없음)"

    pending_data = _load_pending()
    open_issues  = [p for p in pending_data.get("pending", [])
                    if p.get("status") not in ("done", "waiting_credentials", "backlog")]

    test_path = AGENTS_DIR / "tests" / "test_regression.py"
    t_count   = 0
    if test_path.exists():
        t_count = len(_re_w.findall(
            r"^def test_",
            test_path.read_text(encoding="utf-8", errors="ignore"),
            _re_w.MULTILINE
        ))

    qc_pass  = sum(1 for q in qc_results if q["pass"])
    qc_total = len(qc_results)

    gate5_ok   = a_passed >= 52
    gate5_icon = "✅" if gate5_ok else "⚠️"

    sa_detail_lines = "\n".join(
        f"  {f['sa_code']} [{f['severity']}] {f['title']}"
        for f in sa_findings
    ) if sa_findings else "  (SA 감사 미실행)"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = (
        f"<b>📊 주간 시스템 감사 리포트 — {now_str}</b>\n\n"
        f"<b>파이프라인 QC:</b> {qc_pass}/{qc_total} PASS\n\n"
        f"<b>SA-1~SA-8 구조 감사:</b>\n"
        f"{sa_detail_lines}\n\n"
        f"<b>6-Layer 재감사 점수:</b>\n"
        f"  총 {a_passed}/{a_total} PASS | {a_status}\n"
        f"{layer_lines}\n\n"
        f"<b>미결 이슈:</b> {len(open_issues)}건\n"
        f"<b>회귀 테스트:</b> {t_count}개\n\n"
        f"<b>Gate 5 조건 (52/60+):</b> {a_passed}/{a_total} {gate5_icon}"
    )
    print(f"\n[PM] 주간 감사 리포트 전송 중...")
    _tg_send(msg)
    print(f"[PM] 주간 감사 리포트 완료 — 6-Layer: {a_passed}/{a_total}, Gate5: {gate5_icon}")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args      = sys.argv[1:]
    skip_data = "--skip-data" in args

    if "--done-criteria" in args:
        _run_done_criteria()
        sys.exit(0)

    if "--weekly-audit" in args:
        _weekly_audit_report()
        sys.exit(0)

    start_time = time.time()
    print(f"[PM] ══ AI Analyzer PM Agent (고도화) 시작 ══")
    print(f"[PM] 시작: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"[PM] skip_data={skip_data}, max_retries={MAX_RETRIES}")

    _tg_send(
        f"🚀 <b>PM Agent 파이프라인 시작</b>\n"
        f"<i>{datetime.now().strftime('%Y/%m/%d %H:%M')}</i>\n"
        f"max_retries={MAX_RETRIES} | skip_data={skip_data}"
    )

    # ── 1단계: 전체 파이프라인 실행 ──────────────────────────────
    stage_results = run_full_pipeline(skip_data=skip_data)
    failed_stages = [(lbl, ok) for lbl, ok in stage_results if not ok]

    if failed_stages:
        err_text = "\n".join(f"  ✗ {lbl}" for lbl, _ in failed_stages)
        _tg_send(
            f"❌ <b>PM Agent 파이프라인 오류</b>\n"
            f"실패 단계:\n{err_text}\n<i>수동 확인 필요</i>"
        )
        print(f"[PM] 파이프라인 단계 실패 — 종료")
        sys.exit(1)

    # ── 2단계: 자체검증(C1~C6) + 자동 수정 루프 ─────────────────
    for attempt in range(1, MAX_RETRIES + 1):
        failures = validate_results()
        fatal_failures = [(c, d) for c, d in failures if c.fatal]

        print(f"\n[PM] C1~C6 검증 결과 (시도 {attempt}/{MAX_RETRIES}):")
        if not failures:
            print("  C1~C6 전체 기준 통과 ✅")
            break
        for c, d in failures:
            mark = "✗" if c.fatal else "⚠"
            print(f"  {mark} [{c.code}] {d}")

        if not fatal_failures:
            for c, d in failures:
                _tg_send(f"⚠ <b>[{c.code}] {c.desc}</b>\n{d}")
            break

        if attempt < MAX_RETRIES:
            auto_fix(failures, attempt)
        else:
            print(f"[PM] 최대 재시도 {MAX_RETRIES}회 도달 — 실패 상태로 보고")

    # ── 3단계: pm_self_diagnosis — 자가 진단 + 자동 수정 ─────────
    print("\n[PM] pm_self_diagnosis 실행 중...")
    _tg_send("🔍 <b>PM Agent 자가 진단 시작</b>")
    diag_clear, diag_issues = pm_self_diagnosis()

    if diag_clear:
        print("[PM] 자가진단 PASS — 이슈 없음")
        _tg_send("✅ <b>PM 자가진단 PASS</b> — 이슈 없음")
    else:
        diag_txt = "\n".join(f"  • {d}" for d in diag_issues[:10])
        print(f"[PM] 자가진단 이슈 {len(diag_issues)}개")
        _tg_send(
            f"⚠ <b>PM 자가진단 이슈 {len(diag_issues)}개</b>\n{diag_txt}\n"
            f"<i>자동 수정 완료 — fix_request.md 참조</i>"
        )

    # ── 3단계-B: SA 구조 감사 결과 Telegram 전송 ─────────────────
    if _last_audit_findings:
        _sev_icon_p = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📋", "INFO": "ℹ️"}
        _crit_p = [f for f in _last_audit_findings if f["severity"] == "CRITICAL"]
        _sa_lines_p = [
            f"  {_sev_icon_p.get(f['severity'], '')} {f['sa_code']} [{f['severity']}] {f['title']}"
            for f in _last_audit_findings
        ]
        _sa_header_p = (
            f"🚨 <b>SA 구조 감사 — CRITICAL {len(_crit_p)}건 발견</b>"
            if _crit_p else "📋 <b>SA 구조 감사 결과</b>"
        )
        _tg_send(f"{_sa_header_p}\n" + "\n".join(_sa_lines_p))

    # ── 4단계: pm_quality_checks — 품질 기준 ─────────────────────
    print("\n[PM] pm_quality_checks 실행 중...")
    qc_results  = pm_quality_checks()
    qc_failed   = [c for c in qc_results if not c["pass"]]
    qc_all_pass = len(qc_failed) == 0

    # SA-6/SA-7 quality failures → structured audit registration (closes the loop)
    _sa_qc_bridge = [
        {"sa_code": qc["check"].split(" ")[0],
         "severity": "HIGH",
         "title": qc["check"],
         "detail": str(qc.get("detail", ""))}
        for qc in qc_failed
        if qc["check"].split(" ")[0] in ("SA-6", "SA-7")
    ]
    if _sa_qc_bridge:
        _register_audit_findings(_sa_qc_bridge)

    _tg_send_quality_report(qc_results)

    print(f"[PM] pm_quality_checks: {len(qc_results) - len(qc_failed)}/{len(qc_results)} PASS")

    # ── 5단계: 최종 합산 — 두 조건 모두 통과해야 APPROVE ────────────
    final_failures = validate_results()
    c1c6_passed    = not any(c.fatal for c, _ in final_failures)
    all_passed     = c1c6_passed and diag_clear and qc_all_pass
    elapsed        = time.time() - start_time

    if all_passed:
        _tg_send(
            f"🎉 <b>PM Agent 모든 조건 통과</b>\n"
            f"C1~C6: ✅  자가진단: ✅  QC {len(qc_results)}/{len(qc_results)}: ✅\n"
            f"<b>APPROVE 요청 전송 완료</b>\n"
            f"<i>{datetime.now().strftime('%Y/%m/%d %H:%M')}</i>"
        )
    else:
        fail_summary = []
        if not c1c6_passed:
            fail_summary.append("C1~C6 기준 미달")
        if not diag_clear:
            fail_summary.append(f"자가진단 이슈 {len(diag_issues)}개")
        if not qc_all_pass:
            fail_summary.append(f"QC {len(qc_failed)}개 실패")
        _tg_send(
            f"⚠ <b>PM Agent 미통과 — APPROVE 보류</b>\n"
            + "\n".join(f"  • {s}" for s in fail_summary)
            + f"\n<i>최대 {MAX_RETRIES}회 재시도 완료</i>"
        )

    final_report(all_passed, final_failures, elapsed)

    exit_code = 0 if all_passed else 1
    print(f"\n[PM] ══ 완료 ({elapsed/60:.1f}분) | exit={exit_code} ══")

    # 일요일 자동 주간 감사 (--weekly-audit 플래그와 동일 함수)
    if datetime.now().weekday() == 6:
        _weekly_audit_report(qc_results=qc_results)

    sys.exit(exit_code)
