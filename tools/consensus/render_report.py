# -*- coding: utf-8 -*-
"""Phase 14-1 — Markdown report renderer (Narrative + UI Agents).

Input  : analysis dict from analyze_snapshot.analyze
Output : Markdown string suitable for FINAL_REPORT.md or stdout display.

ASCII-safe stdout (no em-dash). Korean narrative.
"""
from __future__ import annotations

from typing import Optional


QUADRANT_NARRATIVE = {
    "TRUE_UPGRADE":         "목표가·EPS 모두 상향. 펀더멘털 기반 정상 업그레이드.",
    "MULTIPLE_EXPANSION":   "목표가만 상향, EPS 정체. 밸류에이션 리레이팅(주의).",
    "OVERHEATED":           "EPS 하향에도 목표가 상향. 과열 신호 가능.",
    "CONSERVATIVE_IB":      "EPS 상향에도 목표가 정체. 추가 상향 잠재(매집 기회 가능).",
    "STAGNANT":             "변화 없음.",
    "WEAK_NEGATIVE":        "EPS 하향, 목표가 정체. 부정적 흐름 초기.",
    "MISPRICED_DOWN":       "EPS 상향에도 목표가 하향. 외부충격 또는 일시적 mispricing 가능.",
    "SENTIMENT_DOWN":       "목표가 하향, EPS 정체. 센티먼트 약화.",
    "TRUE_DOWNGRADE":       "목표가·EPS 모두 하향. 펀더멘털 동반 약화.",
    "INSUFFICIENT":         "Q1~Q4 답하기 위한 데이터가 부족합니다.",
    "UNCLASSIFIED":         "분류 불가.",
}


