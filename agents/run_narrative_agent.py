# -*- coding: utf-8 -*-
"""
Narrative Agent — AI 언어 인사이트 + 액션플랜 자동 생성
PM Condition F: 데이터를 한국어 분석 리포트 + 실무 액션플랜으로 변환

방법: ANTHROPIC_API_KEY 환경변수 설정 시 Claude API LLM 강화, 미설정 시 규칙 기반 템플릿
Done Criteria (NA-1~NA-4):
  NA-1: market_overview 비어있지 않음
  NA-2: sp500_action_plan 최소 1개 항목
  NA-3: kospi_action_plan 최소 1개 항목
  NA-4: disclaimer 존재
"""

import os
from datetime import datetime

# ── Claude API (ANTHROPIC_API_KEY 환경변수 필요) ──────────────────
try:
    import anthropic as _anthropic
    _ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    HAS_ANTHROPIC = bool(_ANTHROPIC_KEY)
except ImportError:
    HAS_ANTHROPIC = False
    _ANTHROPIC_KEY = ""


def _z_desc(z: float) -> str:
    az = abs(z)
    if az >= 1.8: return "매우 강한"
    if az >= 1.2: return "강한"
    if az >= 0.6: return "보통의"
    return "약한"


def _direction_ko(direction: str) -> str:
    return {"risk-on": "위험 선호", "neutral": "중립", "risk-off": "위험 회피"}.get(direction, direction)


def _generate_narrative_llm(signal: dict, decision: dict, ranking: list,
                            sp500: dict, kospi: dict, meta: dict) -> dict | None:
    """Claude API로 한국어 분석 리포트 생성. 실패 시 None 반환 → 템플릿 폴백."""
    if not HAS_ANTHROPIC:
        return None
    try:
        score      = signal.get("score", 50)
        direction  = signal.get("direction", "neutral")
        sp_action  = decision.get("sp500", {}).get("action", "HOLD")
        ksp_action = decision.get("kospi", {}).get("action", "HOLD")
        confidence = decision.get("sp500", {}).get("confidence_pct", 50)
        top3_inds  = [r.get("indicator", "") for r in ranking[:3]]
        sp_top1    = (sp500.get("contribution_top5", [{}]) or [{}])[0]
        ksp_top1   = (kospi.get("contribution_top5", [{}]) or [{}])[0]
        risk_factors = decision.get("risk_factors", [])
        period     = meta.get("period", {})

        prompt = f"""다음 시장 데이터를 바탕으로 한국어 투자 분석 리포트를 작성하세요.
[데이터]
- 복합 시그널 점수: {score}/100 ({direction})
- S&P500 의사결정: {sp_action} (신뢰도 {confidence:.0f}%)
- 코스피 의사결정: {ksp_action}
- 상위 3개 지표: {', '.join(top3_inds)}
- S&P500 기여 1위: {sp_top1.get('name','N/A')} ({sp_top1.get('stock_return_pct',0):+.1f}%)
- 코스피 기여 1위: {ksp_top1.get('name','N/A')} ({ksp_top1.get('stock_return_pct',0):+.1f}%)
- 리스크 요인: {', '.join(risk_factors[:3]) or '없음'}
- 분석 기간: {period.get('start','?')} ~ {period.get('end','?')}

[작성 요구사항]
1. 시장 개요 (2~3문장): 현재 시장 상황 요약, 점수와 방향성 언급
2. 강세 요인 (1~2문장): 상위 지표 기반 강세 근거
3. 약세/리스크 요인 (1~2문장): 리스크 요인 기반
4. S&P500 액션플랜 (2~3단계): {sp_action} 의사결정 기반 구체적 행동
5. 코스피 액션플랜 (2~3단계): {ksp_action} 의사결정 기반 구체적 행동
6. 모니터링 항목 3가지: 주간 점검 지표

JSON 형식으로 반환:
{{"market_overview":"...", "bullish_factors":"...", "bearish_factors":"...",
  "sp500_action_plan":["1단계","2단계","3단계"],
  "kospi_action_plan":["1단계","2단계"],
  "monitoring_checklist":["항목1","항목2","항목3"]}}
JSON만 반환하고 다른 텍스트는 포함하지 마세요."""

        client = _anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        import json as _json
        raw = resp.content[0].text.strip()
        # JSON 블록 추출 (코드 펜스 있을 수 있음)
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        parsed = _json.loads(raw)
        today  = datetime.now().strftime("%Y년 %m월 %d일")
        return {
            "generated_at":      datetime.now().isoformat(),
            "report_date":       today,
            "analysis_period":   f"{period.get('start','?')} ~ {period.get('end','?')}",
            "generation_method": "claude_api",
            "market_overview":   parsed.get("market_overview", ""),
            "bullish_factors":   parsed.get("bullish_factors", ""),
            "bearish_factors":   parsed.get("bearish_factors", ""),
            "sp500_stock_insight": f"{sp_top1.get('name','?')} ({sp_top1.get('stock_return_pct',0):+.1f}%)",
            "kospi_stock_insight": f"{ksp_top1.get('name','?')} ({ksp_top1.get('stock_return_pct',0):+.1f}%)",
            "sp500_action_plan":  parsed.get("sp500_action_plan", []),
            "kospi_action_plan":  parsed.get("kospi_action_plan", []),
            "monitoring_checklist": parsed.get("monitoring_checklist", []),
            "risk_summary":       " / ".join(risk_factors[:3]),
            "disclaimer": "본 리포트는 AI 분석 시스템이 자동 생성한 참고 자료입니다. 투자 결정은 개인 책임이며, 전문 투자 자문이 아닙니다.",
        }
    except Exception as e:
        print(f"  [Narrative LLM] Claude API 실패: {e} → 템플릿 폴백")
        return None


