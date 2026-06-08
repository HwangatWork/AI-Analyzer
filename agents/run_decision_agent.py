# -*- coding: utf-8 -*-
"""
Decision Agent — 매수/매도/관망 자동 판단 엔진
PM Condition E: 데이터 기반 BUY/SELL/HOLD 신호 + 신뢰도 + 근거 자동 생성

판단 로직:
  - 복합 시그널 스코어 + 개별 지표 Z-score 합의도
  - 포지션 사이징 제안 (신뢰도 기반)
  - 진입/청산 트리거 조건 명시
  - 리스크 팩터 자동 식별
"""

import json
from pathlib import Path
from datetime import datetime


def compute_decision(signal: dict, ranking: list, stock_sp500: dict, stock_kospi: dict) -> dict:
    score     = signal.get("score", 50) or 50
    direction = signal.get("direction", "neutral")
    bullish   = signal.get("bullish_count", 0)
    bearish   = signal.get("bearish_count", 0)
    total     = signal.get("total_signals", 1) or 1
    ind_sigs  = signal.get("indicator_signals", [])

    consensus_ratio = bullish / total if total > 0 else 0.5

    # ── 매수/매도/관망 판단 ─────────────────────────────────────────────────
    # SP500
    if score >= 70 and consensus_ratio >= 0.6:
        sp500_action = "BUY"
        sp500_strength = "강" if score >= 80 else "중"
    elif score <= 35 or consensus_ratio <= 0.35:
        sp500_action = "SELL/AVOID"
        sp500_strength = "강" if score <= 25 else "중"
    elif 55 <= score < 70 and consensus_ratio >= 0.55:
        sp500_action = "BUY (소량)"
        sp500_strength = "약"
    else:
        sp500_action = "HOLD"
        sp500_strength = "중립"

    # KOSPI (코스피는 별도 시그널 없이 SP500 시그널 + 상관도로 추론)
    # KOSDAQ z-score 활용
    kosdaq_sig = next((s for s in ind_sigs if s["indicator"] == "KOSDAQ"), None)
    nikkei_sig = next((s for s in ind_sigs if s["indicator"] == "NIKKEI225"), None)
    kospi_bull_boost = 0
    if kosdaq_sig and kosdaq_sig.get("bullish"):
        kospi_bull_boost = 5
    if nikkei_sig and nikkei_sig.get("bullish"):
        kospi_bull_boost += 3

    kospi_score = min(100, score + kospi_bull_boost)
    if kospi_score >= 68 and consensus_ratio >= 0.55:
        kospi_action = "BUY"
        kospi_strength = "강" if kospi_score >= 78 else "중"
    elif kospi_score <= 35:
        kospi_action = "SELL/AVOID"
        kospi_strength = "강" if kospi_score <= 25 else "중"
    else:
        kospi_action = "HOLD"
        kospi_strength = "중립"

    # ── 신뢰도 계산 ──────────────────────────────────────────────────────────
    # 기준: 시그널 합의도 40% + 스코어 극단성 30% + 강한 지표 수 30%
    consensus_conf  = consensus_ratio * 100 if sp500_action != "HOLD" else (1 - abs(consensus_ratio - 0.5) * 2) * 100
    score_conf      = abs(score - 50) / 50 * 100
    strong_sigs     = sum(1 for s in ind_sigs if abs(s.get("z_score", 0)) >= 1.5)
    strength_conf   = min(strong_sigs / max(total, 1) * 100, 100)
    confidence      = round(consensus_conf * 0.4 + score_conf * 0.3 + strength_conf * 0.3, 1)

    # ── 진입 트리거 ─────────────────────────────────────────────────────────
    entry_triggers = []
    exit_triggers  = []

    # 강세 트리거
    strong_bull = [s for s in ind_sigs if s.get("bullish") and abs(s.get("z_score", 0)) >= 1.5]
    strong_bear = [s for s in ind_sigs if not s.get("bullish") and abs(s.get("z_score", 0)) >= 1.5]

    for s in strong_bull[:3]:
        z = s.get("z_score", 0)
        entry_triggers.append(f"{s['indicator']} 강세 (Z={z:+.2f}) — 252일 평균 대비 {abs(z):.1f}σ 이상")
    for s in strong_bear[:3]:
        z = s.get("z_score", 0)
        exit_triggers.append(f"{s['indicator']} 약세 (Z={z:+.2f}) — 하방 압력")

    # 특수 조건
    hy = next((s for s in ind_sigs if s["indicator"] == "HY_SPREAD"), None)
    vix = next((s for s in ind_sigs if s["indicator"] == "VIX"), None)
    if hy and hy.get("bullish"):
        entry_triggers.append("HY_SPREAD 축소 → 신용 리스크 감소, 위험자산 선호")
    if vix and not vix.get("bullish"):
        exit_triggers.append("VIX 상승 → 시장 공포 증가, 포지션 축소 고려")

    # ── 포지션 사이징 ────────────────────────────────────────────────────────
    if confidence >= 70:
        position_pct = 70
        position_note = "신뢰도 높음 — 적극적 포지션"
    elif confidence >= 50:
        position_pct = 40
        position_note = "신뢰도 중간 — 분할 매수 권장"
    else:
        position_pct = 15
        position_note = "신뢰도 낮음 — 소량 또는 관망"

    if sp500_action == "HOLD":
        position_pct = 0
        position_note = "명확한 방향성 미확인 — 현금 비중 유지"

    # ── 리스크 팩터 ─────────────────────────────────────────────────────────
    risk_factors = []
    wti = next((s for s in ind_sigs if s["indicator"] == "WTI"), None)
    us10y = next((s for s in ind_sigs if s["indicator"] == "US10Y"), None)
    dxy = next((s for s in ind_sigs if s["indicator"] == "DXY"), None)
    bband = next((s for s in ind_sigs if s["indicator"] == "BBAND"), None)

    if wti and not wti.get("bullish"):
        risk_factors.append("WTI 상승 → 인플레이션 재점화 위험")
    if us10y and not us10y.get("bullish"):
        z_10y = us10y.get("z_score", 0)
        risk_factors.append(f"미국 10년물 금리 상승 (Z={z_10y:+.2f}) → 할인율 부담")
    if dxy and dxy.get("bullish"):
        risk_factors.append("달러 강세 → 신흥국 자금 유출 위험 (KOSPI 주의)")
    if bband and not bband.get("bullish"):
        risk_factors.append("볼린저밴드 하단 근접 → 변동성 확대 국면")
    if not risk_factors:
        risk_factors.append("현재 주요 리스크 팩터 없음 — 시장 환경 양호")

    # ── 종목 추천 힌트 ─────────────────────────────────────────────────────
    top_sp = stock_sp500.get("contribution_top5", [])[:2]
    top_ksp = stock_kospi.get("contribution_top5", [])[:2]

    sp_hint  = " / ".join(f"{s.get('name','?')} ({s.get('stock_return_pct',0):+.0f}%)" for s in top_sp)
    ksp_hint = " / ".join(f"{s.get('name','?')} ({s.get('stock_return_pct',0):+.0f}%)" for s in top_ksp)

    return {
        "computed_at": datetime.now().isoformat(),
        "composite_score": score,
        "direction": direction,
        "sp500": {
            "action":         sp500_action,
            "strength":       sp500_strength,
            "confidence_pct": confidence,
            "position_size_pct": position_pct if sp500_action != "HOLD" else 0,
            "position_note":  position_note,
            "entry_triggers": entry_triggers,
            "exit_triggers":  exit_triggers,
            "top_stocks_hint": sp_hint,
        },
        "kospi": {
            "action":         kospi_action,
            "strength":       kospi_strength,
            "confidence_pct": min(confidence + 5, 95),
            "position_size_pct": (position_pct - 10) if kospi_action != "HOLD" else 0,
            "position_note":  position_note,
            "top_stocks_hint": ksp_hint,
        },
        "risk_factors":   risk_factors,
        "signal_summary": {
            "bullish": bullish,
            "bearish": bearish,
            "total":   total,
            "consensus_ratio": round(consensus_ratio, 3),
        },
    }


