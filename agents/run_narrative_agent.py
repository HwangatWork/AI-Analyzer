# -*- coding: utf-8 -*-
"""
Narrative Agent — AI 언어 인사이트 + 액션플랜 자동 생성
PM Condition F: final_results.json 읽기 → Claude API 서브에이전트 → FINAL_REPORT.md 저장

Done Criteria (NA-1~NA-5):
  NA-1: ANTHROPIC_API_KEY 설정됨
  NA-2: market_overview에 실제 수치(score, Z-score 등) 포함
  NA-3: sp500_action_plan 최소 1개 항목
  NA-4: kospi_action_plan 최소 1개 항목
  NA-5: FINAL_REPORT.md 생성 + 실제 지표 수치 포함
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_prompt(results: dict) -> str:
    """final_results.json 전체 데이터를 LLM 프롬프트로 변환."""
    signal   = results.get("market_signal", {})
    decision = results.get("decision", {})
    ranking  = results.get("indicator_weight_ranking", [])
    sp500    = results.get("sp500_analysis", {})
    kospi    = results.get("kospi_analysis", {})
    meta     = results.get("meta", {})

    score     = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    bullish   = signal.get("bullish_count", 0)
    bearish   = signal.get("bearish_count", 0)
    total     = signal.get("total_signals", 0)
    ind_sigs  = signal.get("indicator_signals", [])

    sp_dec   = decision.get("sp500", {})
    ksp_dec  = decision.get("kospi", {})
    sp_action  = sp_dec.get("action", "HOLD")
    ksp_action = ksp_dec.get("action", "HOLD")
    sp_conf    = sp_dec.get("confidence_pct", 50)
    ksp_conf   = ksp_dec.get("confidence_pct", 50)
    sp_pos     = sp_dec.get("position_size_pct", 0)
    ksp_pos    = ksp_dec.get("position_size_pct", 0)
    risk_factors = decision.get("risk_factors", [])

    period   = meta.get("period", {})
    start    = period.get("start", "?")
    end      = period.get("end", "?")

    # 지표 시그널 목록 (Z-score 포함)
    sig_lines = []
    for s in ind_sigs:
        ind = s.get("indicator", "")
        z   = s.get("z_score", 0)
        w   = s.get("weight", 0)
        bull = "강세" if s.get("bullish") else "약세"
        sig_lines.append(f"  - {ind}: Z={z:+.3f}, 가중치={w:.4f}, 방향={bull}")
    sigs_text = "\n".join(sig_lines) if sig_lines else "  (없음)"

    # 가중치 Top5
    top5_lines = []
    for r in ranking[:5]:
        top5_lines.append(
            f"  - {r.get('indicator','?')}: combined_weight={r.get('combined_weight',0):.4f}, "
            f"SP500_r={r.get('sp500_signed_r',0):+.3f}, KOSPI_r={r.get('kospi_signed_r',0):+.3f}"
        )
    top5_text = "\n".join(top5_lines) if top5_lines else "  (없음)"

    # S&P500 기여/수혜 Top3
    sp_cont = sp500.get("contribution_top5", [])[:3]
    sp_ben  = sp500.get("beneficiary_top5",  [])[:3]
    sp_cont_text = "\n".join(
        f"  - {s.get('name','?')}: 1Y={s.get('stock_return_pct',0):+.1f}%, 기여점수={s.get('contribution_score',0):.2f}"
        for s in sp_cont
    ) or "  (없음)"
    sp_ben_text = "\n".join(
        f"  - {s.get('name','?')}: 초과수익={s.get('excess_return',0):+.1f}%"
        for s in sp_ben
    ) or "  (없음)"

    # KOSPI 기여/수혜 Top3
    ksp_cont = kospi.get("contribution_top5", [])[:3]
    ksp_ben  = kospi.get("beneficiary_top5",  [])[:3]
    ksp_cont_text = "\n".join(
        f"  - {s.get('name','?')}: 1Y={s.get('stock_return_pct',0):+.1f}%, 기여점수={s.get('contribution_score',0):.2f}"
        for s in ksp_cont
    ) or "  (없음)"
    ksp_ben_text = "\n".join(
        f"  - {s.get('name','?')}: 초과수익={s.get('excess_return',0):+.1f}%"
        for s in ksp_ben
    ) or "  (없음)"

    return f"""당신은 전문 퀀트 애널리스트입니다. 아래 실제 시장 데이터를 분석하여 한국어 투자 리포트를 작성하세요.