def generate_narrative(signal: dict, decision: dict, ranking: list,
                       sp500: dict, kospi: dict, meta: dict) -> dict:
    # LLM 우선 시도 (ANTHROPIC_API_KEY 설정 시)
    llm_result = _generate_narrative_llm(signal, decision, ranking, sp500, kospi, meta)
    if llm_result:
        print("  [Narrative] Claude API LLM 생성 성공")
        return llm_result
    if HAS_ANTHROPIC:
        print("  [Narrative] LLM 실패 → 템플릿 폴백")
    else:
        print("  [Narrative] 템플릿 모드 (ANTHROPIC_API_KEY 미설정)")

    score     = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    bullish   = signal.get("bullish_count", 0)
    bearish   = signal.get("bearish_count", 0)
    total     = signal.get("total_signals", 1) or 1
    ind_sigs  = signal.get("indicator_signals", [])

    sp_action = decision.get("sp500", {}).get("action", "HOLD")
    ksp_action = decision.get("kospi", {}).get("action", "HOLD")
    confidence = decision.get("sp500", {}).get("confidence_pct", 50)
    risk_factors = decision.get("risk_factors", [])

    today = datetime.now().strftime("%Y년 %m월 %d일")
    period = meta.get("period", {})

    # 상위 강세/약세 지표 추출
    bull_sigs = [s for s in ind_sigs if s.get("bullish")][:3]
    bear_sigs = [s for s in ind_sigs if not s.get("bullish")][:3]

    # 최상위 랭킹 지표
    top_indicator = ranking[0] if ranking else {}
    top_ind_name  = top_indicator.get("indicator", "N/A")
    top_sp_r      = top_indicator.get("sp500_signed_r", 0) or 0

    # KOSPI/SP500 Top 종목
    sp_top  = sp500.get("contribution_top5", [])[:2]
    ksp_top = kospi.get("contribution_top5", [])[:2]

    # ── 시장 개요 ──────────────────────────────────────────────────────────
    dir_ko = _direction_ko(direction)
    if score >= 65:
        market_tone = f"복합 시그널 점수 {score}점으로 **{dir_ko}** 구간에 위치합니다. 15개 분석 지표 중 {bullish}개가 강세를 나타내며 시장 모멘텀이 우호적입니다."
    elif score <= 35:
        market_tone = f"복합 시그널 점수 {score}점으로 **{dir_ko}** 구간에 위치합니다. {bearish}개 지표가 약세를 나타내며 시장 불확실성이 높습니다."
    else:
        market_tone = f"복합 시그널 점수 {score}점으로 **{dir_ko}** 구간에 위치합니다. 강세 {bullish}개 / 약세 {bearish}개로 방향성이 혼재되어 있습니다."

    # ── 핵심 강세 요인 ──────────────────────────────────────────────────────
    bull_narrative = ""
    for s in bull_sigs:
        ind = s.get("indicator", "")
        z   = s.get("z_score", 0)
        w   = s.get("weight", 0)
        desc = _z_desc(z)
        if ind == "NASDAQ100":
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}): 미국 기술주 랠리가 S&P500과 +{top_sp_r:.3f} 상관으로 동조화 중. "
        elif ind == "HY_SPREAD":
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}): 하이일드 스프레드 축소 → 신용 리스크 감소, 위험자산 선호 환경. "
        elif ind == "KOSDAQ":
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}): 국내 성장주 섹터 강세 → 코스피 동반 상승 기대. "
        elif ind == "DXY":
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}): 달러 약세 전환 → 신흥국 자금 유입 우호. "
        elif ind == "NIKKEI225":
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}): 동아시아 증시 동조화 → 아시아 리스크온. "
        else:
            bull_narrative += f"**{ind}** ({desc} 강세, Z={z:+.2f}, 가중치 {w:.3f}). "

    # ── 핵심 약세 요인 ──────────────────────────────────────────────────────
    bear_narrative = ""
    for s in bear_sigs:
        ind = s.get("indicator", "")
        z   = s.get("z_score", 0)
        desc = _z_desc(z)
        if ind == "VIX":
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}): 변동성 지수 상승 → 투자자 불안 심리 증가. "
        elif ind == "US10Y":
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}): 금리 상승 → 할인율 부담, 성장주 밸류에이션 압박. "
        elif ind == "WTI":
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}): 유가 상승 → 인플레이션 재점화, 긴축 장기화 우려. "
        elif ind == "BBAND":
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}): 볼린저밴드 하단 → 가격 하방 변동성 확대 구간. "
        elif ind == "STOCH_RSI":
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}): 스토캐스틱 RSI 과매도 → 단기 조정 가능성. "
        else:
            bear_narrative += f"**{ind}** ({desc} 약세, Z={z:+.2f}). "

    # ── 종목 인사이트 ──────────────────────────────────────────────────────
    sp_stock_insight = ""
    for s in sp_top:
        sp_stock_insight += f"**{s.get('name','?')}** (1년 수익률 {s.get('stock_return_pct',0):+.1f}%, 시가총액 기여점수 {s.get('contribution_score',0):.2f}), "

    ksp_stock_insight = ""
    for s in ksp_top:
        ksp_stock_insight += f"**{s.get('name','?')}** ({s.get('stock_return_pct',0):+.1f}%, [{s.get('data_source','?')}/{s.get('data_quality','?')}]), "

    # ── 액션플랜 ──────────────────────────────────────────────────────────
    if sp_action == "BUY":
        sp_action_plan = [
            f"S&P500 ETF(SPY/QQQ) 또는 기여 상위 종목 분할 매수 (신뢰도 {confidence:.0f}%)",
            "목표: 15~30일 보유, 시그널 점수 <50 하락 시 절반 청산",
            f"추천 종목: {sp_stock_insight.rstrip(', ')}",
        ]
    elif sp_action == "SELL/AVOID":
        sp_action_plan = [
            "현재 S&P500 포지션 축소 또는 헤지 (풋옵션/인버스 ETF 검토)",
            "신규 진입 자제, 현금 비중 50% 이상 유지",
            "시그널 점수 >55 회복 시 재진입 검토",
        ]
    else:
        sp_action_plan = [
            "S&P500 신규 매수 자제, 기존 포지션 유지",
            "시그널 점수 >68 또는 강세 지표 >60% 달성 시 매수 재검토",
            "관망하며 HY_SPREAD, VIX 추세 모니터링",
        ]

    if ksp_action == "BUY":
        ksp_action_plan = [
            f"코스피 ETF(KODEX200 등) 또는 반도체/AI 섹터 집중 매수",
            f"주목 종목: {ksp_stock_insight.rstrip(', ')}",
            "환율(원/달러) 1,400 이상 급등 시 추가 매수 자제",
        ]
    else:
        ksp_action_plan = [
            "코스피 신규 매수 자제, KOSDAQ 개별주 모니터링",
            "외국인 순매수 전환 확인 후 진입 검토",
        ]

    # ── 모니터링 지표 ─────────────────────────────────────────────────────
    monitoring = [
        f"복합 시그널 점수 (현재 {score}) — 주간 파이프라인 자동 업데이트",
        "HY_SPREAD: 신용 리스크 선행 지표, 상승 시 즉시 경계",
        "VIX: 20 돌파 시 포지션 축소 검토",
        "US10Y: 5% 재돌파 시 성장주 비중 조정",
        "KOSDAQ 흐름: 코스피 선행 지표로 주 2회 확인",
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "report_date":  today,
        "analysis_period": f"{period.get('start','?')} ~ {period.get('end','?')}",
        "market_overview":     market_tone,
        "bullish_factors":     bull_narrative.strip(),
        "bearish_factors":     bear_narrative.strip(),
        "sp500_stock_insight": sp_stock_insight.strip().rstrip(","),
        "kospi_stock_insight": ksp_stock_insight.strip().rstrip(","),
        "sp500_action_plan":   sp_action_plan,
        "kospi_action_plan":   ksp_action_plan,
        "monitoring_checklist": monitoring,
        "risk_summary":         " / ".join(risk_factors[:3]),
        "disclaimer": "본 리포트는 AI 분석 시스템이 자동 생성한 참고 자료입니다. 투자 결정은 개인 책임이며, 전문 투자 자문이 아닙니다.",
    }


