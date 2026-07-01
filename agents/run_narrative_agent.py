# -*- coding: utf-8 -*-
"""
Narrative Agent — 데이터 준비 전용
PM Condition F: final_results.json 읽기 → narrative_context.json 저장

역할 분리:
  이 스크립트  = 데이터 추출 + 컨텍스트 구조화만 담당 (AI API 호출 없음)
  리포트 생성  = Claude Code /agent 서브에이전트가 narrative_context.json 읽고 FINAL_REPORT.md 작성

Done Criteria (NA-1~NA-3):
  NA-1: final_results.json 존재 + 필수 섹션 포함
  NA-2: narrative_context.json 저장 완료 (signal/decision/ranking/stocks 필드)
  NA-3: 컨텍스트 내 실제 수치 존재 (signal.score, 지표 Z-score 등)
"""
import utf8_setup  # noqa: F401

import json
import sys
from datetime import datetime
from pathlib import Path


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _register_dogfood_pending(base_dir: Path, ctx_path: Path) -> str:
    """Phase 11-A Path Z Group E 재정의 (2026-07-02, meta-audit 7차 확장).

    data-prep 완료 후 dogfood 상태 추적. FINAL_REPORT_v2.md 존재하면 pending
    sweep (Q5 gap fix), 없으면 pending 신규 등록.

    Behavior (Q5 sweeper 통합):
    - FINAL_REPORT_v2.md 존재 + pending 이 남아있음 → completed 로 sweep, 반환 "swept"
    - FINAL_REPORT_v2.md 존재 + pending 없음 → 반환 "skipped"
    - FINAL_REPORT_v2.md 부재 + 이미 등록됨 → 중복 방지, 반환 "already_registered"
    - FINAL_REPORT_v2.md 부재 + 미등록 → 신규 등록, 반환 "registered"
    - I/O 오류 → 파이프라인 차단 안 함 (advisory), 반환 "error"

    meta-audit 7차 Q5: pending → completed 이동 로직 도입 (기존 skip 만은 traceability gap).
    """
    final_report = base_dir / "output" / "FINAL_REPORT_v2.md"
    pending_path = base_dir / "pending_requests.json"
    req_id = "REQ-DOGFOOD-NARRATIVE"

    try:
        if pending_path.exists():
            data = json.loads(pending_path.read_text(encoding="utf-8"))
        else:
            data = {"updated": "", "completed": [], "pending": []}
        pending_list = data.get("pending", [])
        completed_list = data.get("completed", [])

        # sweeper: FINAL_REPORT 있으면 기존 pending 을 completed 로 이동
        if final_report.exists() and final_report.stat().st_size > 100:
            swept = False
            remaining = []
            for item in pending_list:
                if item.get("id") == req_id and item.get("status") == "pending":
                    item["status"] = "completed"
                    item["completed_at"] = datetime.now().isoformat(timespec="seconds")
                    item["completed_by"] = "dogfood_auto_detect (FINAL_REPORT_v2.md 감지)"
                    completed_list.append(item)
                    swept = True
                else:
                    remaining.append(item)
            if swept:
                data["pending"] = remaining
                data["completed"] = completed_list
                data["updated"] = datetime.now().isoformat(timespec="seconds")
                pending_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return "swept"
            return "skipped"

        # FINAL_REPORT 부재: 중복 방지 후 신규 등록
        for item in pending_list:
            if item.get("id") == req_id and item.get("status") == "pending":
                return "already_registered"

        pending_list.append({
            "id": req_id,
            "request": (
                "[Phase 11-A dogfood] narrative-agent subagent 로 "
                "output/FINAL_REPORT_v2.md 생성 필요"
            ),
            "status": "pending",
            "details": (
                f"data-prep 완료: {ctx_path.name}. "
                "다음 세션에서 Task(subagent_type='narrative-agent') 호출 지시. "
                "완료 후 audit-agent 가 산출물 품질 cross-check (자기 인증 회피)."
            ),
            "registered_at": datetime.now().isoformat(timespec="seconds"),
        })
        data["pending"] = pending_list
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        pending_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return "registered"
    except Exception as e:
        # advisory — 파이프라인 차단 안 함
        print(f"  [NA-4] pending 등록 실패 (advisory): {e}")
        return "error"


