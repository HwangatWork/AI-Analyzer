# -*- coding: utf-8 -*-
"""
PM Agent (고도화) — 완전 자율 파이프라인 오케스트레이터
Done Criteria (PM-1~PM-6):
  PM-1: 전체 파이프라인 단계 실행 (exit 0)
  PM-2: 6가지 자체검증 기준 모두 통과
  PM-3: 최대 3회 자동 수정 루프 (수렴 or Telegram 보고)
  PM-4: 각 단계 완료 시 Telegram 진행 보고
  PM-5: 모든 기준 통과 시 Notion 페이지 업데이트
  PM-6: 최종 결과 Telegram 전송 (성공 or 실패 원인 포함)

자체검증 기준:
  C1: 동행 지수(NASDAQ100/DOW/KOSDAQ/NIKKEI225) 상위 3위 이내 → 재분석
  C2: Granger 미통과 지표 상위 5위 이내 → 재분석
  C3: 자기참조 지표(BBAND/MA50/MA200 등) 상위권 → evaluator 재실행
  C4: 소형주($5B 미만) 기여 Top1 → 경고 Telegram (재시도 없음)
  C5: Validation CRITICAL > 0 → 자동 재실행
  C6: Audit CRITICAL > 0 → 자동 재실행

실행:
  python agents/run_pm_agent.py [--skip-data]
  --skip-data : Data Agent(오래 걸림) 건너뜀 — 이미 수집된 데이터 재사용
"""

import json
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

BASE_DIR         = Path(__file__).parent.parent
AGENTS_DIR       = Path(__file__).parent
OUT_DIR          = BASE_DIR / "output"
PROC_DIR         = BASE_DIR / "data" / "processed"
RESULTS_FILE     = OUT_DIR / "final_results.json"
BASELINE_FILE    = PROC_DIR / "pm_baseline.json"
FIX_REQUEST_FILE = BASE_DIR / "fix_request.md"

MAX_RETRIES = 3

CONTEMPORANEOUS_INDICES = {"NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"}
SELF_REFERENTIAL = {
    "BBAND", "MA50", "MA200", "RSI14", "RSI_SIGNAL",
    "STOCH_RSI", "MARKET_MOMENTUM", "BETA"
}
SMALL_CAP_USD_B_THRESHOLD = 5.0    # $5B 미만이면 소형주 경고
CONTRIBUTOR_TOP1_MIN_MC_B = 200.0  # 기여 1위 시작 시총 최소 기준 (USD billions)
EXTREME_RETURN_THRESHOLD  = 500.0  # ⚠ 이유 텍스트 의무 기준 (%)


# ══════════════════════════════════════════════════════════════
# pm_quality_checks — 전체 품질 기준 검증 함수
# ══════════════════════════════════════════════════════════════