[분석 기간]
{start} ~ {end}

[복합 시그널]
- 점수: {score}/100
- 방향성: {direction}
- 강세 지표: {bullish}개 / 약세 지표: {bearish}개 / 총 유효 지표: {total}개

[지표별 Z-Score 상세]
{sigs_text}

[가중치 Top5 지표]
{top5_text}

[S&P500 의사결정]
- 행동: {sp_action}
- 신뢰도: {sp_conf:.1f}%
- 포지션 비중: {sp_pos:.0f}%

[코스피 의사결정]
- 행동: {ksp_action}
- 신뢰도: {ksp_conf:.1f}%
- 포지션 비중: {ksp_pos:.0f}%

[리스크 요인]
{chr(10).join('- ' + r for r in risk_factors) if risk_factors else '- 없음'}

[S&P500 기여 Top3]
{sp_cont_text}

[S&P500 수혜 Top3]
{sp_ben_text}

[코스피 기여 Top3]
{ksp_cont_text}

[코스피 수혜 Top3]
{ksp_ben_text}

[작성 요구사항]
반드시 위의 실제 수치(점수, Z-score, %, 가중치)를 인용하여 작성하세요.
단순 "강세 국면" / "약세 국면" 같은 일반적 표현만 쓰지 마세요.

다음 JSON 형식으로 반환하세요 (JSON 외 텍스트 금지):
{{
  "market_overview": "현재 시장 상황 3~4문장. 점수 {score}/100, {direction} 방향, Z-score 상위 지표명과 수치 반드시 포함",
  "bullish_factors": "강세 지표 2~3개, Z-score 수치 포함 2문장",
  "bearish_factors": "약세 지표 2~3개, Z-score 수치 포함 2문장",
  "sp500_action_plan": ["1단계: 구체적 행동 ({sp_action}, 신뢰도 {sp_conf:.0f}%)", "2단계", "3단계"],
  "kospi_action_plan": ["1단계: 구체적 행동 ({ksp_action}, 신뢰도 {ksp_conf:.0f}%)", "2단계"],
  "monitoring_checklist": ["모니터링항목1 (구체적 수치 임계값 포함)", "항목2", "항목3"],
  "top_indicator_insight": "가중치 1위 지표에 대한 1문장 해설 (수치 포함)"
}}"""


def generate_narrative_llm(results: dict) -> dict:
    """Claude API 서브에이전트로 한국어 분석 리포트 생성. 실패 시 exit(1)."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[Narrative] ANTHROPIC_API_KEY 미설정 — 리포트 생성 불가")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("[Narrative] anthropic 패키지 미설치 — pip install anthropic")
        sys.exit(1)

    prompt = _build_prompt(results)

    print("  [Narrative] Claude API 호출 중 (claude-haiku-4-5-20251001)...")
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = resp.content[0].text.strip()
    # 코드 펜스 제거
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
        if "```" in raw:
            raw = raw[:raw.index("```")]

    parsed = json.loads(raw)

    signal   = results.get("market_signal", {})
    decision = results.get("decision", {})
    meta     = results.get("meta", {})
    period   = meta.get("period", {})
    risk_factors = decision.get("risk_factors", [])

    sp500  = results.get("sp500_analysis", {})
    kospi  = results.get("kospi_analysis", {})
    sp_top1  = (sp500.get("contribution_top5") or [{}])[0]
    ksp_top1 = (kospi.get("contribution_top5") or [{}])[0]

    today = datetime.now().strftime("%Y년 %m월 %d일")
    return {
        "generated_at":         datetime.now().isoformat(),
        "report_date":          today,
        "analysis_period":      f"{period.get('start','?')} ~ {period.get('end','?')}",
        "generation_method":    "claude_api",
        "market_overview":      parsed.get("market_overview", ""),
        "bullish_factors":      parsed.get("bullish_factors", ""),
        "bearish_factors":      parsed.get("bearish_factors", ""),
        "top_indicator_insight":parsed.get("top_indicator_insight", ""),
        "sp500_stock_insight":  f"{sp_top1.get('name','?')} ({sp_top1.get('stock_return_pct',0):+.1f}%)",
        "kospi_stock_insight":  f"{ksp_top1.get('name','?')} ({ksp_top1.get('stock_return_pct',0):+.1f}%)",
        "sp500_action_plan":    parsed.get("sp500_action_plan", []),
        "kospi_action_plan":    parsed.get("kospi_action_plan", []),
        "monitoring_checklist": parsed.get("monitoring_checklist", []),
        "risk_summary":         " / ".join(risk_factors[:3]),
        "signal_score":         signal.get("score", 50),
        "signal_direction":     signal.get("direction", "neutral"),
        "disclaimer": "본 리포트는 AI 분석 시스템이 자동 생성한 참고 자료입니다. 투자 결정은 개인 책임이며, 전문 투자 자문이 아닙니다.",
    }