def _check_inputs(out_dir: Path) -> None:
    """Input contract: validate required files exist and have expected structure."""
    fr = out_dir / "final_results.json"
    if not fr.exists():
        print(f"INPUT_CONTRACT FAIL — final_results.json not found: {fr}")
        sys.exit(1)
    try:
        data = json.loads(fr.read_bytes().decode("utf-8"))
    except Exception as e:
        print(f"INPUT_CONTRACT FAIL — final_results.json parse error: {e}")
        sys.exit(1)
    for key in ("market_signal", "indicator_weight_ranking"):
        if key not in data:
            print(f"INPUT_CONTRACT FAIL — missing key in final_results.json: '{key}'")
            sys.exit(1)
    print(f"INPUT_CONTRACT PASS — final_results.json ({fr.stat().st_size}B) keys ok")


def build_narrative_context(results: dict) -> dict:
    """final_results.json → 서브에이전트용 구조화 컨텍스트."""
    signal   = results.get("market_signal", {})
    decision = results.get("decision", {})
    ranking  = results.get("indicator_weight_ranking", [])
    sp500    = results.get("sp500_analysis", {})
    kospi    = results.get("kospi_analysis", {})
    meta     = results.get("meta", {})

    period = meta.get("period", {})
    ind_sigs = signal.get("indicator_signals", [])

    # 지표 시그널 (Z-score + 가중치 포함)
    indicator_details = [
        {
            "indicator": s.get("indicator", ""),
            "z_score":   round(s.get("z_score", 0), 4),
            "weight":    round(s.get("weight", 0), 5),
            "bullish":   s.get("bullish", False),
        }
        for s in sorted(ind_sigs, key=lambda x: abs(x.get("z_score", 0)), reverse=True)
    ]

    # 가중치 Top5
    top5_ranking = [
        {
            "rank":             r.get("rank", i + 1),
            "indicator":        r.get("indicator", ""),
            "combined_weight":  round(r.get("combined_weight", 0), 5),
            "sp500_signed_r":   round(r.get("sp500_signed_r", 0), 4),
            "kospi_signed_r":   round(r.get("kospi_signed_r", 0), 4),
        }
        for i, r in enumerate(ranking[:5])
    ]

    # S&P500 Top5 기여/수혜
    sp_cont = [
        {
            "name":              s.get("name", ""),
            "stock_return_pct":  round(s.get("stock_return_pct", 0), 1),
            "contribution_score": round(s.get("contribution_score", 0), 3),
        }
        for s in (sp500.get("contribution_top5") or [])[:5]
    ]
    sp_ben = [
        {
            "name":           s.get("name", ""),
            "excess_return":  round(s.get("excess_return", 0), 1),
        }
        for s in (sp500.get("beneficiary_top5") or [])[:5]
    ]

    # KOSPI Top5 기여/수혜
    ksp_cont = [
        {
            "name":              s.get("name", ""),
            "stock_return_pct":  round(s.get("stock_return_pct", 0), 1),
            "contribution_score": round(s.get("contribution_score", 0), 3),
        }
        for s in (kospi.get("contribution_top5") or [])[:5]
    ]
    ksp_ben = [
        {
            "name":           s.get("name", ""),
            "excess_return":  round(s.get("excess_return", 0), 1),
        }
        for s in (kospi.get("beneficiary_top5") or [])[:5]
    ]

    sp_dec  = decision.get("sp500", {})
    ksp_dec = decision.get("kospi", {})

    return {
        "generated_at": datetime.now().isoformat(),
        "analysis_period": {
            "start": period.get("start", "?"),
            "end":   period.get("end",   "?"),
        },
        "signal": {
            "score":         signal.get("score", 50),
            "direction":     signal.get("direction", "neutral"),
            "bullish_count": signal.get("bullish_count", 0),
            "bearish_count": signal.get("bearish_count", 0),
            "total_signals": signal.get("total_signals", 0),
            "indicator_details": indicator_details,
        },
        "decision": {
            "sp500": {
                "action":           sp_dec.get("action", "HOLD"),
                "confidence_pct":   round(sp_dec.get("confidence_pct", 0), 1),
                "confidence_tier":  sp_dec.get("confidence_tier", "warn"),
                "position_size_pct": sp_dec.get("position_size_pct", 0),
            },
            "kospi": {
                "action":           ksp_dec.get("action", "HOLD"),
                "confidence_pct":   round(ksp_dec.get("confidence_pct", 0), 1),
                "confidence_tier":  ksp_dec.get("confidence_tier", "warn"),
                "position_size_pct": ksp_dec.get("position_size_pct", 0),
            },
            "risk_factors": decision.get("risk_factors", []),
        },
        "top5_ranking": top5_ranking,
        "sp500": {
            "contribution_top5": sp_cont,
            "beneficiary_top5":  sp_ben,
        },
        "kospi": {
            "contribution_top5": ksp_cont,
            "beneficiary_top5":  ksp_ben,
        },
    }