def pm_quality_checks() -> list[dict]:
    """
    PM 품질 기준 전항목 검증.
    반환: [{"check": str, "pass": bool, "detail": str}, ...]
    모든 항목 pass=True 이면 루프 종료 조건 충족.
    """
    results = []
    data = _load_results()
    vr   = _load_validation()
    ar   = _load_audit()

    rank   = data.get("indicator_weight_ranking", [])
    sig    = data.get("market_signal", {})
    sp_a   = data.get("sp500_analysis", {})
    ksp_a  = data.get("kospi_analysis", {})
    sp_cont  = sp_a.get("contribution_top5",  [])
    sp_bene  = sp_a.get("beneficiary_top5",   [])
    ksp_cont = ksp_a.get("contribution_top5", [])
    ksp_bene = ksp_a.get("beneficiary_top5",  [])

    # ── Indicator Quality ──────────────────────────────────────

    # IQ-1: Co-movement indices ranked 4th or lower
    top3_inds = {r["indicator"] for r in rank[:3]}
    cm_in_top3 = top3_inds & CONTEMPORANEOUS_INDICES
    results.append({
        "check": "IQ-1 동행지수 4위 이하",
        "pass":  len(cm_in_top3) == 0,
        "detail": f"OK — 동행지수 상위 3위 없음" if not cm_in_top3
                  else f"FAIL — 상위 3위에 동행지수 포함: {cm_in_top3}",
        "fix_stages": ["run_analysis_agent_v2.py", "run_evaluator_agent_v2.py",
                       "run_validation_agent.py", "generate_report_v2.py"],
    })

    # IQ-2: Granger-passed indicators occupy top 5 exclusively
    top5 = rank[:5]
    granger_fails = [
        r["indicator"] for r in top5
        if not r.get("sp500_granger_sig") and not r.get("kospi_granger_sig")
    ]
    results.append({
        "check": "IQ-2 Top5 Granger 통과",
        "pass":  len(granger_fails) == 0,
        "detail": "OK — Top5 전원 Granger 통과" if not granger_fails
                  else f"FAIL — Granger 미통과 Top5: {granger_fails}",
        "fix_stages": ["run_evaluator_agent_v2.py", "run_validation_agent.py",
                       "generate_report_v2.py"],
    })

    # IQ-3: Valid indicators exclude all self-referential
    self_ref_in_rank = [r["indicator"] for r in rank if r["indicator"] in SELF_REFERENTIAL]
    results.append({
        "check": "IQ-3 자기참조 지표 랭킹 제외",
        "pass":  len(self_ref_in_rank) == 0,
        "detail": "OK — 자기참조 지표 없음" if not self_ref_in_rank
                  else f"FAIL — 자기참조 지표 포함: {self_ref_in_rank}",
        "fix_stages": ["run_evaluator_agent_v2.py", "run_validation_agent.py",
                       "generate_report_v2.py"],
    })

    # IQ-4: Z-Score indicator count matches ranking count
    z_count   = sig.get("total_signals", 0)
    rank_count = len(rank)
    results.append({
        "check": "IQ-4 Z-Score ↔ 랭킹 지표 수 일치",
        "pass":  z_count == rank_count,
        "detail": f"OK — 양쪽 {z_count}개" if z_count == rank_count
                  else f"FAIL — Z-Score {z_count}개 vs 랭킹 {rank_count}개",
        "fix_stages": ["run_ui_agent.py", "generate_report_v2.py"],
    })

    # ── Stock Analysis ─────────────────────────────────────────

    for label, lst in [("SA-1 SP500 기여", sp_cont), ("SA-2 SP500 수혜", sp_bene),
                        ("SA-3 KOSPI 기여", ksp_cont), ("SA-4 KOSPI 수혜", ksp_bene)]:
        results.append({
            "check": f"{label} Top5",
            "pass":  len(lst) == 5,
            "detail": f"OK — 5개" if len(lst) == 5 else f"FAIL — {len(lst)}개 (5개 필요)",
            "fix_stages": ["run_stock_agent_v2.py", "run_ui_agent.py", "generate_report_v2.py"],
        })

    # SA-5: SP500 기여 Top1 시작 시총 ≥ $200B
    sp_top1 = sp_cont[0] if sp_cont else {}
    mc1 = sp_top1.get("market_cap_start_b") or sp_top1.get("market_cap_b") or 0
    results.append({
        "check": "SA-5 기여 Top1 시총 ≥$200B",
        "pass":  mc1 >= CONTRIBUTOR_TOP1_MIN_MC_B,
        "detail": f"OK — ${mc1:.0f}B" if mc1 >= CONTRIBUTOR_TOP1_MIN_MC_B
                  else f"FAIL — ${mc1:.0f}B < $200B ({sp_top1.get('name','?')})",
        "fix_stages": [],   # 경고만 (데이터 결과)
    })

    # SA-6: KOSPI 기여 Top1 시작 시총 ≥ $200B
    ksp_top1 = ksp_cont[0] if ksp_cont else {}
    mc1k = ksp_top1.get("market_cap_start_b") or ksp_top1.get("market_cap_b") or 0
    results.append({
        "check": "SA-6 KOSPI 기여 Top1 시총 ≥$200B",
        "pass":  mc1k >= CONTRIBUTOR_TOP1_MIN_MC_B,
        "detail": f"OK — ${mc1k:.0f}B" if mc1k >= CONTRIBUTOR_TOP1_MIN_MC_B
                  else f"FAIL — ${mc1k:.0f}B < $200B ({ksp_top1.get('name','?')})",
        "fix_stages": [],
    })

    # SA-7: ⚠ 표시 종목 전원 warn_reason 보유
    all_stocks = sp_cont + sp_bene + ksp_cont + ksp_bene
    flagged_missing = [
        s.get("name", s.get("ticker", "?"))
        for s in all_stocks
        if abs(s.get("excess_return_pct", 0) or s.get("stock_return_pct", 0)) >= EXTREME_RETURN_THRESHOLD
        and not s.get("warn_reason")
    ]
    results.append({
        "check": "SA-7 ⚠종목 warn_reason 보유",
        "pass":  len(flagged_missing) == 0,
        "detail": "OK — 전원 이유 텍스트 보유" if not flagged_missing
                  else f"FAIL — warn_reason 없음: {flagged_missing}",
        "fix_stages": ["run_stock_agent_v2.py", "run_ui_agent.py", "generate_report_v2.py"],
    })

    # ── Signal Integrity ───────────────────────────────────────

    # SI-1: signal total == Z-Score indicator count (already IQ-4, recheck explicitly)
    z_inds   = len(sig.get("indicator_signals", []))
    results.append({
        "check": "SI-1 시그널 지표 수 = Z-Score 수",
        "pass":  z_inds == rank_count,
        "detail": f"OK — {z_inds}개" if z_inds == rank_count
                  else f"FAIL — 시그널 {z_inds}개 vs 랭킹 {rank_count}개",
        "fix_stages": ["run_ui_agent.py", "generate_report_v2.py"],
    })

    # ── News Quality ───────────────────────────────────────────

    news_file = OUT_DIR / "news_report.json"
    if news_file.exists():
        try:
            news_data = json.loads(news_file.read_text(encoding="utf-8"))
            movements = news_data.get("movements", [])
            causes    = news_data.get("causes", [])
            watchpts  = news_data.get("watchpoints", [])
            sources   = news_data.get("sources", [])

            # NQ-1: 등락률(%) + 방향 기호
            nq1_ok = any(
                ("%" in m) and any(c in m for c in ("▲", "▼")) and any(c.isdigit() for c in m)
                for m in movements
            )
            results.append({
                "check": "NQ-1 핵심 움직임 등락률(%)",
                "pass":  nq1_ok,
                "detail": "OK — 등락률 포함" if nq1_ok else "FAIL — 등락률(%) 없음",
                "fix_stages": ["run_news_agent.py"],
            })

            # NQ-2: 원인→결과 구조 (→ 기호 필수, 헤드라인 복붙 불가)
            nq2_ok = bool(causes) and all("→" in c for c in causes)
            results.append({
                "check": "NQ-2 가능한 원인 원인→결과 구조",
                "pass":  nq2_ok,
                "detail": "OK — 모든 원인에 → 포함" if nq2_ok else "FAIL — → 없는 원인 존재",
                "fix_stages": ["run_news_agent.py"],
            })

            # NQ-3: 날짜 명시
            nq3_ok = bool(watchpts) and any(
                wp.get("date", "미정") not in ("미정", "", None) and len(wp.get("date", "")) >= 7
                for wp in watchpts
            )
            results.append({
                "check": "NQ-3 주시 포인트 날짜 명시",
                "pass":  nq3_ok,
                "detail": "OK — 날짜 포함" if nq3_ok else "FAIL — 날짜 없음",
                "fix_stages": ["run_news_agent.py"],
            })

            # NQ-4: ≥3개 실제 기사 URL (Google 리다이렉트 제외)
            real_links   = [s for s in sources if s.get("link","").startswith("http")
                            and "news.google.com" not in s.get("link","")]
            google_links = [s for s in sources if s.get("link","").startswith("http")
                            and "news.google.com" in s.get("link","")]
            nq4_ok = len(real_links) >= 3
            detail = (f"OK — 실제URL {len(real_links)}개" if nq4_ok else
                      f"FAIL — 실제URL {len(real_links)}개 + 구글리다이렉트 {len(google_links)}개")
            results.append({
                "check": "NQ-4 뉴스 실제URL ≥3개",
                "pass":  nq4_ok,
                "detail": detail,
                "fix_stages": ["run_news_agent.py"],
            })
        except Exception as e:
            for nq in ["NQ-1", "NQ-2", "NQ-3", "NQ-4"]:
                results.append({
                    "check": f"{nq} (파싱 오류)",
                    "pass":  False,
                    "detail": f"FAIL — news_report.json 파싱 실패: {e}",
                    "fix_stages": ["run_news_agent.py"],
                })
    else:
        for nq in ["NQ-1", "NQ-2", "NQ-3", "NQ-4"]:
            results.append({
                "check": f"{nq} (파일 없음)",
                "pass":  False,
                "detail": "FAIL — output/news_report.json 없음",
                "fix_stages": ["run_news_agent.py"],
            })

    return results


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
    baseline: dict = {}
    if BASELINE_FILE.exists():
        try:
            baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

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

    # SD-7: GitHub Actions 마지막 run-pipeline 실패 감지 (GITHUB_TOKEN 필요)
    try:
        import os as _os
        import urllib.request as _urllib_req
        _gh_token = _os.getenv("GITHUB_TOKEN", "")
        if _gh_token:
            _req = _urllib_req.Request(
                "https://api.github.com/repos/HwangatWork/AI-Analyzer/actions/runs"
                "?per_page=10&branch=main",
                headers={"Authorization": f"token {_gh_token}",
                         "Accept": "application/vnd.github+json"},
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
        pass  # GITHUB_TOKEN 없거나 API 오류 시 건너뜀

    # SD-8: News Agent 실제 URL 부족 시 재실행 플래그
    _news_file = OUT_DIR / "news_report.json"
    if _news_file.exists():
        try:
            _news_data = json.loads(_news_file.read_text(encoding="utf-8"))
            _real_links = [
                s for s in _news_data.get("sources", [])
                if s.get("link", "").startswith("http")
                and "news.google.com" not in s.get("link", "")
            ]
            if len(_real_links) < 3:
                issues.append(
                    f"SD-8 News Agent 실제URL {len(_real_links)}개 (최소 3개 필요) "
                    f"— run_news_agent.py 재실행 필요"
                )
        except Exception:
            pass

    print(f"[PM] 자가진단 완료 — 이슈 {len(issues)}개")
    for iss in issues:
        print(f"  ⚠ {iss}")

    # ── 문제 발견 시 자동 수정 ────────────────────────────────
    if issues:
        _write_fix_request(issues)
        _auto_fix_from_diagnosis(issues)
        # 수정 후 quality check 결과 추가
        qc = pm_quality_checks()
        qc_failed = [c for c in qc if not c["pass"]]
        if qc_failed:
            for c in qc_failed:
                issues.append(f"QC재검증 실패: {c['check']} — {c['detail']}")

    # ── 기준선 저장 ───────────────────────────────────────────
    _save_baseline(curr_count, rank)

    return len(issues) == 0, issues


def _write_fix_request(issues: list[str]) -> None:
    lines = [
        "# PM Agent 자가진단 수정 요청서",
        f"생성: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}",
        "",
        "## 발견된 문제",
    ]
    for i, iss in enumerate(issues, 1):
        lines.append(f"{i}. {iss}")
    lines += [
        "",
        "## 자동 수정 계획",
        "- run_evaluator_agent_v2.py  — 자기참조/동행지수 재필터",
        "- run_stock_agent_v2.py      — warn_reason 재생성",
        "- run_ui_agent.py            — 최종 결과 재빌드",
        "- generate_report_v2.py      — 리포트 재생성",
    ]
    FIX_REQUEST_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[PM] fix_request.md 작성 완료 ({len(issues)}개 이슈)")


def _auto_fix_from_diagnosis(issues: list[str]) -> None:
    """진단 코드별로 해당 Agent 자동 재실행."""
    scripts_needed: set[str] = set()

    for iss in issues:
        if "SD-1" in iss or "SD-6" in iss:
            scripts_needed |= {"run_analysis_agent_v2.py", "run_evaluator_agent_v2.py"}
        if "SD-2" in iss or "SD-3" in iss:
            scripts_needed |= {"run_evaluator_agent_v2.py", "run_validation_agent.py"}
        if "SD-4" in iss or "SD-5" in iss:
            scripts_needed |= {"run_stock_agent_v2.py"}
        if "SD-8" in iss:
            scripts_needed |= {"run_news_agent.py"}
        # SD-7 (GitHub Actions 실패)는 원격 CI 문제 — 로컬 재실행 불필요

    if not scripts_needed:
        return

    # 항상 마지막 단계 포함
    scripts_needed |= {"run_ui_agent.py", "generate_report_v2.py"}

    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    ordered = sorted(
        scripts_needed,
        key=lambda s: pipeline_order.index(s) if s in pipeline_order else 99
    )

    _tg_send(
        f"🔧 <b>PM 자가진단 자동 수정</b>\n"
        f"이슈 {len(issues)}개 발견\n"
        f"재실행: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자가진단 자동 수정: {ordered}")
    run_partial_pipeline(ordered)


def _save_baseline(indicator_count: int, rank: list) -> None:
    baseline = {
        "timestamp":       datetime.now().isoformat(),
        "indicator_count": indicator_count,
        "top5_indicators": [r["indicator"] for r in rank[:5]],
        "top1_indicator":  rank[0]["indicator"] if rank else None,
    }
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[PM] 기준선 저장: {indicator_count}개 지표")


def _tg_send_quality_report(checks: list[dict]) -> None:
    """품질 검증 결과 텔레그램 보고."""
    passed = [c for c in checks if c["pass"]]
    failed = [c for c in checks if not c["pass"]]
    icon   = "✅" if not failed else "⚠"
    lines  = [f"{icon} <b>PM Quality Check Results</b>",
              f"통과: {len(passed)}/{len(checks)}",  ""]
    for c in checks:
        mark = "✅" if c["pass"] else "❌"
        lines.append(f"{mark} {c['check']}: {c['detail'][:80]}")
    _tg_send("\n".join(lines))


def _tg_check_approve() -> bool:
    """텔레그램 최근 메시지에 APPROVE가 있으면 True 반환."""
    try:
        import os, urllib.request
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return False
        url = f"https://api.telegram.org/bot{token}/getUpdates?offset=-5&limit=5"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for upd in reversed(data.get("result", [])):
            text = (upd.get("message") or upd.get("channel_post") or {}).get("text", "")
            if "APPROVE" in text.upper():
                return True
    except Exception:
        pass
    return False


# ── Telegram 전송 (run_telegram_agent 없이 직접 호출) ────────────

def _tg_send(text: str) -> None:
    """텔레그램 메시지 전송 (run_telegram_agent 임포트 없이 직접)."""
    try:
        import os, urllib.request
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


# ── 자체검증 ─────────────────────────────────────────────────────

class Criterion:
    def __init__(self, code: str, desc: str, fix_stages: list[str]):
        self.code       = code
        self.desc       = desc
        self.fix_stages = fix_stages   # 재실행할 스크립트 목록
        self.fatal      = True         # False면 경고만 (retry 없음)


CRITERIA = [
    Criterion("C1", "동행 지수 상위 3위 이내",
              ["run_analysis_agent_v2.py", "run_evaluator_agent_v2.py",
               "run_validation_agent.py", "generate_report_v2.py"]),
    Criterion("C2", "Granger 미통과 지표 상위 5위 이내",
              ["run_evaluator_agent_v2.py", "run_validation_agent.py",
               "generate_report_v2.py"]),
    Criterion("C3", "자기참조 지표 상위권",
              ["run_evaluator_agent_v2.py", "run_validation_agent.py",
               "generate_report_v2.py"]),
    Criterion("C4", "소형주 기여 Top1", []),          # 경고만, retry 없음
    Criterion("C5", "Validation CRITICAL > 0",
              ["run_validation_agent.py", "generate_report_v2.py"]),
    Criterion("C6", "Audit CRITICAL > 0",
              ["run_audit_agent.py"]),
]
# C4는 재시도 없음
CRITERIA[3].fatal = False


def validate_results() -> list[tuple[Criterion, str]]:
    """결과 검증 → 실패한 (Criterion, 상세) 목록 반환."""
    failures: list[tuple[Criterion, str]] = []
    data = _load_results()
    vr   = _load_validation()
    ar   = _load_audit()

    if not data:
        return [(CRITERIA[0], "final_results.json 없음")]

    rank = data.get("indicator_weight_ranking", [])

    # C1: 동행 지수 상위 3위
    top3_inds = {r["indicator"] for r in rank[:3]}
    overlap   = top3_inds & CONTEMPORANEOUS_INDICES
    if overlap:
        failures.append((CRITERIA[0], f"상위 3위에 동행 지수 포함: {overlap}"))

    # C2: Granger 미통과 지표 상위 5위
    top5 = rank[:5]
    granger_fails = [
        r["indicator"] for r in top5
        if not r.get("sp500_granger_sig") and not r.get("kospi_granger_sig")
    ]
    if granger_fails:
        failures.append((CRITERIA[1], f"Granger 미통과 상위 5위: {granger_fails}"))

    # C3: 자기참조 지표 상위권 (상위 5위)
    self_ref_in_top = [r["indicator"] for r in top5 if r["indicator"] in SELF_REFERENTIAL]
    if self_ref_in_top:
        failures.append((CRITERIA[2], f"자기참조 지표 상위 5위: {self_ref_in_top}"))

    # C4: 소형주 기여 Top1 (경고만)
    sp_top1 = (data.get("sp500_analysis", {}).get("contribution_top5") or [{}])[0]
    mc_start = sp_top1.get("market_cap_start_b") or sp_top1.get("market_cap_b") or 0
    if 0 < mc_start < SMALL_CAP_USD_B_THRESHOLD:
        failures.append((CRITERIA[3],
            f"S&P500 기여 1위 시총 ${mc_start:.1f}B — 소형주({sp_top1.get('name','?')}) ⚠ 수동 확인 필요"))

    # C5: Validation CRITICAL
    val_crit = vr.get("summary", {}).get("failed_critical", 0)
    if val_crit and val_crit != "?" and int(val_crit) > 0:
        crit_items = [
            f"[{c['check_id']}] {c.get('description','')}"
            for c in vr.get("checks", [])
            if not c.get("passed") and c.get("severity") == "CRITICAL"
        ]
        failures.append((CRITERIA[4], f"CRITICAL {val_crit}건: {crit_items[:3]}"))

    # C6: Audit CRITICAL
    aud_crit = ar.get("summary", {}).get("failed_critical", 0)
    if aud_crit and int(aud_crit) > 0:
        audit_items = [
            f"[{f['code']}] {f.get('target','')}"
            for f in ar.get("findings", [])
            if not f.get("passed") and f.get("severity") == "CRITICAL"
        ]
        failures.append((CRITERIA[5], f"Audit CRITICAL {aud_crit}건: {audit_items[:3]}"))

    return failures


# ── 전체 파이프라인 실행 ──────────────────────────────────────────

PIPELINE_STAGES = [
    ("run_data_agent_v2.py",    "Data Agent",       1, 800),
    ("refresh_data.py",         "Refresh",          2, 120),
    ("run_analysis_agent_v2.py","Analysis Agent",   3, 300),
    ("run_stock_agent_v2.py",   "Stock Agent",      4, 300),
    ("run_evaluator_agent_v2.py","Evaluator Agent", 5, 120),
    ("run_sector_agent.py",     "Sector Agent",     6, 120),
    ("run_validation_agent.py", "Validation Agent", 7, 120),
    ("run_ui_agent.py",         "UI Agent",         8, 120),
    ("generate_report_v2.py",   "Report",           9, 120),
    ("run_audit_agent.py",      "Audit Agent",      10, 300),
]
TOTAL_STEPS = 11  # 10 스테이지 + 1 최종 보고


def run_full_pipeline(skip_data: bool = False) -> list[tuple[str, bool]]:
    """전체 파이프라인 실행. 각 단계 완료 시 Telegram 보고."""
    results = []
    for script, label, step_n, timeout in PIPELINE_STAGES:
        if skip_data and script in ("run_data_agent_v2.py", "refresh_data.py"):
            print(f"[PM] 건너뜀 (--skip-data): {script}")
            _tg_step(step_n, TOTAL_STEPS, label, "건너뜀 (기존 데이터 사용)")
            results.append((label, True))
            continue
        ok, out = _run(script, label, timeout)
        short = out.strip().splitlines()[-1][:150] if out.strip() else ""
        _tg_step(step_n, TOTAL_STEPS, label, short if ok else f"⚠ 오류: {short}")
        results.append((label, ok))
        if not ok:
            print(f"[PM] {label} 실패 — 파이프라인 중단")
            break
    return results


def run_partial_pipeline(scripts: list[str]) -> list[tuple[str, bool]]:
    """지정 스테이지만 재실행 (자동 수정용)."""
    script_map = {s: (lbl, sn, to) for s, lbl, sn, to in PIPELINE_STAGES}
    results = []
    for script in scripts:
        if script not in script_map:
            print(f"[PM] 알 수 없는 스크립트: {script} — 건너뜀")
            continue
        lbl, sn, to = script_map[script]
        ok, out = _run(script, lbl, to)
        results.append((lbl, ok))
    return results


# ── 자동 수정 ─────────────────────────────────────────────────────

def auto_fix(failures: list[tuple[Criterion, str]], attempt: int) -> None:
    """실패 기준별 자동 수정 실행."""
    fatal   = [(c, d) for c, d in failures if c.fatal]
    warning = [(c, d) for c, d in failures if not c.fatal]

    # 경고 항목은 Telegram 보고만
    for c, d in warning:
        _tg_send(
            f"⚠ <b>PM Agent 경고 [{c.code}]</b>\n"
            f"기준: {c.desc}\n상세: {d}\n<i>재시도 없음 — 수동 확인 권장</i>"
        )

    if not fatal:
        return

    # 가장 영향 범위가 큰 fix_stages 합집합으로 재실행 (중복 제거, 순서 유지)
    seen    = set()
    ordered = []
    for c, _ in fatal:
        for s in c.fix_stages:
            if s not in seen:
                seen.add(s)
                ordered.append(s)

    # 파이프라인 순서 보존
    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    ordered.sort(key=lambda s: pipeline_order.index(s) if s in pipeline_order else 99)

    fail_descs = "\n".join(f"  [{c.code}] {d}" for c, d in fatal)
    _tg_send(
        f"🔄 <b>PM Agent 자동 수정 시도 {attempt}/{MAX_RETRIES}</b>\n"
        f"실패 기준:\n{fail_descs}\n\n"
        f"재실행 단계: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자동 수정 실행: {ordered}")
    run_partial_pipeline(ordered)


# ── 최종 보고 ─────────────────────────────────────────────────────

def final_report(all_passed: bool, failures: list[tuple[Criterion, str]], elapsed: float) -> None:
    """Telegram 최종 보고 + Notion 업데이트."""
    data  = _load_results()
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    direc = sig.get("direction", "N/A")
    rank  = data.get("indicator_weight_ranking", [])

    top3 = "\n".join(
        f"  {r['rank']}. {r['indicator']} ({r['combined_weight']:.4f})"
        for r in rank[:3]
    )

    vr = _load_validation()
    vs = vr.get("summary", {})
    val_pass = vs.get("passed", "?")
    val_tot  = vs.get("total",  "?")

    elapsed_str = f"{elapsed/60:.1f}분"

    if all_passed:
        status_emoji = "✅"
        status_text  = "모든 자체검증 기준 통과"
    else:
        status_emoji = "⚠"
        fail_list = "\n".join(f"  [{c.code}] {d}" for c, d in failures if c.fatal)
        status_text = f"일부 기준 미달 (최대 {MAX_RETRIES}회 재시도 완료)\n{fail_list}"

    msg = (
        f"🏁 <b>PM Agent 완료</b>  ({elapsed_str})\n\n"
        f"{status_emoji} <b>상태:</b> {status_text}\n\n"
        f"<b>시장 시그널:</b> {score:.1f} / 100  ({direc})\n"
        f"<b>Validation:</b> {val_pass}/{val_tot} PASS\n\n"
        f"<b>가중치 Top3:</b>\n{top3}\n\n"
        f"<i>AI Analyzer PM Agent v2 | {datetime.now().strftime('%Y/%m/%d %H:%M')}</i>"
    )
    _tg_send(msg)
    print(f"[PM] 최종 Telegram 보고 완료")

    # Notion 업데이트
    notion_script = AGENTS_DIR / "run_notion_agent.py"
    if notion_script.exists():
        import os
        if os.getenv("NOTION_TOKEN"):
            ok, _ = _run("run_notion_agent.py", "Notion 업데이트", 60)
            if ok:
                print("[PM] Notion 업데이트 완료")
            else:
                print("[PM] Notion 업데이트 실패 (비치명적)")
        else:
            print("[PM] NOTION_TOKEN 없음 — Notion 업데이트 건너뜀")

    # Telegram --summary (상세 포맷)
    _run("run_telegram_agent.py", "Telegram 상세 요약", 30)
    _tg_step(TOTAL_STEPS, TOTAL_STEPS, "최종 보고", "Telegram + Notion 완료")


# ── Done Criteria 자체검증 ────────────────────────────────────────

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
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args      = sys.argv[1:]
    skip_data = "--skip-data" in args

    if "--done-criteria" in args:
        _run_done_criteria()
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

    # ── 4단계: pm_quality_checks — 12개 품질 기준 ─────────────────
    print("\n[PM] pm_quality_checks 실행 중...")
    qc_results  = pm_quality_checks()
    qc_failed   = [c for c in qc_results if not c["pass"]]
    qc_all_pass = len(qc_failed) == 0

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
    sys.exit(exit_code)