def save_final_report_md(narr: dict, results: dict, out_dir: Path) -> Path:
    """FINAL_REPORT.md 생성 — 실제 지표 수치 포함 마크다운 리포트."""
    signal   = results.get("market_signal", {})
    decision = results.get("decision", {})
    ranking  = results.get("indicator_weight_ranking", [])
    ind_sigs = signal.get("indicator_signals", [])

    score     = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    sp_dec    = decision.get("sp500", {})
    ksp_dec   = decision.get("kospi", {})
    today     = narr.get("report_date", datetime.now().strftime("%Y년 %m월 %d일"))
    period    = narr.get("analysis_period", "?")

    dir_map = {"risk-on": "위험 선호", "neutral": "중립", "risk-off": "위험 회피"}
    dir_ko  = dir_map.get(direction, direction)

    # 지표 시그널 테이블
    sig_rows = []
    for s in sorted(ind_sigs, key=lambda x: abs(x.get("z_score", 0)), reverse=True):
        ind  = s.get("indicator", "")
        z    = s.get("z_score", 0)
        w    = s.get("weight", 0)
        bull = "🟢 강세" if s.get("bullish") else "🔴 약세"
        sig_rows.append(f"| {ind} | {z:+.3f} | {w:.4f} | {bull} |")
    sig_table = "\n".join(sig_rows) if sig_rows else "| (없음) | - | - | - |"

    # 가중치 Top5 테이블
    rank_rows = []
    for i, r in enumerate(ranking[:5], 1):
        rank_rows.append(
            f"| {i} | {r.get('indicator','?')} | {r.get('combined_weight',0):.4f} | "
            f"{r.get('sp500_signed_r',0):+.3f} | {r.get('kospi_signed_r',0):+.3f} |"
        )
    rank_table = "\n".join(rank_rows) if rank_rows else "| - | (없음) | - | - | - |"

    sp_plan_md  = "\n".join(f"{i+1}. {p}" for i, p in enumerate(narr.get("sp500_action_plan", [])))
    ksp_plan_md = "\n".join(f"{i+1}. {p}" for i, p in enumerate(narr.get("kospi_action_plan", [])))
    monitor_md  = "\n".join(f"- [ ] {m}" for m in narr.get("monitoring_checklist", []))

    md = f"""# AI Analyzer — 주간 시장 분석 리포트
> 자동 생성: {today} | 분석 기간: {period}

---

## 📊 복합 시그널 요약

| 항목 | 수치 |
|------|------|
| 복합 시그널 점수 | **{score}/100** |
| 시장 방향성 | **{dir_ko}** ({direction}) |
| 강세 지표 수 | {signal.get('bullish_count', 0)}개 |
| 약세 지표 수 | {signal.get('bearish_count', 0)}개 |
| 유효 지표 총수 | {signal.get('total_signals', 0)}개 |

---

## 🎯 의사결정

| 시장 | 행동 | 신뢰도 | 포지션 |
|------|------|--------|--------|
| S&P500 | **{sp_dec.get('action','HOLD')}** | {sp_dec.get('confidence_pct',0):.1f}% | {sp_dec.get('position_size_pct',0):.0f}% |
| 코스피  | **{ksp_dec.get('action','HOLD')}** | {ksp_dec.get('confidence_pct',0):.1f}% | {ksp_dec.get('position_size_pct',0):.0f}% |

---

## 📈 지표별 Z-Score 분석

| 지표 | Z-Score | 가중치 | 방향 |
|------|---------|--------|------|
{sig_table}

---

## 🏆 가중치 Top5 지표

| 순위 | 지표 | Combined Weight | S&P500 r | KOSPI r |
|------|------|-----------------|----------|---------|
{rank_table}

---

## 💬 시장 개요

{narr.get('market_overview', '')}

### 강세 요인
{narr.get('bullish_factors', '')}

### 약세 요인 / 리스크
{narr.get('bearish_factors', '')}

{f"### 핵심 지표 인사이트{chr(10)}{narr.get('top_indicator_insight', '')}" if narr.get('top_indicator_insight') else ''}

---

## 📋 액션플랜

### S&P500
{sp_plan_md}

### 코스피
{ksp_plan_md}

---

## 🔍 주간 모니터링 체크리스트

{monitor_md}

---

## 📌 리스크 요약
{narr.get('risk_summary', '없음')}

---

*{narr.get('disclaimer', '')}*
*생성 방식: {narr.get('generation_method', 'unknown')} | 생성 시각: {narr.get('generated_at', '')}*
"""

    out_path = out_dir / "FINAL_REPORT.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