DIRECTION_KO = {
    "UP": "상승",
    "DOWN": "하락",
    "FLAT": "정체",
    "INSUFFICIENT": "데이터 부족",
}


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def _fmt_money_krw(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"{x:,.0f}원"


def render_markdown(analysis: dict) -> str:
    ticker = analysis.get("ticker", "?")
    company = analysis.get("company") or "(unknown)"
    ans = analysis.get("answers", {})
    raw = analysis.get("raw_inputs", {})
    meta = analysis.get("meta_audit", {})
    quality = analysis.get("data_quality", {})
    warnings = analysis.get("parser_warnings", [])

    q4 = ans.get("Q4_quadrant", "UNCLASSIFIED")
    q4_text = QUADRANT_NARRATIVE.get(q4, "분류 불가.")

    lines: list[str] = []
    lines.append(f"# Consensus Snapshot -- {company} ({ticker})")
    lines.append("")
    lines.append(
        f"- 데이터 시점 상태: **{meta.get('point_in_time_status','unknown')}** "
        "(daily 누적 시작 전 단일 스냅샷)"
    )
    lines.append(
        f"- 데이터 품질 점수: **{quality.get('score', 0.0):.2f}** / 1.00"
    )
    lines.append("")
    lines.append("## 기본 컨센서스")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("|---|---|")
    lines.append(
        f"| 투자의견 (1~5 scale) | "
        f"{raw.get('investment_opinion') if raw.get('investment_opinion') is not None else 'N/A'} |"
    )
    lines.append(
        f"| 추정기관 수 | {raw.get('n_analysts') or 'N/A'} |"
    )
    lines.append(
        f"| 최근 컨센서스 목표주가 | "
        f"{_fmt_money_krw(raw.get('latest_target_price'))} "
        f"({raw.get('latest_target_price_date') or 'N/A'} 기준) |"
    )
    lines.append(
        f"| 1개월 전 목표주가 | {_fmt_money_krw(raw.get('prior_target_price'))} |"
    )
    lines.append(
        f"| 1개월 변화율 | "
        f"{_fmt_pct(ans.get('Q1_target_price_change_pct'))} |"
    )
    lines.append("")

    # Arithmetic sanity-check block (RCA 2026-06-30 + OL-8 2026-07-04)
    static_eps = raw.get("static_eps")
    static_per = raw.get("static_per")
    close_latest = raw.get("close_price_latest")  # LIVE FDR/yfinance value
    close_source = raw.get("close_price_source")
    close_as_of = raw.get("close_price_as_of")
    close_chart = raw.get("close_price_from_wisereport_chart")  # WiseReport chart
    static_tgt = raw.get("static_target_price")
    chart_tgt = raw.get("chart_latest_target_price")
    if any(v is not None for v in (static_eps, static_per, close_latest, close_chart)):
        lines.append("## 산술 일관성 점검 (사용자 sanity-check 용)")
        lines.append("")
        lines.append("| 항목 | 값 |")
        lines.append("|---|---|")
        if static_eps is not None:
            lines.append(f"| EPS (static table) | {_fmt_money_krw(static_eps)} |")
        if static_per is not None:
            lines.append(f"| PER (static table) | {static_per} 배 |")
        if static_eps is not None and static_per is not None:
            implied = static_eps * static_per
            lines.append(
                f"| PER × EPS = 함의 주가 | {_fmt_money_krw(implied)} |"
            )
        if close_latest is not None:
            source_note = ""
            if close_source == "FinanceDataReader":
                source_note = f" (FDR 라이브 {close_as_of or ''})".rstrip()
            elif close_source == "yfinance":
                source_note = f" (yfinance 라이브 {close_as_of or ''})".rstrip()
            elif close_source and "chart" in close_source:
                source_note = " (WiseReport chart — 라이브 fetch 실패 fallback)"
            elif close_source == "fixture_mode_no_live_fetch":
                source_note = " (fixture 모드)"
            lines.append(
                f"| 현재 주가{source_note} | {_fmt_money_krw(close_latest)} |"
            )
        if (close_chart is not None and close_latest is not None
                and close_chart != close_latest):
            lines.append(
                f"| WiseReport chart close (자기일관성 참고) | "
                f"{_fmt_money_krw(close_chart)} |"
            )
        # Self-consistency invariant compares against chart close (WiseReport
        # native), not live close, because PER/EPS in the static table were
        # computed by WiseReport against its own chart close snapshot.
        if static_eps is not None and static_per is not None \
                and close_chart is not None and close_chart > 0:
            implied = static_eps * static_per
            diff_pct = (implied - close_chart) / close_chart * 100
            lines.append(
                f"| PER×EPS vs chart close (WiseReport 자기일관성) | "
                f"{_fmt_pct(diff_pct)} "
                f"({'OK' if abs(diff_pct) < 1 else '경고'}) |"
            )
        # Stale detection: live vs chart divergence
        if (close_latest is not None and close_chart is not None
                and close_latest > 0 and close_chart > 0
                and close_latest != close_chart):
            gap = (close_chart - close_latest) / close_latest * 100
            stale_mark = "OK" if abs(gap) < 5 else "STALE"
            lines.append(
                f"| 라이브 vs WiseReport chart 차이 | {_fmt_pct(gap)} "
                f"({stale_mark}) |"
            )
        if static_tgt is not None and chart_tgt is not None and chart_tgt > 0:
            gap = (static_tgt - chart_tgt) / chart_tgt * 100
            lines.append(
                f"| 현재(static) vs 1개월전(chart) target | "
                f"{_fmt_pct(gap)} |"
            )
        lines.append("")

    # Phase 14-1-B: opinion breakdown + per-firm + quarterly op_income
    breakdown = raw.get("opinion_breakdown") or {}
    if breakdown and any(v is not None for k, v in breakdown.items() if k != "total"):
        lines.append("## 투자의견 분포 (Buy / Hold / Sell)")
        lines.append("")
        lines.append("| 의견 | 오늘 | 1개월 전 |")
        lines.append("|---|---:|---:|")
        prior = raw.get("opinion_breakdown_prior") or {}
        for label, key in [
            ("강력매수", "strong_buy"),
            ("매수", "buy"),
            ("중립 (Hold)", "hold"),
            ("매도", "sell"),
            ("강력매도", "strong_sell"),
        ]:
            t = breakdown.get(key)
            p = prior.get(key)
            t_str = "0" if t is None else str(t)
            p_str = "0" if p is None else str(p)
            lines.append(f"| {label} | {t_str} | {p_str} |")
        total_t = breakdown.get("total") or 0
        total_p = prior.get("total") or 0
        lines.append(f"| **합계** | **{total_t}** | **{total_p}** |")
        lines.append("")

    pft = raw.get("per_firm_targets") or {}
    if pft.get("n_firms"):
        lines.append("## 증권사별 목표주가 (per-firm)")
        lines.append("")
        lines.append(
            f"- 추출된 기관 수: **{pft['n_firms']}**개 / "
            f"최고 **{_fmt_money_krw(pft.get('high_target'))}** / "
            f"최저 **{_fmt_money_krw(pft.get('low_target'))}** / "
            f"평균 **{_fmt_money_krw(pft.get('mean_target'))}**"
        )
        lines.append("")
        lines.append("| 증권사 | 작성일 | 목표가 | 이전 | 변동률 | 의견 |")
        lines.append("|---|---|---:|---:|---:|---|")
        for f in pft.get("firms", [])[:15]:  # show top 15 most recent
            lines.append(
                f"| {f.get('firm','')} | {f.get('report_date','')} | "
                f"{_fmt_money_krw(f.get('target_price'))} | "
                f"{_fmt_money_krw(f.get('prior_target_price'))} | "
                f"{_fmt_pct(f.get('change_pct'))} | "
                f"{f.get('rating','')} |"
            )
        if pft["n_firms"] > 15:
            lines.append(f"| ... | (+{pft['n_firms']-15} more) | | | | |")
        lines.append("")

    qe = raw.get("quarterly_earnings") or {}
    if qe.get("found") and qe.get("quarters"):
        lines.append("## 분기 실적 추이 (매출액 · 영업이익)")
        lines.append("")
        lines.append("| 분기 | 매출 cons | 매출 actual | 영업이익 cons | 영업이익 actual | 영업이익 YoY |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for q in qe["quarters"]:
            lines.append(
                f"| {q['yymm']} | "
                f"{_fmt_money_krw(q.get('revenue_consensus'))} | "
                f"{_fmt_money_krw(q.get('revenue_actual'))} | "
                f"{_fmt_money_krw(q.get('op_income_consensus'))} | "
                f"{_fmt_money_krw(q.get('op_income_actual'))} | "
                f"{_fmt_pct(q.get('op_income_yoy_pct'))} |"
            )
        lines.append("- 단위: 매출액·영업이익 = 억원")
        lines.append("")

    # Phase 14-4: Named Global IB Targets (per-firm) — comes BEFORE aggregate
    named = analysis.get("global_ib_named") or []
    if named:
        lines.append("## Named Global IB Targets (per-firm)")
        lines.append("")
        lines.append("| IB 명 | 목표가 | 보고일 | 신뢰도 | 출처 | Stale? |")
        lines.append("|---|---:|---|---|---|---|")
        for e in named:
            badge = ""
            if e.get("extraction_method") == "manual":
                badge = " [user-verified PDF]"
            stale_mark = "STALE" if e.get("is_stale") else ""
            source_label = (
                "manual" if e.get("extraction_method") == "manual"
                else "news"
            )
            lines.append(
                f"| {e.get('firm','')}{badge} | "
                f"{_fmt_money_krw(e.get('target_price'))} | "
                f"{e.get('report_date','N/A')} | "
                f"{e.get('confidence','?')} | {source_label} | {stale_mark} |"
            )
        lines.append("")
        lines.append(
            "> 정확도 주의: 뉴스 기반 추출은 한국 기사가 여러 종목 목표가를 "
            "동시 언급할 때 attribution 오류 가능. 매뉴얼 입력(`configs/"
            "manual_global_ib_targets.json`)이 user_verified 로 최우선."
        )
        lines.append("")

    # Phase 14-3: Global IB section
    q5_details = ans.get("Q5_details") or {}
    yf_n = q5_details.get("yfinance_n_analysts")
    yf_mean = q5_details.get("yfinance_mean")
    implied = q5_details.get("implied") or {}
    if yf_n or yf_mean:
        lines.append("## 글로벌 IB 집계 (yfinance — per-firm 명단 없음)")
        lines.append("")
        lines.append("| 항목 | 값 |")
        lines.append("|---|---|")
        lines.append(f"| 전체 (KR + 글로벌) analysts | {yf_n} |")
        lines.append(f"| 전체 평균 목표가 | {_fmt_money_krw(yf_mean)} |")
        nig = implied.get("n_implied_global")
        if nig is not None and yf_n is not None:
            domestic_n = yf_n - nig
            lines.append(
                f"| 추정 글로벌 IB 수 ({yf_n} - {domestic_n}) | {nig} |"
            )
        igt = implied.get("implied_global_mean_target")
        if igt is not None:
            lines.append(
                f"| 추정 글로벌 IB 평균 목표가 | {_fmt_money_krw(igt)} |"
            )
        gap = implied.get("gap_pct")
        if gap is not None:
            lines.append(
                f"| 글로벌 vs 국내 평균 격차 | {_fmt_pct(gap)} |"
            )
        lines.append("")
        lines.append(
            "> 주의: yfinance 는 per-firm 이름을 노출하지 않음. JPM/Goldman "
            "Sachs 등 개별 IB 의 목표가는 무료 채널로 수집 불가 (Phase 14-3 audit)."
        )
        lines.append("")

    lines.append("## AI 분석 (Q1~Q5)")
    lines.append("")
    lines.append("| 질문 | 결과 | 변화율 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| Q1 목표주가 추세 | "
        f"{DIRECTION_KO.get(ans.get('Q1_direction','INSUFFICIENT'))} | "
        f"{_fmt_pct(ans.get('Q1_target_price_change_pct'))} |"
    )
    lines.append(
        f"| Q2 EPS 추세 | "
        f"{DIRECTION_KO.get(ans.get('Q2_direction','INSUFFICIENT'))} | "
        f"{_fmt_pct(ans.get('Q2_eps_change_pct'))} |"
    )
    lines.append(
        f"| Q3 영업이익 추세 | "
        f"{DIRECTION_KO.get(ans.get('Q3_direction','INSUFFICIENT'))} | "
        f"{_fmt_pct(ans.get('Q3_op_income_change_pct'))} |"
    )
    lines.append(
        f"| Q4 4사분면 분류 | **{q4}** | -- |"
    )
    lines.append(
        f"| Q5 글로벌 vs 국내 | "
        f"{ans.get('Q5_global_vs_domestic','INSUFFICIENT')} | -- |"
    )
    lines.append("")

    lines.append("## 코멘트")
    lines.append("")
    lines.append(q4_text)
    lines.append("")

    lines.append("## 데이터 해석 주의사항")
    lines.append("")
    if meta.get("kr_buy_bias_warning"):
        lines.append(
            f"- **한국 매수편향 주의**: {meta.get('kr_buy_bias_source','')}. "
            "투자의견 수치 자체는 신호 가치가 낮으므로 EPS / 목표가 revision 을 우선."
        )
    lines.append(
        f"- **목표주가 역할**: {meta.get('target_price_role','')} -- "
        f"{meta.get('target_price_role_source','')}. "
        "절대 가격 예측이 아닌 sentiment / valuation proxy 로 해석."
    )
    lines.append(
        f"- **시점 상태**: {meta.get('point_in_time_note','')}"
    )
    if warnings:
        lines.append(
            "- **파서 경고**: " + ", ".join(warnings)
        )
    lines.append("")

    lines.append("## 참고 (footnote)")
    lines.append("")
    lines.append(
        "- KCMI 2025, *Optimism Bias in Analyst Research*: 2020-2024 한국 sell-side "
        "Buy 93.1%, Sell 0.1%."
    )
    lines.append(
        "- Bradshaw, Brown, Huang 2013, *Review of Accounting Studies*: 12-month "
        "target price 달성률 38%, 평균 절대 오차 ~45%."
    )
    lines.append(
        "- Ljungqvist, Malloy, Marston 2009, *Journal of Finance*: I/B/E/S 과거 "
        "레코드의 retroactive 변경 1.6%~21.7%."
    )

    return "\n".join(lines) + "\n"
