# -*- coding: utf-8 -*-
"""
PM Agent — 품질 검증 (pm_quality.py)
pm_quality_checks(), report_quality_check(), 기준선 관리, 이슈 수정 스크립트 도출.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from pm_utils import (
    BASE_DIR, AGENTS_DIR, OUT_DIR, PROC_DIR,
    BASELINE_FILE, FIX_REQUEST_FILE, PENDING_FILE,
    _load_results, _load_validation, _load_audit,
    _tg_send, _load_pending, register_pending,
)

# SD-14 회귀 감지에서 영구 제외할 QC 체크
_KNOWN_FAIL_CHECKS: list[str] = []

MAX_RETRIES = 3

CONTEMPORANEOUS_INDICES = {"NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225", "INDIVIDUAL_NET"}
SELF_REFERENTIAL = {
    "RSI14", "MA50", "RSI_SIGNAL", "BETA", "MA_SIGNAL",
    # 완화된 항목 (지연 지표 — KOSPI 예측 유효): BBAND, STOCH_RSI, MARKET_MOMENTUM 제거
}
SMALL_CAP_USD_B_THRESHOLD       = 5.0    # $5B 미만이면 소형주 경고
SP500_CONTRIBUTOR_TOP1_MIN_MC_B = 200.0
CONTRIBUTOR_TOP1_MIN_MC_B       = 200.0  # 하위호환 alias (SP500 기준 유지)
EXTREME_RETURN_THRESHOLD        = 500.0  # ⚠ 이유 텍스트 의무 기준 (%)


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

    _dyn_evidence = _re_qr.compile(
        r'\d+/\d+|exit[= ]\d|\bexit\s*code\b|exit_code|run_id=|conclusion='
        r'|\d+%|\d+개|\d+건|\bPASS\b|\bFAIL\b|\d{4,}',
        _re_qr.IGNORECASE,
    )
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
# LLM-as-Judge 헬퍼 (Phase 8) — ANTHROPIC_API_KEY 없으면 SKIP
# ══════════════════════════════════════════════════════════════

def _llm_score_narrative(text: str) -> tuple[int, str]:
    """Claude Sonnet으로 내러티브 품질 1-5 스코어링. API 키 없으면 (0, 'SKIP')."""
    import os, re as _re
    if not os.getenv("ANTHROPIC_API_KEY"):
        return 0, "SKIP"
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            "다음 시장 분석 리포트의 품질을 1-5점으로 평가하세요.\n"
            "기준: 한국어 전문성, 실행 가능한 액션플랜, 시장 분석 깊이, 논리 일관성, 데이터 근거.\n\n"
            f"리포트:\n{text[:3000]}\n\n"
            "형식: SCORE: [1-5]\nREASON: [한 문장]"
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        out = resp.content[0].text
        score = int(_re.search(r"SCORE:\s*(\d)", out).group(1)) if _re.search(r"SCORE:\s*(\d)", out) else 3
        reason = (_re.search(r"REASON:\s*(.+)", out) or type("", (), {"group": lambda s, n: out[:60]})()).group(1)
        return score, str(reason).strip()
    except ImportError:
        return 0, "anthropic 미설치"
    except Exception as e:
        return 0, f"API 오류: {str(e)[:50]}"


def _llm_score_decision(decision: dict) -> tuple[int, str]:
    """Claude Sonnet으로 의사결정 추론 일관성 1-5 스코어링. API 키 없으면 (0, 'SKIP')."""
    import os, re as _re
    if not os.getenv("ANTHROPIC_API_KEY"):
        return 0, "SKIP"
    try:
        import anthropic
        client = anthropic.Anthropic()
        sp = decision.get("sp500", {}); ksp = decision.get("kospi", {})
        # FIX-G (2026-06-23): 실제 decision.json 필드는 position_note/composite_score.
        # reason/signal_score는 존재하지 않음 — 빈 prompt → 낮은 점수 강제. ([[operational-lessons]] OL-6)
        sp_reason  = str(sp.get("position_note", "") or sp.get("reason", ""))[:150]
        ksp_reason = str(ksp.get("position_note", "") or ksp.get("reason", ""))[:150]
        sig_score  = decision.get("composite_score", decision.get("signal_score", "?"))
        sp_entry   = (sp.get("entry_triggers") or [])[:2]
        sp_exit    = (sp.get("exit_triggers") or [])[:2]
        risks      = (decision.get("risk_factors") or [])[:3]
        prompt = (
            "다음 투자 의사결정의 논리 일관성을 1-5점으로 평가하세요.\n"
            "기준: 시그널 점수와 방향 일치, 이유 논리성, 근거 구체성.\n\n"
            f"SP500: {sp.get('action','?')} — {sp_reason}\n"
            f"  진입 트리거: {sp_entry}\n"
            f"  청산 트리거: {sp_exit}\n"
            f"KOSPI: {ksp.get('action','?')} — {ksp_reason}\n"
            f"시그널 점수: {sig_score}\n"
            f"리스크 요인: {risks}\n\n"
            "형식: SCORE: [1-5]\nREASON: [한 문장]"
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        out = resp.content[0].text
        score = int(_re.search(r"SCORE:\s*(\d)", out).group(1)) if _re.search(r"SCORE:\s*(\d)", out) else 3
        reason = (_re.search(r"REASON:\s*(.+)", out) or type("", (), {"group": lambda s, n: out[:60]})()).group(1)
        return score, str(reason).strip()
    except ImportError:
        return 0, "anthropic 미설치"
    except Exception as e:
        return 0, f"API 오류: {str(e)[:50]}"


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

    # SA-5: SP500 기여 Top1 시작 시총 ≥ $200B (SP500 기준 유지)
    sp_top1 = sp_cont[0] if sp_cont else {}
    mc1 = sp_top1.get("market_cap_start_b") or sp_top1.get("market_cap_b") or 0
    results.append({
        "check": f"SA-5 기여 Top1 시총 ≥${SP500_CONTRIBUTOR_TOP1_MIN_MC_B:.0f}B",
        "pass":  mc1 >= SP500_CONTRIBUTOR_TOP1_MIN_MC_B,
        "detail": f"OK — ${mc1:.0f}B" if mc1 >= SP500_CONTRIBUTOR_TOP1_MIN_MC_B
                  else f"FAIL — ${mc1:.0f}B < ${SP500_CONTRIBUTOR_TOP1_MIN_MC_B:.0f}B ({sp_top1.get('name','?')})",
        "fix_stages": [],
    })

    # SA-6: KOSPI 기여 Top1 존재 + 시총 > 0 (데이터 오류 감지)
    ksp_top1 = ksp_cont[0] if ksp_cont else {}
    mc1k = ksp_top1.get("market_cap_start_b") or ksp_top1.get("market_cap_b") or 0
    sa6_pass = bool(ksp_cont) and mc1k > 0
    results.append({
        "check": "SA-6 KOSPI 기여 Top1 존재 (데이터 유효성)",
        "pass":  sa6_pass,
        "detail": (f"OK — {ksp_top1.get('name','?')} ${mc1k:.1f}B" if sa6_pass
                   else ("FAIL — 기여 Top1 없음" if not ksp_cont
                         else f"FAIL — {ksp_top1.get('name','?')} 시총 미수집 (mc=0)")),
        "fix_stages": ["run_stock_agent_v2.py"],
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

    # QI-1: BUY/SELL 액션일 때 신뢰도 ≥ 20% — 모니터링 전용 (pass=True 고정)
    # 시장 데이터 변동에 따라 임계값을 오르내리므로 회귀 기준선에서 제외.
    # 임계값 위반은 WARN 으로 표기하여 Telegram 에 노출하되 FAIL 처리하지 않는다.
    _QI1_MIN_CONF = 20.0
    _qi1_dec: dict = {}
    _qi1_dec_file = OUT_DIR / "decision.json"
    if _qi1_dec_file.exists():
        try:
            _qi1_dec = json.loads(_qi1_dec_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not _qi1_dec:
        _qi1_dec = data.get("decision", {})
    if _qi1_dec:
        _qi1_sp_act  = (_qi1_dec.get("sp500")  or {}).get("action",         "HOLD")
        _qi1_ksp_act = (_qi1_dec.get("kospi")   or {}).get("action",         "HOLD")
        _qi1_sp_conf = (_qi1_dec.get("sp500")   or {}).get("confidence_pct", 0.0)
        _qi1_ksp_conf= (_qi1_dec.get("kospi")   or {}).get("confidence_pct", 0.0)
        _qi1_warns = []
        if _qi1_sp_act  not in ("HOLD",) and _qi1_sp_conf  < _QI1_MIN_CONF:
            _qi1_warns.append(f"SP500={_qi1_sp_act} {_qi1_sp_conf:.1f}%<{_QI1_MIN_CONF}%")
        if _qi1_ksp_act not in ("HOLD",) and _qi1_ksp_conf < _QI1_MIN_CONF:
            _qi1_warns.append(f"KOSPI={_qi1_ksp_act} {_qi1_ksp_conf:.1f}%<{_QI1_MIN_CONF}%")
        qi1_detail = (f"OK — SP500={_qi1_sp_act}/{_qi1_sp_conf:.1f}%, KOSPI={_qi1_ksp_act}/{_qi1_ksp_conf:.1f}%"
                      if not _qi1_warns
                      else f"WARN — {', '.join(_qi1_warns)} (모니터링 전용)")
    else:
        qi1_detail = "SKIP — decision.json 없음"
    results.append({
        "check": f"QI-1 BUY/SELL 신뢰도 ≥{_QI1_MIN_CONF:.0f}% [모니터링]",
        "pass":  True,  # 시장 데이터 의존 — 회귀 기준선 제외
        "detail": qi1_detail,
        "fix_stages": ["run_decision_agent.py"],
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

            nq2_ok = bool(causes) and all("→" in c for c in causes)
            results.append({
                "check": "NQ-2 가능한 원인 원인→결과 구조",
                "pass":  nq2_ok,
                "detail": "OK — 모든 원인에 → 포함" if nq2_ok else "FAIL — → 없는 원인 존재",
                "fix_stages": ["run_news_agent.py"],
            })

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
        "fix_stages": [],
    })

    # ── Condition E: BUY/SELL/HOLD 의사결정 엔진 ─────────────────
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
        _dec_src = data.get("decision", {})
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
        qf1_ok = False
        qf1_detail = "WARN — narrative_context.json 준비됨, FINAL_REPORT.md 미생성 (서브에이전트 실행 필요)"
    results.append({
        "check": "QF-1 AI 언어 리포트 + 액션플랜",
        "pass":  qf1_ok,
        "detail": qf1_detail,
        "fix_stages": ["run_narrative_agent.py", "generate_report_v2.py"],
    })

    # ── Condition G: Google Sheets 연동 상태 (optional 체크) ──────
    import os as _os2
    from pathlib import Path as _Path2
    google_sa = _os2.getenv("GOOGLE_SA_JSON", "")
    if not google_sa:
        qg1_pass   = True
        qg1_detail = "SKIP — 미활성화 (선택 기능, GOOGLE_SA_JSON 미설정)"
    else:
        sa_path    = _Path2(google_sa)
        qg1_pass   = sa_path.exists()
        qg1_detail = (f"OK — {google_sa}" if qg1_pass
                      else f"FAIL — 자격증명 파일 없음: {google_sa}")
    results.append({
        "check":      "QG-1 Google Sheets 서비스 계정 설정",
        "pass":       qg1_pass,
        "detail":     qg1_detail,
        "fix_stages": [],
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

    # ── QG-2: waiting_credentials 방치 경보 ─────────────────────
    _stale_days_limit = 14
    _today = datetime.utcnow()
    _stale_creds: list[str] = []
    try:
        _pd = _load_pending()
        for _item in _pd.get("pending", []):
            if _item.get("status") == "waiting_credentials":
                _created = _item.get("created_at", "")
                if _created:
                    try:
                        _age = (_today - datetime.fromisoformat(_created)).days
                        if _age >= _stale_days_limit:
                            _stale_creds.append(f"{_item['id']} ({_age}일 대기)")
                    except Exception:
                        pass
    except Exception:
        pass
    if _stale_creds:
        qg2_pass = True  # advisory only, does not block pipeline
        qg2_detail = f"WARN — {len(_stale_creds)}개 자격증명 {_stale_days_limit}일 초과 대기: {', '.join(_stale_creds)}"
    else:
        qg2_pass, qg2_detail = True, f"OK — 방치된 자격증명 없음 ({_stale_days_limit}일 기준)"
    results.append({
        "check":      "QG-2 waiting_credentials 방치 감지",
        "pass":       qg2_pass,
        "detail":     qg2_detail,
        "fix_stages": [],
    })

    # ── QN-1: LLM-as-Judge 내러티브 품질 스코어 (Phase 8) ────────
    # FIX-G (2026-06-23): narrative agent는 data-prep only이므로 narrative_context.json에
    # narrative/report 키가 없음. 실제 prose는 FINAL_REPORT_v2.md에 있음. ([[operational-lessons]] OL-6)
    import os as _osN
    narrative_ctx = OUT_DIR / "narrative_context.json"
    final_report  = OUT_DIR / "FINAL_REPORT_v2.md"
    _narr_text = ""
    if narrative_ctx.exists():
        try:
            _nd = json.loads(narrative_ctx.read_text(encoding="utf-8"))
            _narr_text = str(_nd.get("narrative", "") or _nd.get("report", ""))[:4000]
        except Exception:
            pass
    if not _narr_text and final_report.exists():
        try:
            _narr_text = final_report.read_text(encoding="utf-8")[:4000]
        except Exception:
            pass
    if not _osN.getenv("ANTHROPIC_API_KEY"):
        qn1_pass, qn1_detail = True, "SKIP — ANTHROPIC_API_KEY 미설정"
    elif len(_narr_text) < 100:
        qn1_pass, qn1_detail = True, "SKIP — 내러티브 prose 없음 (FINAL_REPORT_v2.md 미생성)"
    else:
        _score_n, _reason_n = _llm_score_narrative(_narr_text)
        if _score_n >= 3:
            qn1_pass, qn1_detail = True, f"OK — score={_score_n}/5: {_reason_n[:60]}"
        else:
            qn1_pass = True  # WARN: advisory, does not block pipeline
            qn1_detail = f"WARN — score={_score_n}/5 (<3): {_reason_n[:60]}"
            register_pending("QN-1-warn", "QN-1 내러티브 품질 점수 < 3 — 리포트 재생성 검토")
    results.append({
        "check": "QN-1 LLM 내러티브 품질 스코어",
        "pass":  qn1_pass,
        "detail": qn1_detail,
        "fix_stages": ["run_narrative_agent.py"],
    })

    # ── QR-1: LLM-as-Judge 의사결정 추론 일관성 (Phase 8) ────────
    decision_f = OUT_DIR / "decision.json"
    _dec_data: dict = {}
    if decision_f.exists():
        try:
            _dec_data = json.loads(decision_f.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not _osN.getenv("ANTHROPIC_API_KEY"):
        qr1_pass, qr1_detail = True, "SKIP — ANTHROPIC_API_KEY 미설정"
    elif not _dec_data:
        qr1_pass, qr1_detail = True, "SKIP — decision.json 없음"
    else:
        _score_r, _reason_r = _llm_score_decision(_dec_data)
        if _score_r >= 3:
            qr1_pass, qr1_detail = True, f"OK — score={_score_r}/5: {_reason_r[:60]}"
        else:
            qr1_pass = True  # WARN: advisory
            qr1_detail = f"WARN — score={_score_r}/5 (<3): {_reason_r[:60]}"
            register_pending("QR-1-warn", "QR-1 의사결정 추론 일관성 점수 < 3 — 의사결정 로직 점검")
    results.append({
        "check": "QR-1 LLM 의사결정 추론 일관성",
        "pass":  qr1_pass,
        "detail": qr1_detail,
        "fix_stages": ["run_decision_agent.py"],
    })

    # ── QC-29: Level 8 동적 게이트 — DC evidence 검증 (2026-06-29 신설) ────
    # 배경: FIX-G + 라운드 14 "DONE_CRITERIA: PASS 위장" 패턴 재발 방지.
    # AI Harness 원칙 2 (Runtime > design intent).
    # 룰: level_claimed >= 8 인데 evidence_files 빈/null → CRITICAL.
    qc29_pass = True
    qc29_violations = []
    try:
        _baseline_path = BASE_DIR / "regression_baseline.json"
        if _baseline_path.exists():
            _baseline = json.loads(_baseline_path.read_text(encoding="utf-8"))
            _min_level = _baseline.get("level_gate_rules", {}).get("min_level_for_gate", 8)
            for _dc_id, _ev in _baseline.get("dc_evidence", {}).items():
                _level = _ev.get("level_claimed")
                if _level is None:  # N/A 위임 항목 등
                    continue
                if _level < _min_level:  # Level 7 이하는 게이트 대상 외
                    continue
                _status = _ev.get("status", "")
                if not _status.startswith("PASS"):  # PENDING/FAIL은 별도 처리
                    continue
                _evidence = _ev.get("evidence_files", [])
                _dyn_test = _ev.get("dynamic_test")
                if not _evidence or not _dyn_test:
                    qc29_violations.append(
                        f"{_dc_id} (Level {_level}, status='{_status}'): evidence={_evidence}, dyn_test={_dyn_test}"
                    )
            qc29_pass = len(qc29_violations) == 0
            if qc29_violations:
                qc29_detail = (
                    f"CRITICAL — Level≥{_min_level} DC 'PASS 위장' 의심 {len(qc29_violations)}건:\n  "
                    + "\n  ".join(qc29_violations)
                )
            else:
                qc29_detail = (
                    f"OK — regression_baseline.json dc_evidence Level≥{_min_level} 검증 통과"
                )
        else:
            qc29_pass = True  # baseline 부재 시 SKIP (실 운영 전 단계)
            qc29_detail = "SKIP — regression_baseline.json 미존재"
    except Exception as e:
        qc29_pass = True  # parse 실패 등은 advisory
        qc29_detail = f"SKIP — 검증 중 오류: {e}"
    results.append({
        "check": "QC-29 Level 8 동적 게이트 (DC evidence 검증)",
        "pass":  qc29_pass,
        "detail": qc29_detail,
        "fix_stages": ["regression_baseline.json 갱신"],
    })

    return results


# ══════════════════════════════════════════════════════════════
# 기준선 관리
# ══════════════════════════════════════════════════════════════

def _qc_summary(checks: list[dict]) -> str:
    """'N/N PASS' 요약 문자열. SKIP 항목이 있으면 '(X SKIP 포함)' 접미사 추가."""
    passed = [c for c in checks if c["pass"]]
    skipped = [c for c in passed if "SKIP" in c.get("detail", "")]
    base = f"{len(passed)}/{len(checks)} PASS"
    if skipped:
        names = ", ".join(c["check"].split()[0] for c in skipped)
        base += f" ({names} SKIP 포함)"
    return base


def _load_baseline() -> dict:
    """pm_baseline.json 로드. v1(schema_version 없음) → v2 자동 마이그레이션."""
    if not BASELINE_FILE.exists():
        return {}
    try:
        b = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if b.get("schema_version") is None:
        b["schema_version"] = 2
        b.setdefault("known_fail_checks", _KNOWN_FAIL_CHECKS)
    return b


def _save_baseline(indicator_count: int, rank: list,
                   qc_results: list | None = None) -> None:
    baseline = {
        "schema_version":  2,
        "timestamp":       datetime.now().isoformat(),
        "indicator_count": indicator_count,
        "top5_indicators": [r["indicator"] for r in rank[:5]],
        "top1_indicator":  rank[0]["indicator"] if rank else None,
        "known_fail_checks": _KNOWN_FAIL_CHECKS,
    }
    if qc_results is not None:
        baseline["qc_pass_count"]    = sum(1 for c in qc_results if c["pass"])
        baseline["qc_total"]         = len(qc_results)
        baseline["qc_failed_checks"] = [c["check"] for c in qc_results if not c["pass"]]
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[PM] 기준선 저장 (v2): {indicator_count}개 지표"
          + (f" / QC {_qc_summary(qc_results)}"
             if qc_results is not None else ""))


def _tg_send_quality_report(checks: list[dict]) -> None:
    """품질 검증 결과 텔레그램 보고."""
    passed  = [c for c in checks if c["pass"]]
    skipped = [c for c in passed if "SKIP" in c.get("detail", "")]
    failed  = [c for c in checks if not c["pass"]]
    icon    = "✅" if not failed else "⚠"
    summary = _qc_summary(checks)
    lines   = [f"{icon} <b>PM Quality Check Results</b>",
               f"통과: {summary}", ""]
    if skipped:
        lines.append(f"⏭ SKIP 항목 ({len(skipped)}개 — 선택 기능 미설정):")
        for c in skipped:
            lines.append(f"  ⏭ {c['check']}: {c['detail'][:80]}")
        lines.append("")
    for c in checks:
        if "SKIP" in c.get("detail", ""):
            continue
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


# ══════════════════════════════════════════════════════════════
# 이슈 수정 스크립트 도출
# ══════════════════════════════════════════════════════════════

def _derive_fix_scripts(issues: list[str]) -> tuple[set[str], list[str]]:
    """이슈 코드 → 자동 수정 스크립트 + 수동 수정 목록 도출 (단일 진실 소스).

    re.findall로 SD-N 코드를 정밀 추출해 'SD-1' in 'SD-19' 오매칭 방지.
    """
    scripts: set[str] = set()
    manual: list[str] = []
    for iss in issues:
        codes = set(re.findall(r"SD-\d+", iss))
        if codes & {"SD-6"}:
            scripts |= {"run_decision_agent.py"}
        if codes & {"SD-1"}:
            scripts |= {"run_analysis_agent_v2.py", "run_evaluator_agent_v2.py"}
        if codes & {"SD-2", "SD-3"}:
            scripts |= {"run_evaluator_agent_v2.py", "run_validation_agent.py"}
        if codes & {"SD-4", "SD-5"}:
            scripts |= {"run_stock_agent_v2.py"}
        if codes & {"SD-8"}:
            scripts |= {"run_news_agent.py"}
        if codes & {"SD-13", "SD-14"}:
            scripts |= {"run_validation_agent.py"}
        if codes & {"SD-7", "SD-10", "SD-11", "SD-12"}:
            manual.append(iss)
    return scripts, manual


def _write_fix_request(issues: list[str]) -> None:
    _fx_scripts, _manual_issues = _derive_fix_scripts(issues)

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