def generate_narrative_section(narrative: dict) -> str:
    """대시보드 HTML 용 내러티브 섹션 (run_ui_agent.py에서 호출)."""
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
    BASE_DIR = Path(__file__).parent.parent
    OUT_DIR  = BASE_DIR / "output"

    print("=" * 60)
    print("Narrative Agent — Claude API 서브에이전트 모드")
    print("=" * 60)

    results = _load_json(OUT_DIR / "final_results.json")
    if not results:
        print("[FAIL] final_results.json 없음 또는 빈 파일")
        sys.exit(1)

    # Claude API 호출 (API 키 없으면 내부에서 exit(1))
    narr = generate_narrative_llm(results)
    print("  [Narrative] Claude API LLM 생성 성공")

    # ── Done Criteria ──────────────────────────────────────────
    fails = []

    # NA-1: API 키 확인 (여기까지 왔으면 이미 PASS)
    print("  ✓ NA-1 ANTHROPIC_API_KEY 설정됨 PASS")

    # NA-2: 실제 수치 포함 여부
    overview = narr.get("market_overview", "")
    has_numbers = bool(re.search(r'\d+\.?\d*', overview))
    if not has_numbers:
        fails.append("NA-2 market_overview에 실제 수치 없음")
    else:
        print(f"  ✓ NA-2 market_overview 수치 포함 PASS")

    # NA-3: SP500 액션플랜
    if not narr.get("sp500_action_plan"):
        fails.append("NA-3 sp500_action_plan 없음")
    else:
        print(f"  ✓ NA-3 sp500_action_plan {len(narr['sp500_action_plan'])}개 PASS")

    # NA-4: KOSPI 액션플랜
    if not narr.get("kospi_action_plan"):
        fails.append("NA-4 kospi_action_plan 없음")
    else:
        print(f"  ✓ NA-4 kospi_action_plan {len(narr['kospi_action_plan'])}개 PASS")

    # 저장 — narrative.json (대시보드 호환)
    narr_path = OUT_DIR / "narrative.json"
    narr_path.write_text(json.dumps(narr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [저장] {narr_path}")

    # NA-5: FINAL_REPORT.md 생성 + 수치 포함 확인
    report_path = save_final_report_md(narr, results, OUT_DIR)
    report_text = report_path.read_text(encoding="utf-8")
    num_count   = len(re.findall(r'[+-]?\d+\.?\d*', report_text))
    if num_count < 10:
        fails.append(f"NA-5 FINAL_REPORT.md 수치 부족 ({num_count}개 < 10)")
    else:
        print(f"  ✓ NA-5 FINAL_REPORT.md 생성 완료 (수치 {num_count}개) PASS")

    print("\n=== Done Criteria 최종 ===")
    if fails:
        for f in fails:
            print(f"  ✗ {f}")
        print(f"\n[FAIL] Done Criteria 미충족: {fails}")
        sys.exit(1)

    print("[PASS] NA-1~NA-5 전항목 통과")
    print(f"\n시장 개요 (첫 150자):\n{overview[:150]}...")
    print(f"\nSP500 액션플랜:\n" + "\n".join(f"  {i+1}. {p}" for i,p in enumerate(narr.get('sp500_action_plan',[]))))
    print(f"\nKOSPI 액션플랜:\n" + "\n".join(f"  {i+1}. {p}" for i,p in enumerate(narr.get('kospi_action_plan',[]))))