def generate_narrative(signal: dict, decision: dict, ranking: list,
                       sp500: dict, kospi: dict, meta: dict) -> dict:
    """UI Agent 호환성 함수: narrative.json(서브에이전트 생성) 우선, 없으면 기본 구조 반환."""
    import re as _re
    # 서브에이전트가 생성한 narrative.json 우선 사용
    base = Path(__file__).parent.parent / "output"
    narr_path = base / "narrative.json"
    if narr_path.exists():
        try:
            data = json.loads(narr_path.read_text(encoding="utf-8"))
            if data.get("market_overview"):
                return data
        except Exception:
            pass

    # 서브에이전트 미실행 — 컨텍스트에서 기본 구조 구성 (템플릿 없음, 수치만)
    period   = meta.get("period", {})
    score    = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    dir_map  = {"risk-on": "위험 선호", "neutral": "중립", "risk-off": "위험 회피"}
    dir_ko   = dir_map.get(direction, direction)
    bullish  = signal.get("bullish_count", 0)
    bearish  = signal.get("bearish_count", 0)
    total    = signal.get("total_signals", 0)

    sp_dec  = decision.get("sp500", {})
    ksp_dec = decision.get("kospi", {})
    sp_action  = sp_dec.get("action", "HOLD")
    ksp_action = ksp_dec.get("action", "HOLD")
    sp_conf    = sp_dec.get("confidence_pct", 0)
    risk_factors = decision.get("risk_factors", [])

    top_inds = [r.get("indicator", "") for r in ranking[:3]]
    today = datetime.now().strftime("%Y년 %m월 %d일")

    return {
        "generated_at":      datetime.now().isoformat(),
        "report_date":       today,
        "analysis_period":   f"{period.get('start','?')} ~ {period.get('end','?')}",
        "generation_method": "context_only",
        "market_overview":   f"복합 시그널 {score}/100 ({dir_ko}). 강세 {bullish}개 / 약세 {bearish}개 / 유효 {total}개. 상위 지표: {', '.join(top_inds)}.",
        "bullish_factors":   " / ".join(top_inds[:2]) if bullish > 0 else "현재 강세 요인 없음",
        "bearish_factors":   " / ".join(top_inds[-2:]) if bearish > 0 else "현재 주요 약세 요인 없음",
        "sp500_action_plan": [f"{sp_action} — 신뢰도 {sp_conf:.0f}%", "서브에이전트 실행 후 상세 액션플랜 생성됩니다"],
        "kospi_action_plan": [f"{ksp_action}", "서브에이전트 실행 후 상세 액션플랜 생성됩니다"],
        "monitoring_checklist": [f"복합 시그널 점수 (현재 {score})", "HY_SPREAD 추세", "VIX 수준"],
        "risk_summary":      " / ".join(risk_factors[:3]),
        "sp500_stock_insight": "",
        "kospi_stock_insight": "",
        "disclaimer": "본 리포트는 AI 분석 시스템이 자동 생성한 참고 자료입니다. 투자 결정은 개인 책임이며, 전문 투자 자문이 아닙니다.",
    }


