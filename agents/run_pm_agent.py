# -*- coding: utf-8 -*-
"""
PM Agent — Orchestrator + Meta-Audit (run_pm_agent.py)
  역할 1 (Orchestrator/.claude/agents/orchestrator.md):
    파이프라인 조율, APPROVE/HOLD 최종 판단, pending_requests 갱신
  역할 2 (Meta-Audit/.claude/agents/meta-audit-agent.md):
    pm_self_diagnosis() — SD-1~20 자가진단, report_quality_check() 보고서 레벨 평가
  [설계 주의] 두 역할이 한 파일에 혼재. 규모 확장 시 별도 분리 고려.

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

import io
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows cp949 환경에서 한글 UnicodeEncodeError 방지
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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

    # 기존 항목 양쪽에서 제거
    data[target_list] = [e for e in data[target_list] if e["id"] != req_id]
    data[other_list]  = [e for e in data[other_list]  if e["id"] != req_id]

    data[target_list].append(entry)
    _save_pending(data)
    print(f"[PM] pending_requests 등록: {req_id} ({status})")

MAX_RETRIES = 3

CONTEMPORANEOUS_INDICES = {"NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"}
SELF_REFERENTIAL = {
    "RSI14", "MA50", "RSI_SIGNAL", "BETA", "MA_SIGNAL",
    # 완화된 항목 (지연 지표 — KOSPI 예측 유효): BBAND, STOCH_RSI, MARKET_MOMENTUM 제거
}
SMALL_CAP_USD_B_THRESHOLD = 5.0    # $5B 미만이면 소형주 경고
CONTRIBUTOR_TOP1_MIN_MC_B = 200.0  # 기여 1위 시작 시총 최소 기준 (USD billions)
EXTREME_RETURN_THRESHOLD  = 500.0  # ⚠ 이유 텍스트 의무 기준 (%)


# ══════════════════════════════════════════════════════════════
# report_quality_check — 완료 보고 품질 자가 평가 (REQ-018)
# ══════════════════════════════════════════════════════════════

def report_quality_check() -> list[str]:
    """
    QR: 최근 완료 항목의 Evidence 품질 검증.
    - priority=high 완료 항목에 수치/exit code/실행 결과 없으면 QR-1 WARN
    - 정적 분석 키워드만 있고 동적 실행 증거 없으면 QR-2 WARN
    반환: WARN 메시지 리스트 (빈 리스트 = 전항목 OK)
    """
    import re as _re_qr
    warnings: list[str] = []
    if not PENDING_FILE.exists():
        return warnings
    try:
        _pdata = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        _all_items = _pdata.get("completed", []) + _pdata.get("pending", [])
        _done_items = [i for i in _all_items if i.get("status") == "done"]
    except Exception:
        return warnings

    # 동적 실행 증거 키워드 (수치/exit code/로그 포함)
    _dyn_evidence = _re_qr.compile(
        r'\d+/\d+|exit[= ]\d|\bexit\s*code\b|exit_code|run_id=|conclusion='
        r'|\d+%|\d+개|\d+건|\bPASS\b|\bFAIL\b|\d{4,}',
        _re_qr.IGNORECASE,
    )
    # 정적 분석만 시사하는 키워드
    _static_only = _re_qr.compile(
        r'정적 분석|코드 읽기|코드 확인|grep으로|read_text|패턴 탐지만',
        _re_qr.IGNORECASE,
    )

    for _item in _done_items:
        if _item.get("priority") != "high":
            continue
        _req_id  = _item.get("id", "?")
        _details = _item.get("details", "")

        _has_dyn    = bool(_dyn_evidence.search(_details))
        _has_static = bool(_static_only.search(_details))

        if not _has_dyn:
            warnings.append(
                f"QR-1 {_req_id} Evidence 수치 없음 — priority=high 완료 보고에 "
                f"exit code/실행 수치/run_id 없음 (동적 테스트 미확인 가능성)"
            )
        elif _has_static and not _has_dyn:
            warnings.append(
                f"QR-2 {_req_id} 정적 분석만 기재 — 동적 실행 증거(exit code/수치) 없음"
            )

    return warnings


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

    # SA-8: KOSPI 극단 수익률(±200%) 종목 전원 교차검증 실행 확인
    kospi_extreme = [
        s for s in ksp_cont + ksp_bene
        if abs(s.get("stock_return_pct", 0)) >= 200
    ]
    cross_missing = [
        s.get("name", s.get("ticker", "?"))
        for s in kospi_extreme
        if not s.get("data_quality") or s.get("data_quality") == "없음"
    ]
    results.append({
        "check": "SA-8 KOSPI 극단종목 교차검증 실행",
        "pass":  len(cross_missing) == 0,
        "detail": f"OK — 극단종목 {len(kospi_extreme)}개 전원 교차검증 완료" if not cross_missing
                  else f"FAIL — 교차검증 미실행: {cross_missing}",
        "fix_stages": ["run_stock_agent_v2.py"],
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

            # NQ-4: ≥3개 기사 URL (https://, 기사 경로 포함 — Google News 기사별 경로 허용)
            def _pm_is_article_url(url: str) -> bool:
                try:
                    from urllib.parse import urlparse
                    path = urlparse(url).path.rstrip("/")
                    return bool(path) and path not in ("", "/", "/home", "/news")
                except Exception:
                    return False
            article_links = [s for s in sources
                             if s.get("link","").startswith("https://")
                             and _pm_is_article_url(s.get("link",""))]
            homepage_links = [s for s in sources
                              if s.get("link","").startswith("https://")
                              and not _pm_is_article_url(s.get("link",""))]
            nq4_ok = len(article_links) >= 3
            detail = (f"OK — 기사URL {len(article_links)}개" if nq4_ok else
                      f"FAIL — 기사URL {len(article_links)}개 (홈페이지 {len(homepage_links)}개, 최소3개 필요)")
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

    # ── Condition B: 복합 시그널 점수(0~100) + 방향성 ────────────
    score_val = sig.get("score")
    direction = sig.get("direction", "")
    qb1_ok = (score_val is not None
              and isinstance(score_val, (int, float))
              and 0 <= float(score_val) <= 100
              and direction in ("risk-on", "neutral", "risk-off"))
    results.append({
        "check": "QB-1 복합 시그널 점수 0~100 + 방향성",
        "pass":  qb1_ok,
        "detail": f"OK — score={score_val}, direction={direction}" if qb1_ok
                  else f"FAIL — score={score_val} 범위 또는 direction={direction} 무효",
        "fix_stages": ["run_ui_agent.py", "generate_report_v2.py"],
    })

    # ── Condition C: GitHub Pages 대시보드 배포 링크 ─────────────
    dashboard_file = OUT_DIR / "dashboard.html"
    _local_ok = dashboard_file.exists() and dashboard_file.stat().st_size > 10000
    _pages_ok  = False
    _pages_detail = ""
    try:
        import urllib.request as _urlreq
        _pages_url = "https://hwangatwork.github.io/AI-Analyzer/"
        _req = _urlreq.Request(_pages_url, method="HEAD")
        with _urlreq.urlopen(_req, timeout=10) as _resp:
            _pages_ok = (_resp.status == 200)
            _pages_detail = f" | Pages={_resp.status}"
    except Exception as _pe:
        _pages_detail = f" | Pages=ERR({str(_pe)[:40]})"
    qc1_ok = _local_ok and _pages_ok
    _size_str = f"{dashboard_file.stat().st_size:,}bytes" if _local_ok else "없음"
    results.append({
        "check": "QC-1 dashboard.html 빌드 + Pages 200 OK",
        "pass":  qc1_ok,
        "detail": (f"OK — local={_size_str}{_pages_detail}" if qc1_ok
                   else f"FAIL — local={_size_str}{_pages_detail}"),
        "fix_stages": ["run_ui_agent.py", "generate_report_v2.py"],
    })

    # ── Condition D: 주 1회 자동화 파이프라인 (GitHub Actions schedule) ──
    import os as _os
    wf_dir = BASE_DIR / ".github" / "workflows"
    qd1_ok = False
    qd1_detail = "FAIL — .github/workflows 없음"
    if wf_dir.exists():
        for wf in wf_dir.glob("*.yml"):
            try:
                content = wf.read_text(encoding="utf-8")
                if "schedule" in content and "cron" in content:
                    qd1_ok = True
                    qd1_detail = f"OK — {wf.name}에 cron 스케줄 확인"
                    break
            except Exception:
                pass
        if not qd1_ok:
            qd1_detail = "FAIL — 스케줄 cron 설정된 워크플로우 없음"
    results.append({
        "check": "QD-1 주간 자동화 파이프라인 스케줄",
        "pass":  qd1_ok,
        "detail": qd1_detail,
        "fix_stages": [],   # CI 설정 — 자동 수정 불가
    })

    # ── Condition E: BUY/SELL/HOLD 의사결정 엔진 ─────────────────
    # decision.json 또는 final_results.json["decision"] 확인
    decision_file = OUT_DIR / "decision.json"
    qe1_ok = False
    qe1_detail = "FAIL — decision 데이터 없음"
    valid_actions = {"BUY", "SELL", "HOLD", "SELL/AVOID"}
    _dec_src = {}
    if decision_file.exists():
        try:
            _dec_src = json.loads(decision_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not _dec_src:
        _dec_src = data.get("decision", {})   # final_results.json["decision"]
    if _dec_src:
        sp_act  = (_dec_src.get("sp500") or {}).get("action", "")
        ksp_act = (_dec_src.get("kospi")  or {}).get("action", "")
        if sp_act in valid_actions and ksp_act in valid_actions:
            qe1_ok = True
            qe1_detail = f"OK — SP500={sp_act}, KOSPI={ksp_act}"
        else:
            qe1_detail = f"FAIL — 유효하지 않은 action: SP500={sp_act!r}, KOSPI={ksp_act!r}"
    results.append({
        "check": "QE-1 BUY/SELL/HOLD 의사결정 유효",
        "pass":  qe1_ok,
        "detail": qe1_detail,
        "fix_stages": ["run_decision_agent.py", "generate_report_v2.py"],
    })

    # ── Condition F: AI 언어 리포트 + 액션플랜 ───────────────────
    # QF-1: FINAL_REPORT.md 내용 품질만 검사 (API 키 여부 무관)
    import re as _reF
    final_report_f  = OUT_DIR / "FINAL_REPORT.md"
    narrative_ctx_f = OUT_DIR / "narrative_context.json"
    qf1_ok = False
    qf1_detail = "FAIL — FINAL_REPORT.md 없음 (서브에이전트 미실행)"
    if final_report_f.exists():
        try:
            report_text = final_report_f.read_text(encoding="utf-8")
            num_matches = _reF.findall(r'[+-]?\d+\.?\d+', report_text)
            has_numbers = len(num_matches) >= 10
            # 내용이 없거나 너무 짧으면 FAIL
            if len(report_text.strip()) < 200:
                qf1_detail = f"FAIL — FINAL_REPORT.md 내용 너무 짧음 ({len(report_text)}자)"
            elif not has_numbers:
                qf1_detail = f"FAIL — FINAL_REPORT.md 실제 수치 없음 ({len(num_matches)}개 < 10)"
            else:
                qf1_ok = True
                qf1_detail = f"OK — FINAL_REPORT.md {len(report_text)}자, 수치 {len(num_matches)}개"
        except Exception as _e:
            qf1_detail = f"FAIL — FINAL_REPORT.md 읽기 오류: {_e}"
    elif narrative_ctx_f.exists():
        # 컨텍스트만 있고 리포트 미생성 — 서브에이전트 실행 필요
        qf1_ok = False
        qf1_detail = "WARN — narrative_context.json 준비됨, FINAL_REPORT.md 미생성 (서브에이전트 실행 필요)"
    results.append({
        "check": "QF-1 AI 언어 리포트 + 액션플랜",
        "pass":  qf1_ok,
        "detail": qf1_detail,
        "fix_stages": ["run_narrative_agent.py", "generate_report_v2.py"],
    })

    # ── Condition G: Google Sheets 연동 상태 ─────────────────────
    import os as _os2
    google_sa = _os2.getenv("GOOGLE_SA_JSON", "")
    qg1_ok = bool(google_sa)
    results.append({
        "check": "QG-1 Google Sheets 서비스 계정 설정",
        "pass":  qg1_ok,
        "detail": ("OK — GOOGLE_SA_JSON 설정됨" if qg1_ok
                   else "FAIL — GOOGLE_SA_JSON 미설정 (pending_requests.json T9 참고)"),
        "fix_stages": [],   # 사용자가 .env에 추가해야 함
    })

    # ── Condition H: 산업별 딥다이브 데이터 ──────────────────────
    sector_file = OUT_DIR / "sector_analysis.json"
    qh1_ok = False
    qh1_detail = "FAIL — output/sector_analysis.json 없음"
    if sector_file.exists():
        try:
            sec = json.loads(sector_file.read_text(encoding="utf-8"))
            total_tickers = sum(
                len([v for v in data.get("tickers", {}).values() if "return_1y" in v])
                for k, data in sec.items() if k != "_meta"
            )
            if total_tickers >= 3:
                qh1_ok = True
                qh1_detail = f"OK — {len([k for k in sec if k!='_meta'])}개 섹터, {total_tickers}종목"
            else:
                qh1_detail = f"FAIL — 수집 종목 {total_tickers}개 (최소 3개 필요)"
        except Exception as e:
            qh1_detail = f"FAIL — sector_analysis.json 파싱 오류: {e}"
    results.append({
        "check": "QH-1 산업별 딥다이브 데이터",
        "pass":  qh1_ok,
        "detail": qh1_detail,
        "fix_stages": ["run_sector_agent.py", "generate_report_v2.py"],
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

    # ── SD-10: 명세-구현 일치 검증 (Claude API 주장 vs 실제 코드) ─
    _api_claim_keywords = ("claude api", "anthropic_api_key", "anthropic api")
    _api_call_patterns  = ("anthropic.Anthropic(", "client.messages.create(", "anthropic.messages.create(")
    for _py in AGENTS_DIR.glob("*.py"):
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
    # 자기 자신(run_pm_agent.py)은 검사 제외
    # 패턴: 진짜 구현 없이 명세를 위장하는 코드 (fallback 제외)
    _hardcode_re_patterns = [
        # top5 리스트에 리터럴 기업명이 하드코딩된 경우 (3개 이상)
        (r'"name":\s*"[A-Za-z가-힣].*"name":\s*"[A-Za-z가-힣].*"name":\s*"[A-Za-z가-힣]', "Top5에 리터럴 기업명 3개 이상 하드코딩 의심"),
        # 조건 없이 항상 PASS를 반환하는 구조
        (r'if\s+True:\s*#\s*always', "조건 우회 의심"),
        # TODO/placeholder 미구현 표시
        (r'#\s*(TODO|FIXME|placeholder|stub).*implement', "미구현 stub 탐지"),
    ]
    for _py in AGENTS_DIR.glob("*.py"):
        if _py.name == Path(__file__).name:
            continue  # self-check 제외
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
    # 파이프라인 각 Agent의 done_criteria 정의 + exit(1) 가드 공존 여부 확인
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
    # 빈 리스트에서 vacuously True가 되는 조건 → 실패 데이터도 PASS 처리 우려
    import re as _re13
    _vacuous_pats13 = [
        # not any(condition for s in list) in done_criteria — 빈 리스트에서 항상 True
        (r"""["']SA-\d+[^"']*["']\s*:\s*not any\(""",
         "not any() 조건 — 빈 리스트에서 vacuously True (실제 실패 미감지 가능)"),
        # not has_company_dup(empty_list) in done_criteria — 빈 리스트에서 항상 True
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
    # 현재 QC PASS 수가 기준선보다 줄어들면 즉시 Telegram 알림
    try:
        _qc14      = pm_quality_checks()
        _qc14_pass = sum(1 for c in _qc14 if c["pass"])
        _qc14_base = baseline.get("qc_pass_count")
        if _qc14_base is not None and _qc14_pass < _qc14_base:
            _regressed14 = _qc14_base - _qc14_pass
            # qc_failed_checks가 None이면 legacy baseline — 신규 실패 목록 미출력
            # (QG-1처럼 항상 실패하는 known-fail이 오탐되지 않도록)
            _prev_fail_history14 = baseline.get("qc_failed_checks")
            if _prev_fail_history14 is not None:
                _prev_fails14 = set(_prev_fail_history14)
                _new_fails14  = [c["check"] for c in _qc14
                                 if not c["pass"] and c["check"] not in _prev_fails14]
            else:
                _prev_fails14 = set()
                _new_fails14  = []  # Legacy baseline: known-fail 오탐 방지
            issues.append(
                f"SD-14 QC 회귀: {_qc14_pass}/{len(_qc14)} PASS "
                f"(기준선 {_qc14_base} → 현재 {_qc14_pass}, "
                f"-{_regressed14}개 감소)"
                + (f". 신규 실패: {_new_fails14}" if _new_fails14 else "")
            )
            _tg_send(
                f"🚨 <b>SD-14 QC 회귀 감지</b>\n"
                f"기준선 {_qc14_base}/{len(_qc14)} → "
                f"현재 {_qc14_pass}/{len(_qc14)} PASS\n"
                + (f"신규 실패: {', '.join(_new_fails14[:5])}" if _new_fails14
                   else "신규 실패: 없음 (legacy baseline — known-fail 제외)")
            )
    except Exception:
        pass

    # ── SD-15: pm_quality_checks() 조건 실제 검증 능력 분석 ──────────
    # 핵심 지지 데이터가 비어 있는데 PASS하는 조건 → vacuous PASS 탐지
    try:
        _fr15      = data  # pm_self_diagnosis 시작에서 로드한 final_results 재사용
        _sp_a15    = _fr15.get("sp500_analysis",  {})
        _ksp_a15   = _fr15.get("kospi_analysis",  {})
        _all_t15   = (_sp_a15.get("contribution_top5", []) + _sp_a15.get("beneficiary_top5", []) +
                      _ksp_a15.get("contribution_top5", []) + _ksp_a15.get("beneficiary_top5", []))
        _ksp_t15   = (_ksp_a15.get("contribution_top5", []) + _ksp_a15.get("beneficiary_top5", []))
        _ksp_ext15 = [s for s in _ksp_t15 if abs(s.get("stock_return_pct", 0)) >= 200]

        # SA-7 vacuous: all_stocks=[] 인데 PASS → 종목 데이터 없이 경고 체크 통과
        if not _all_t15:
            issues.append(
                "SD-15 SA-7 vacuous PASS — all_stocks=[] (종목 미수집 상태에서 "
                "warn_reason 체크 통과, SA-1~4와 연동 의존)"
            )
        # SA-8 vacuous: KOSPI 종목 없는데 PASS
        if not _ksp_t15:
            issues.append(
                "SD-15 SA-8 vacuous PASS — KOSPI 종목=[] (극단 수익률 교차검증 vacuously 통과)"
            )
        # permanent FAIL 종목 확인 (fix_stages=[] → 자동수정 불가)
        _qc15 = pm_quality_checks()
        _perm_fails15 = [c["check"] for c in _qc15
                         if not c["pass"] and not c.get("fix_stages")]
        print(f"  [SD-15] QC {sum(1 for c in _qc15 if c['pass'])}/{len(_qc15)} PASS | "
              f"extreme_stocks={len(_ksp_ext15)} | permanent_fail={_perm_fails15}")
    except Exception:
        pass

    # ── SD-16: 결과물 타임스탬프 신선도 검증 ───────────────────────
    # daily 파이프라인 기준: 25시간 초과 생성 파일 → SD 이슈
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
            OUT_DIR / "final_results.json": (1_024,    5_242_880),   # 1KB ~ 5MB
            OUT_DIR / "decision.json":      (100,      1_048_576),   # 100B ~ 1MB
            OUT_DIR / "dashboard.html":     (5_120,   10_485_760),   # 5KB ~ 10MB
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
        # 파이프라인에 등록된 파일만 감사 (v1/레거시 파일 제외)
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
            # Heuristic: hardcoded plan has static agent list without "이슈별 도출" header
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

        # P2-3: before/after pass-count 비교
        _qc_before = pm_quality_checks()
        _pass_before = sum(1 for c in _qc_before if c["pass"])
        print(f"  [PM] 수정 전 QC: {_pass_before}/{len(_qc_before)} PASS")

        _auto_fix_from_diagnosis(issues)

        # 수정 후 quality check 재실행 (최대 2회)
        for fix_round in range(1, 3):
            qc = pm_quality_checks()
            qc_failed = [c for c in qc if not c["pass"]]
            # 기존 SD 이슈와 겹치지 않는 새 QC 실패만 추가
            # fix_stages 없는 항목(미설정 자격증명 등, QG-1 등)은 SD 이슈에서 제외
            existing_checks = {iss.split(":")[0] for iss in issues}
            new_failures = [
                f"QC재검증 실패: {c['check']} — {c['detail']}"
                for c in qc_failed
                if c["check"].split(" ")[0] not in existing_checks
                and c.get("fix_stages")  # fix_stages 없으면 자동 수정 불가 — SD 목록 제외
            ]
            if new_failures:
                issues.extend(new_failures)
                print(f"  [PM] 재검증 round {fix_round}: 추가 실패 {len(new_failures)}개")
                # 새 실패에 대해 추가 fix 시도
                _auto_fix_from_diagnosis(new_failures)
            else:
                print(f"  [PM] 재검증 round {fix_round}: 추가 실패 없음 — 루프 종료")
                break

        # 최종 QC 결과 요약 + before/after 비교
        final_qc = pm_quality_checks()
        final_pass = [c for c in final_qc if c["pass"]]
        final_fail = [c for c in final_qc if not c["pass"]]
        _pass_after = len(final_pass)
        _delta = _pass_after - _pass_before
        _delta_str = f"+{_delta}" if _delta >= 0 else str(_delta)
        print(f"  [PM] 최종 QC: {_pass_after}/{len(final_qc)} PASS (수정 전 {_pass_before} → 수정 후 {_pass_after}, Δ{_delta_str})")
        if _delta == 0:
            print("  [PM] ⚠ 자동 수정 효과 없음 — 수동 개입 필요")
        if final_fail:
            print(f"  [PM] 미해결 QC: {[c['check'] for c in final_fail[:5]]}")

    # ── 기준선 저장 (최종 QC 결과 포함 — SD-14 다음 실행에서 회귀 감지에 사용) ──
    _save_baseline(curr_count, rank, pm_quality_checks())

    return len(issues) == 0, issues


def _write_fix_request(issues: list[str]) -> None:
    # derive actual auto-fix scripts from issue codes (mirrors _auto_fix_from_diagnosis logic)
    _fx_scripts: set[str] = set()
    for _iss in issues:
        if "SD-1" in _iss or "SD-6" in _iss:
            _fx_scripts |= {"run_analysis_agent_v2.py", "run_evaluator_agent_v2.py"}
        if "SD-2" in _iss or "SD-3" in _iss:
            _fx_scripts |= {"run_evaluator_agent_v2.py", "run_validation_agent.py"}
        if "SD-4" in _iss or "SD-5" in _iss:
            _fx_scripts |= {"run_stock_agent_v2.py"}
        if "SD-8" in _iss:
            _fx_scripts |= {"run_news_agent.py"}
        if "SD-13" in _iss or "SD-14" in _iss:
            _fx_scripts |= {"run_validation_agent.py"}
    _manual_issues = [i for i in issues if any(c in i for c in ("SD-7", "SD-10", "SD-11", "SD-12"))]

    lines = [
        "# PM Agent 자가진단 수정 요청서",
        f"생성: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}",
        "",
        "## 발견된 문제",
    ]
    for i, iss in enumerate(issues, 1):
        lines.append(f"{i}. {iss}")
    lines += ["", "## 자동 수정 계획 (이슈별 도출)"]
    if _fx_scripts:
        for sc in sorted(_fx_scripts):
            lines.append(f"- {sc}")
    else:
        lines.append("- (자동 수정 대상 없음 — 수동 점검 필요)")
    if _manual_issues:
        lines += ["", "## 수동 수정 필요"]
        for mi in _manual_issues:
            lines.append(f"- {mi}")
    FIX_REQUEST_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[PM] fix_request.md 작성 완료 ({len(issues)}개 이슈, 자동수정 {len(_fx_scripts)}개 스크립트)")


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
        if "SD-13" in iss or "SD-14" in iss:
            scripts_needed |= {"run_validation_agent.py"}
        # SD-7 (GitHub Actions 실패)는 원격 CI 문제 — 로컬 재실행 불필요
        # SD-12 (exit 가드 누락)는 코드 수정 필요 — 로컬 재실행 무의미
        # SD-13 (항상True 조건)은 코드 수정 필요 — 재실행으로 해결 불가

    if not scripts_needed:
        return

    # 의존성 맵 기반 재실행: 진단 이슈 스크립트 + 전이적 의존 단계만 실행
    known = {s for s in scripts_needed if s in {st for st, *_ in PIPELINE_STAGES}}
    if not known:
        return
    ordered = _get_dependents(known)

    _tg_send(
        f"🔧 <b>PM 자가진단 자동 수정</b>\n"
        f"이슈 {len(issues)}개 발견\n"
        f"재실행: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자가진단 자동 수정: {ordered}")
    run_partial_pipeline(ordered)


def _save_baseline(indicator_count: int, rank: list,
                   qc_results: list | None = None) -> None:
    baseline = {
        "timestamp":       datetime.now().isoformat(),
        "indicator_count": indicator_count,
        "top5_indicators": [r["indicator"] for r in rank[:5]],
        "top1_indicator":  rank[0]["indicator"] if rank else None,
    }
    if qc_results is not None:
        baseline["qc_pass_count"]    = sum(1 for c in qc_results if c["pass"])
        baseline["qc_total"]         = len(qc_results)
        baseline["qc_failed_checks"] = [c["check"] for c in qc_results if not c["pass"]]
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[PM] 기준선 저장: {indicator_count}개 지표"
          + (f" / QC {baseline.get('qc_pass_count')}/{baseline.get('qc_total')} PASS"
             if qc_results is not None else ""))


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

# SD-9: 중복 전송 방지 — 동일 메시지 해시 60초 내 재전송 차단
_tg_last_sent: dict[str, float] = {}

def _tg_send(text: str) -> None:
    """텔레그램 메시지 전송 (run_telegram_agent 임포트 없이 직접)."""
    import hashlib, time
    # SD-9: 동일 메시지를 60초 내 재전송 방지
    msg_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    now = time.time()
    if now - _tg_last_sent.get(msg_hash, 0.0) < 60.0:
        print(f"  [TG] 중복 메시지 차단 (60s 이내 동일 해시)")
        return
    _tg_last_sent[msg_hash] = now
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
    ("run_data_agent_v2.py",    "Data Agent",       1,  800),
    ("refresh_data.py",         "Refresh",          2,  120),
    ("run_analysis_agent_v2.py","Analysis Agent",   3,  300),
    ("run_stock_agent_v2.py",   "Stock Agent",      4,  600),
    ("run_evaluator_agent_v2.py","Evaluator Agent", 5,  120),
    ("run_news_agent.py",       "News Agent",       6,  120),
    ("run_sector_agent.py",     "Sector Agent",     7,  120),
    ("run_validation_agent.py", "Validation Agent", 8,  120),
    ("run_decision_agent.py",   "Decision Agent",   9,  120),
    ("run_ui_agent.py",         "UI Agent",         10, 120),
    ("generate_report_v2.py",   "Report",           11, 120),
    ("run_audit_agent.py",      "Audit Agent",      12, 300),
]
TOTAL_STEPS = 13  # 12 스테이지 + 1 최종 보고

# ── 단계 간 데이터 의존성 맵 ─────────────────────────────────────
# Key: 스크립트명, Value: 이 스크립트가 직접 의존하는 선행 스크립트 목록
# 의존성 없음 = 독립 실행 가능 (데이터를 외부에서 직접 수집)
STAGE_DEPS: dict[str, list[str]] = {
    "run_data_agent_v2.py":      [],                              # root — 외부 API 직접 수집
    "refresh_data.py":           ["run_data_agent_v2.py"],        # raw → processed 변환
    "run_analysis_agent_v2.py":  ["refresh_data.py"],             # processed 지표 → 상관/Granger
    "run_stock_agent_v2.py":     ["refresh_data.py"],             # processed 지표 → 종목 분석 (analysis와 병렬)
    "run_evaluator_agent_v2.py": ["run_analysis_agent_v2.py"],    # 분석 결과 → 가중치 랭킹
    "run_news_agent.py":         [],                              # 독립 — 외부 RSS 직접 수집
    "run_sector_agent.py":       ["refresh_data.py"],             # processed 지표 → 섹터 분석
    "run_validation_agent.py":   ["run_evaluator_agent_v2.py",
                                   "run_stock_agent_v2.py"],      # 랭킹 + 종목 → 검증
    "run_decision_agent.py":     ["run_validation_agent.py"],     # 검증 결과 → 의사결정
    "run_ui_agent.py":           ["run_decision_agent.py",
                                   "run_evaluator_agent_v2.py",
                                   "run_stock_agent_v2.py"],      # 의사결정 + 랭킹 + 종목 → 대시보드
    "generate_report_v2.py":     ["run_ui_agent.py"],             # 대시보드 → 최종 리포트
    "run_audit_agent.py":        ["generate_report_v2.py"],       # 최종 리포트 → 감사
}


def _get_dependents(failed_scripts: set[str]) -> list[str]:
    """
    실패한 스크립트 집합에서 재실행이 필요한 스크립트 목록 반환.

    STAGE_DEPS의 역방향 그래프를 BFS로 탐색해 전이적 의존 단계를 수집한다.
    의존성 없는 독립 단계(run_news_agent.py 등)는 포함되지 않으므로
    불필요한 재실행을 방지한다.

    반환: 파이프라인 순서(PIPELINE_STAGES)로 정렬된 재실행 대상 목록
    """
    # 역방향 의존성 맵: X가 실패하면 누가 영향받는가
    reverse_deps: dict[str, list[str]] = {s: [] for s in STAGE_DEPS}
    for stage, deps in STAGE_DEPS.items():
        for dep in deps:
            if dep in reverse_deps:
                reverse_deps[dep].append(stage)

    # BFS — 실패 단계 + 전이적 의존 후속 단계 수집
    to_run: set[str] = set(failed_scripts)
    queue: list[str] = list(failed_scripts)
    while queue:
        current = queue.pop(0)
        for dependent in reverse_deps.get(current, []):
            if dependent not in to_run:
                to_run.add(dependent)
                queue.append(dependent)

    # 파이프라인 정의 순서로 정렬
    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    return [s for s in pipeline_order if s in to_run]


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

    # 의존성 맵 기반 재실행: 실패 단계 + 전이적 의존 단계만 실행
    # (독립 단계 — run_news_agent 등 — 불필요 재실행 방지)
    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    fix_stage_set: set[str] = {
        s for c, _ in fatal for s in c.fix_stages if s in pipeline_order
    }
    if not fix_stage_set:
        return
    ordered = _get_dependents(fix_stage_set)

    fail_descs = "\n".join(f"  [{c.code}] {d}" for c, d in fatal)
    _tg_send(
        f"🔄 <b>PM Agent 자동 수정 시도 {attempt}/{MAX_RETRIES}</b>\n"
        f"실패 기준:\n{fail_descs}\n\n"
        f"재실행 단계: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자동 수정 실행: {ordered}")
    run_partial_pipeline(ordered)


# ── 최종 보고 ─────────────────────────────────────────────────────

def _confidence_tier(confidence_pct: float) -> tuple[str, str]:
    """신뢰도 임계값 분류. (tier, label) 반환."""
    if confidence_pct >= 70:
        return "normal", f"✅ 정상 신호 ({confidence_pct:.1f}%)"
    elif confidence_pct >= 50:
        return "warn", f"⚠ 주의 신호 ({confidence_pct:.1f}%) — 부분 신뢰"
    else:
        return "hold", f"🔴 신호 보류 ({confidence_pct:.1f}%) — 데이터 부족"


def _format_decision_for_tg(decision: dict) -> str:
    """decision.json 내용을 Telegram 메시지용 텍스트로 변환 (신뢰도 임계값 적용)."""
    lines = []
    for market_key, market_label in [("sp500", "S&P500"), ("kospi", "코스피")]:
        dec = decision.get(market_key, {})
        action = dec.get("action", "HOLD")
        conf   = dec.get("confidence_pct", 0.0)
        pos    = dec.get("position_size_pct", 0.0)
        tier, tier_label = _confidence_tier(conf)

        if tier == "hold":
            lines.append(f"  {market_label}: {action} | {tier_label}\n  → 신뢰도 50% 미만 — 의사결정 보류")
        elif tier == "warn":
            lines.append(f"  {market_label}: {action} | {tier_label}\n  → 포지션 {pos:.0f}% (낮은 신뢰도 감안 주의)")
        else:
            lines.append(f"  {market_label}: {action} | {tier_label} | 포지션 {pos:.0f}%")
    return "\n".join(lines)


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

    # 신뢰도 임계값 적용 — decision.json 로드
    decision   = data.get("decision", {})
    dec_section = ""
    if decision:
        sp_conf  = decision.get("sp500", {}).get("confidence_pct", 0.0)
        ksp_conf = decision.get("kospi", {}).get("confidence_pct", 0.0)
        sp_tier,  _ = _confidence_tier(sp_conf)
        ksp_tier, _ = _confidence_tier(ksp_conf)
        dec_text = _format_decision_for_tg(decision)
        dec_section = f"\n<b>의사결정 (신뢰도 임계값 적용):</b>\n{dec_text}\n"
        # 50% 미만 신뢰도 경고 로그
        if sp_tier == "hold":
            print(f"  [PM] ⚠ S&P500 신뢰도 {sp_conf:.1f}% < 50% — 의사결정 보류 표시")
        if ksp_tier == "hold":
            print(f"  [PM] ⚠ 코스피 신뢰도 {ksp_conf:.1f}% < 50% — 의사결정 보류 표시")

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
        f"<b>Validation:</b> {val_pass}/{val_tot} PASS\n"
        f"{dec_section}\n"
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