def generate_narrative_section(narrative: dict) -> str:
    today    = narrative.get("report_date", "")
    period   = narrative.get("analysis_period", "")
    overview = narrative.get("market_overview", "")
    bull_f   = narrative.get("bullish_factors", "")
    bear_f   = narrative.get("bearish_factors", "")
    sp_plan  = narrative.get("sp500_action_plan", [])
    ksp_plan = narrative.get("kospi_action_plan", [])
    monitor  = narrative.get("monitoring_checklist", [])
    risk_sum = narrative.get("risk_summary", "")
    sp_hint  = narrative.get("sp500_stock_insight", "")
    ksp_hint = narrative.get("kospi_stock_insight", "")
    disclaimer = narrative.get("disclaimer", "")

    def md_bold(text: str) -> str:
        import re
        return re.sub(r'\*\*(.*?)\*\*', r'<strong style="color:#e2e8f0">\1</strong>', text)

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
    import json, sys
    from pathlib import Path

    BASE_DIR = Path(__file__).parent.parent
    OUT_DIR  = BASE_DIR / "output"

    # 데이터 로드 (없으면 더미)
    def _jload(p):
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {}

    results  = _jload(OUT_DIR / "final_results.json")
    signal   = results.get("market_signal", {"score": 55, "direction": "neutral",
                                              "bullish_count": 5, "bearish_count": 4,
                                              "total_signals": 9, "indicator_signals": []})
    decision = results.get("decision", {"sp500": {"action": "HOLD", "confidence_pct": 55,
                                                   "position_pct": 30},
                                         "kospi": {"action": "HOLD", "confidence_pct": 50},
                                         "risk_factors": []})
    ranking  = results.get("indicator_weight_ranking", [])
    sp500    = results.get("sp500_analysis", {})
    kospi    = results.get("kospi_analysis",  {})
    meta     = results.get("meta", {"period": {"start": "?", "end": "?"}})

    print("=" * 60)
    print("Narrative Agent — Done Criteria 검증")
    print(f"  LLM 모드: {'활성' if HAS_ANTHROPIC else '비활성 (템플릿)'}")
    print("=" * 60)

    narr = generate_narrative(signal, decision, ranking, sp500, kospi, meta)

    # ── Done Criteria ──────────────────────────────────────────
    fails = []
    if not narr.get("market_overview", "").strip():
        fails.append("NA-1 market_overview 비어있음")
    if not narr.get("sp500_action_plan"):
        fails.append("NA-2 sp500_action_plan 없음")
    if not narr.get("kospi_action_plan"):
        fails.append("NA-3 kospi_action_plan 없음")
    if not narr.get("disclaimer", "").strip():
        fails.append("NA-4 disclaimer 없음")

    print("\n=== Done Criteria ===")
    for code in ["NA-1", "NA-2", "NA-3", "NA-4"]:
        fail_item = next((f for f in fails if code in f), None)
        print(f"  {'✗' if fail_item else '✓'} {fail_item or code + ' PASS'}")

    if fails:
        print(f"\n[FAIL] Done Criteria 미충족: {fails}")
        sys.exit(1)
    print("\n[PASS] NA-1~NA-4 전항목 통과")

    # 리포트 저장
    out_file = OUT_DIR / "narrative.json"
    out_file.write_text(json.dumps(narr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {out_file}")