def generate_narrative_section(narrative: dict) -> str:
    """대시보드 HTML용 내러티브 섹션 렌더러."""
    import re as _re
    today      = narrative.get("report_date", "")
    period     = narrative.get("analysis_period", "")
    overview   = narrative.get("market_overview", "")
    bull_f     = narrative.get("bullish_factors", "")
    bear_f     = narrative.get("bearish_factors", "")
    sp_plan    = narrative.get("sp500_action_plan", [])
    ksp_plan   = narrative.get("kospi_action_plan", [])
    monitor    = narrative.get("monitoring_checklist", [])
    risk_sum   = narrative.get("risk_summary", "")
    sp_hint    = narrative.get("sp500_stock_insight", "")
    ksp_hint   = narrative.get("kospi_stock_insight", "")
    disclaimer = narrative.get("disclaimer", "")

    def md_bold(text: str) -> str:
        return _re.sub(r'\*\*(.*?)\*\*', r'<strong style="color:#e2e8f0">\1</strong>', text)

    def plan_html(items):
        return "".join(
            f'<div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #1e293b;font-size:0.8rem">'
            f'<span style="color:#6366f1;flex-shrink:0;font-weight:700">{i+1}.</span>'
            f'<span style="color:#94a3b8">{md_bold(item)}</span></div>'
            for i, item in enumerate(items)
        )

    def check_html(items):
        return "".join(
            f'<div style="display:flex;gap:8px;padding:4px 0;font-size:0.76rem">'
            f'<span style="color:#22c55e;flex-shrink:0">☐</span>'
            f'<span style="color:#94a3b8">{item}</span></div>'
            for item in items
        )

    return f"""<!-- ═══ NARRATIVE SECTION ═══ -->
<section id="narrative">
  <h2 class="section-title">AI 분석 리포트</h2>
  <div style="font-size:0.72rem;color:#475569;margin-bottom:16px">
    자동 생성: {today} &nbsp;|&nbsp; 분석 기간: {period}
  </div>

  <div class="grid-2" style="gap:16px;margin-bottom:16px">

    <!-- 시장 개요 + 강약세 -->
    <div>
      <div class="card" style="margin-bottom:12px">
        <div style="font-size:0.82rem;font-weight:700;color:#60a5fa;margin-bottom:8px">시장 개요</div>
        <div style="font-size:0.85rem;color:#cbd5e1;line-height:1.7">{md_bold(overview)}</div>
        {f'<div style="margin-top:8px;font-size:0.72rem;color:#ef4444">리스크 요약: {md_bold(risk_sum)}</div>' if risk_sum else ""}
      </div>

      <div class="card" style="margin-bottom:12px">
        <div style="font-size:0.82rem;font-weight:700;color:#22c55e;margin-bottom:6px">강세 요인</div>
        <div style="font-size:0.8rem;color:#94a3b8;line-height:1.8">{md_bold(bull_f) if bull_f else "현재 강세 요인 없음"}</div>
      </div>

      <div class="card">
        <div style="font-size:0.82rem;font-weight:700;color:#ef4444;margin-bottom:6px">약세 요인 / 리스크</div>
        <div style="font-size:0.8rem;color:#94a3b8;line-height:1.8">{md_bold(bear_f) if bear_f else "현재 주요 약세 요인 없음"}</div>
      </div>
    </div>

    <!-- 액션플랜 + 모니터링 -->
    <div>
      <div class="card" style="margin-bottom:12px">
        <div style="font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:8px">S&amp;P500 액션플랜</div>
        {plan_html(sp_plan)}
        {f'<div style="margin-top:8px;font-size:0.72rem;color:#475569">주목 종목: {md_bold(sp_hint)}</div>' if sp_hint else ""}
      </div>

      <div class="card" style="margin-bottom:12px">
        <div style="font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:8px">코스피 액션플랜</div>
        {plan_html(ksp_plan)}
        {f'<div style="margin-top:8px;font-size:0.72rem;color:#475569">주목 종목: {md_bold(ksp_hint)}</div>' if ksp_hint else ""}
      </div>

      <div class="card">
        <div style="font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:8px">주간 모니터링 체크리스트</div>
        {check_html(monitor)}
      </div>
    </div>
  </div>

  <div style="font-size:0.68rem;color:#334155;padding:8px 12px;background:#0f172a;border-radius:6px;border-left:3px solid #334155">
    {disclaimer}
  </div>
</section>"""


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent.parent
    OUT_DIR  = BASE_DIR / "output"

    print("=" * 60)
    print("Narrative Agent — 데이터 준비 (AI API 없음)")
    print("=" * 60)

    _check_inputs(OUT_DIR)

    results_path = OUT_DIR / "final_results.json"
    results = _load_json(results_path)
    print("  ✓ NA-1 final_results.json 로드 성공")
    fails = []

    # 컨텍스트 구축
    ctx = build_narrative_context(results)

    # NA-3: 실제 수치 존재 확인
    score = ctx["signal"]["score"]
    n_indicators = len(ctx["signal"]["indicator_details"])
    if score == 0 and n_indicators == 0:
        fails.append("NA-3 시그널 수치 없음 (score=0, indicators=0)")

    if fails:
        print(f"[FAIL] {fails}")
        sys.exit(1)

    print(f"  ✓ NA-3 수치 확인: score={score}, 지표={n_indicators}개")

    # NA-2: narrative_context.json 저장
    ctx_path = OUT_DIR / "narrative_context.json"
    ctx_path.write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # NA-2: file on disk + required fields
    if not ctx_path.exists() or ctx_path.stat().st_size < 100:
        fails.append(f"NA-2 narrative_context.json not saved or too small")
    for field in ("signal", "decision", "top5_ranking", "sp500", "kospi"):
        if field not in ctx:
            fails.append(f"NA-2 context에 '{field}' 필드 없음")

    if fails:
        print("DONE_CRITERIA: FAIL — " + " | ".join(fails))
        sys.exit(1)

    print(f"  ✓ NA-2 narrative_context.json saved ({ctx_path.stat().st_size}B)")

    print("\n=== Done Criteria ===")
    print("  ✓ NA-1 final_results.json 로드 PASS")
    print("  ✓ NA-2 narrative_context.json 저장 PASS")
    print("  ✓ NA-3 실제 수치 포함 PASS")
    print(f"\n컨텍스트 요약:")
    print(f"  분석 기간: {ctx['analysis_period']['start']} ~ {ctx['analysis_period']['end']}")
    print(f"  시그널: {score}/100 ({ctx['signal']['direction']})")
    print(f"  강세/약세: {ctx['signal']['bullish_count']}/{ctx['signal']['bearish_count']}")
    print(f"  SP500: {ctx['decision']['sp500']['action']} ({ctx['decision']['sp500']['confidence_pct']}%)")
    print(f"  KOSPI:  {ctx['decision']['kospi']['action']} ({ctx['decision']['kospi']['confidence_pct']}%)")
    print(f"  가중치 Top1: {ctx['top5_ranking'][0]['indicator'] if ctx['top5_ranking'] else 'N/A'}")
    # Phase 11-A 재정의 (2026-07-02, Path Z 채택):
    # 이 스크립트는 data-prep only — narrative_context.json 완성으로 종료.
    # prose 생성 (FINAL_REPORT_v2.md) 은 architectural constraint 로 pm_orchestrator
    # 자동화 불가 (subprocess 에서 Claude Code Task tool 호출 불가, Phase 13-B-6 DC-6 와 동일).
    # → 사용자가 다음 Claude Code session 에서 narrative-agent subagent 를 manual 호출.
    #    (Task tool 로 subagent_type="narrative-agent" spawn, narrative_context.json 인용 지시)
    # 자동화 대체: verification 강화 (schema 완전성 회귀 + sourced-claim metric).
    # Phase 11-A Path Z Group E: dogfood pending 자동 등록
    dogfood_status = _register_dogfood_pending(BASE_DIR, ctx_path)
    print(f"  ✓ NA-4 dogfood pending: {dogfood_status}")

    print(f"\n-> 다음 단계 (manual dogfood):")
    print(f"   1. 다음 Claude Code session 진입 후")
    print(f"   2. Task tool 로 narrative-agent subagent spawn")
    print(f"   3. 프롬프트에 output/narrative_context.json 경로 명시")
    print(f"   4. subagent 가 output/FINAL_REPORT_v2.md 생성")
    print(f"   (pending_requests.json 의 REQ-DOGFOOD-NARRATIVE 참조)")
    print("DONE_CRITERIA: PASS")