def generate_decision_section(decision: dict) -> str:
    sp  = decision.get("sp500", {})
    ksp = decision.get("kospi", {})
    risks = decision.get("risk_factors", [])
    score = decision.get("composite_score", 50)
    direction = decision.get("direction", "neutral")
    computed = decision.get("computed_at", "")[:16].replace("T", " ")

    action_colors = {
        "BUY": "#22c55e", "BUY (소량)": "#86efac",
        "HOLD": "#f59e0b", "SELL/AVOID": "#ef4444",
    }

    bull  = decision.get("signal_summary", {}).get("bullish", 0)
    total_sigs = decision.get("signal_summary", {}).get("total", 1) or 1

    def action_card(market_name, data, flag=""):
        action   = data.get("action", "HOLD")
        strength = data.get("strength", "중립")
        conf     = data.get("confidence_pct", 50)
        pos      = data.get("position_size_pct", 0)
        note     = data.get("position_note", "")
        hint     = data.get("top_stocks_hint", "")
        cl       = action_colors.get(action, "#64748b")
        is_hold  = action == "HOLD"

        # 신뢰도 바
        conf_cl = "#22c55e" if conf >= 70 else ("#f59e0b" if conf >= 50 else "#ef4444")

        entries = data.get("entry_triggers", [])
        exits   = data.get("exit_triggers", [])

        entry_html = "".join(f'<div style="font-size:0.72rem;color:#86efac;padding:2px 0">▲ {e}</div>' for e in entries[:2])
        exit_html  = "".join(f'<div style="font-size:0.72rem;color:#fca5a5;padding:2px 0">▼ {x}</div>' for x in exits[:2])

        # 포지션 블록: HOLD와 BUY/SELL은 다르게 표시
        if is_hold:
            position_block = f"""
          <div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:10px">
            <div style="font-size:0.72rem;color:#f59e0b;font-weight:600;margin-bottom:4px">📌 HOLD 의미</div>
            <div style="font-size:0.75rem;color:#94a3b8;line-height:1.5">
              · 신규 매수: 시장 방향성 불명확 — 진입 보류<br>
              · 기존 보유: 포지션 유지 (매도 신호 없음)<br>
              · 추천 행동: 다음 주 시그널 재확인
            </div>
            <div style="font-size:0.68rem;color:#475569;margin-top:6px">{note}</div>
          </div>"""
        else:
            position_block = f"""
          <div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
              <span style="font-size:0.72rem;color:#64748b">권장 포지션 비중</span>
              <span style="font-size:0.9rem;font-weight:700;color:{cl}">{pos}%</span>
            </div>
            <div style="background:#1e293b;height:6px;border-radius:3px;overflow:hidden">
              <div style="height:100%;width:{pos}%;background:{cl};border-radius:3px"></div>
            </div>
            <div style="font-size:0.68rem;color:#475569;margin-top:4px">{note}</div>
          </div>"""

        return f"""
        <div class="card" style="border-left:3px solid {cl};padding:16px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
            <div>
              <div style="font-size:0.72rem;color:#64748b;margin-bottom:2px">{market_name} {flag}</div>
              <div style="font-size:1.6rem;font-weight:900;color:{cl};letter-spacing:-0.03em">{action}</div>
              <div style="font-size:0.75rem;color:{cl};opacity:0.8">신호 강도: {strength}</div>
            </div>
            <div style="text-align:right">
              <div style="font-size:0.7rem;color:#64748b;margin-bottom:2px">신뢰도</div>
              <div style="font-size:1.4rem;font-weight:800;color:{conf_cl}">{conf:.0f}%</div>
              <div style="font-size:0.65rem;color:#475569">지표 {bull}/{total_sigs}개 강세</div>
            </div>
          </div>

          <!-- 포지션 사이징 -->
          {position_block}

          <!-- 트리거 -->
          {f'<div style="margin-bottom:8px">{entry_html}</div>' if entry_html else ""}
          {f'<div>{exit_html}</div>' if exit_html else ""}

          <!-- 주목 종목 -->
          {f'<div style="margin-top:8px;font-size:0.7rem;color:#475569">주목 종목: <span style="color:#94a3b8">{hint}</span></div>' if hint else ""}
        </div>"""

    risk_html = "".join(
        f'<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #1e293b;font-size:0.78rem">'
        f'<span style="color:#f59e0b;flex-shrink:0">⚠</span>'
        f'<span style="color:#94a3b8">{r}</span></div>'
        for r in risks
    )

    sp_html  = action_card("S&P500", sp)
    ksp_html = action_card("코스피", ksp, "🇰🇷")

    return f"""
<!-- ═══ DECISION SECTION ═══ -->
<section id="decision">
  <h2 class="section-title">매수/매도 의사결정</h2>
  <div style="font-size:0.72rem;color:#475569;margin-bottom:14px">
    기준: 복합 시그널 {score}점 ({direction}) | 산출: {computed} | 투자 판단은 개인 책임입니다
  </div>

  <div class="grid-2" style="gap:16px;margin-bottom:16px">
    {sp_html}
    {ksp_html}
  </div>

  <!-- 리스크 팩터 -->
  <div class="card">
    <div style="font-size:0.82rem;font-weight:600;color:#94a3b8;margin-bottom:8px">리스크 팩터</div>
    {risk_html}
  </div>
</section>"""


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))
    BASE_DIR = Path(__file__).parent.parent
    PROC_DIR = BASE_DIR / "data" / "processed"
    OUT_DIR  = BASE_DIR / "output"

    final = json.loads((OUT_DIR / "final_results.json").read_bytes().decode("utf-8"))
    signal = final.get("market_signal", {})
    ranking = final.get("indicator_weight_ranking", [])
    sp500  = final.get("sp500_analysis", {})
    kospi  = final.get("kospi_analysis", {})

    decision = compute_decision(signal, ranking, sp500, kospi)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(f"\nSP500: {decision['sp500']['action']} (신뢰도 {decision['sp500']['confidence_pct']}%)")
    print(f"KOSPI: {decision['kospi']['action']} (신뢰도 {decision['kospi']['confidence_pct']}%)")

    # ── Done Criteria 자체검증 ────────────────────────────────────
    fails = []
    for market, key in [("SP500", "sp500"), ("KOSPI", "kospi")]:
        d = decision.get(key, {})
        action = d.get("action", "")
        conf   = d.get("confidence_pct", -1)
        if action not in ("BUY", "SELL", "HOLD"):
            fails.append(f"DE-1 {market} action 유효하지 않음: '{action}'")
        if not (0 <= conf <= 100):
            fails.append(f"DE-2 {market} confidence_pct 범위 오류: {conf}")
        if not d.get("position_pct") and d.get("position_pct") != 0:
            fails.append(f"DE-3 {market} position_pct 없음")
    print("\n[Done Criteria] Decision Agent:")
    if fails:
        for f in fails:
            print(f"  ✗ {f}")
        print("[FAIL] Decision Agent Done Criteria 미충족")
        sys.exit(1)
    print("  ✓ DE-1~3 BUY/SELL/HOLD + 신뢰도 + 포지션 전항목 PASS")
