# -*- coding: utf-8 -*-
"""Phase 14-1 — Consensus snapshot analyzer (Analysis + Meta-Audit Agents).

Input  : parsed dict from naver_parser.parse_wisereport_html
Output : analysis dict with Q1~Q5 answers, 4사분면 classification, and
         meta-audit labels (KCMI bias warning, point-in-time status,
         target_price_role footnote).

Pure function. No I/O. Standard library only.
"""
from __future__ import annotations

from typing import Any, Optional


# Thresholds (configurable; documented in docs/consensus_revision_tracker.md)
CHANGE_UP_THRESHOLD_PCT = 0.5    # 변동률 +0.5% 이상 = UP
CHANGE_DOWN_THRESHOLD_PCT = -0.5  # -0.5% 이하 = DOWN


def _direction_from_pct(pct: Optional[float]) -> str:
    if pct is None:
        return "INSUFFICIENT"
    if pct > CHANGE_UP_THRESHOLD_PCT:
        return "UP"
    if pct < CHANGE_DOWN_THRESHOLD_PCT:
        return "DOWN"
    return "FLAT"


def _eps_change_pct(estimates: dict) -> Optional[float]:
    """Compute YoY-like EPS change between earlier FY (실적) and later
    FY (컨센서스). Returns percent or None if data insufficient."""
    fy_actual = None
    fy_consensus = None
    for k in estimates:
        if "실적" in k:
            fy_actual = k
        elif "컨센서스" in k or "(E)" in k:
            fy_consensus = k
    if not fy_actual or not fy_consensus:
        return None
    eps_a = estimates.get(fy_actual, {}).get("EPS")
    eps_c = estimates.get(fy_consensus, {}).get("EPS")
    if eps_a is None or eps_c is None or eps_a <= 0:
        return None
    return (eps_c - eps_a) / eps_a * 100.0


def classify_quadrant(target_dir: str, eps_dir: str) -> str:
    """4-사분면 분류 (Bradshaw 2013 — target price as sentiment proxy).

    Rules:
      target ↑ + EPS ↑   = TRUE_UPGRADE         (펀더멘털 동반 상향)
      target ↑ + EPS →   = MULTIPLE_EXPANSION   (밸류에이션 리레이팅)
      target ↑ + EPS ↓   = OVERHEATED           (실적 하향에도 목표가 상향)
      target → + EPS ↑   = CONSERVATIVE_IB      (보수적 — 매집 잠재)
      target → + EPS →   = STAGNANT
      target → + EPS ↓   = WEAK_NEGATIVE
      target ↓ + EPS ↑   = MISPRICED_DOWN       (희귀 — 외부충격 가능)
      target ↓ + EPS →   = SENTIMENT_DOWN
      target ↓ + EPS ↓   = TRUE_DOWNGRADE
      anything INSUFFICIENT = INSUFFICIENT
    """
    if target_dir == "INSUFFICIENT" or eps_dir == "INSUFFICIENT":
        return "INSUFFICIENT"
    table = {
        ("UP",   "UP"):   "TRUE_UPGRADE",
        ("UP",   "FLAT"): "MULTIPLE_EXPANSION",
        ("UP",   "DOWN"): "OVERHEATED",
        ("FLAT", "UP"):   "CONSERVATIVE_IB",
        ("FLAT", "FLAT"): "STAGNANT",
        ("FLAT", "DOWN"): "WEAK_NEGATIVE",
        ("DOWN", "UP"):   "MISPRICED_DOWN",
        ("DOWN", "FLAT"): "SENTIMENT_DOWN",
        ("DOWN", "DOWN"): "TRUE_DOWNGRADE",
    }
    return table.get((target_dir, eps_dir), "UNCLASSIFIED")


def assess_data_quality(parsed: dict) -> dict:
    """Evaluator Agent role: 0~1 quality score."""
    score = 0.0
    components = {}
    if parsed.get("investment_opinion") is not None:
        score += 0.15; components["investment_opinion"] = True
    else:
        components["investment_opinion"] = False
    if parsed.get("n_analysts") is not None:
        score += 0.15; components["n_analysts"] = True
    else:
        components["n_analysts"] = False
    if parsed.get("latest_target_price") is not None:
        score += 0.25; components["latest_target_price"] = True
    else:
        components["latest_target_price"] = False
    if parsed.get("target_price_change_1m_pct") is not None:
        score += 0.20; components["target_price_change_1m_pct"] = True
    else:
        components["target_price_change_1m_pct"] = False
    if parsed.get("estimates"):
        score += 0.15; components["estimates_present"] = True
    else:
        components["estimates_present"] = False
    series = parsed.get("target_price_series", [])
    if len([e for e in series if e.get("y") is not None]) >= 3:
        score += 0.10; components["sufficient_series_length"] = True
    else:
        components["sufficient_series_length"] = False
    return {
        "score": round(score, 3),
        "components": components,
    }


def analyze(parsed: dict, ticker: str, company: Optional[str] = None) -> dict:
    """Top-level analyzer. Returns answers to Q1~Q5 + metadata.

    PIT (Phase 14-0-C) override is applied by the pipeline post-analyze,
    not here — this keeps `analyze()` a pure function on `parsed` input
    (Meta-Audit Agent's read-only invariant).
    """
    target_pct = parsed.get("target_price_change_1m_pct")
    target_dir = _direction_from_pct(target_pct)
    q1_source = parsed.get("target_price_change_label") or "insufficient"

    # Phase 14-0-C: parsed dict may have been pre-populated by the pipeline
    # with PIT-derived values. If so, `Q1_source` will already indicate
    # `snapshot_pit_prior_day`. No side effects inside analyze().

    eps_pct = _eps_change_pct(parsed.get("estimates", {}))
    eps_dir = _direction_from_pct(eps_pct)

    # Q3 영업이익 — phase 14-1-B: prefer quarterly_earnings.op_income_yoy_pct
    # of the most recent quarter (annual op_income is not on the page; YoY
    # of the latest reported quarter is the next-best proxy).
    op_pct: Optional[float] = None
    op_source = "insufficient"
    qe = parsed.get("quarterly_earnings", {})
    if qe.get("found") and qe.get("quarters"):
        latest = qe["quarters"][-1]
        if latest.get("op_income_yoy_pct") is not None:
            op_pct = float(latest["op_income_yoy_pct"])
            op_source = f"latest_quarter_yoy({latest.get('yymm')})"
    if op_pct is None:
        # Fall back to estimates dict (legacy path)
        estimates = parsed.get("estimates", {})
        if estimates:
            fy_actual = next((k for k in estimates if "실적" in k), None)
            fy_cons = next(
                (k for k in estimates
                 if "컨센서스" in k or "(E)" in k), None,
            )
            if fy_actual and fy_cons:
                op_a = estimates.get(fy_actual, {}).get("영업이익")
                op_c = estimates.get(fy_cons, {}).get("영업이익")
                if op_a is not None and op_c is not None and op_a > 0:
                    op_pct = (op_c - op_a) / op_a * 100.0
                    op_source = "annual_estimates_table"
    op_dir = _direction_from_pct(op_pct)

    quadrant = classify_quadrant(target_dir, eps_dir)

    # Q5: 글로벌 vs 국내
    # Phase 14-3: yfinance aggregate -> implied global stats
    # Phase 14-4: Korean news + manual input -> NAMED per-firm targets
    q5_status = "GLOBAL_DATA_INSUFFICIENT"
    q5_details: dict[str, Any] = {"per_firm_jpm_gs_available": False}

    # Phase 14-4: check named entries first (takes precedence per Decision Agent rule)
    named_entries = parsed.get("global_ib_named") or []
    high_conf_named = [e for e in named_entries
                        if e.get("confidence") in ("user_verified", "high")]
    if len(high_conf_named) >= 2:
        # Named global IBs with high confidence: Q5 fully resolved
        q5_status = "ALIGNED_BY_NAMED_GLOBAL_IB"
        q5_details["per_firm_jpm_gs_available"] = True
        q5_details["named_entries_count"] = len(named_entries)
        q5_details["high_confidence_count"] = len(high_conf_named)
        q5_details["firms_named"] = sorted({e["firm"] for e in high_conf_named})
    elif len(named_entries) == 1:
        q5_status = "GLOBAL_NAMED_PARTIAL"
        q5_details["named_entries_count"] = 1
        q5_details["firms_named"] = [named_entries[0]["firm"]]

    global_ib = parsed.get("global_ib") or {}
    if q5_status == "GLOBAL_DATA_INSUFFICIENT" and global_ib.get("found"):
        from tools.consensus.global_ib_feed import derive_implied_global
        domestic = (parsed.get("per_firm_targets") or {})
        implied = derive_implied_global(
            global_ib,
            {"n_firms": domestic.get("n_firms"),
             "mean_target": domestic.get("mean_target")},
        )
        q5_details["implied"] = implied
        q5_details["yfinance_n_analysts"] = global_ib.get("n_analysts")
        q5_details["yfinance_mean"] = global_ib.get("target_mean")
        q5_details["per_firm_jpm_gs_available"] = False  # confirmed by audit
        if implied.get("sample_quality") == "ok" and target_dir == "UP":
            # Both yfinance aggregate (which includes both KR + global)
            # and Korean-only consensus show UP direction; gap_pct shows
            # absolute-level divergence.
            gap = implied.get("gap_pct")
            if gap is not None:
                if abs(gap) <= 5.0:
                    q5_status = "ALIGNED_DIRECTION_AND_LEVEL"
                elif gap < -5.0:
                    q5_status = "ALIGNED_DIRECTION_GLOBAL_LOWER"
                elif gap > 5.0:
                    q5_status = "ALIGNED_DIRECTION_GLOBAL_HIGHER"
            else:
                q5_status = "ALIGNED_DIRECTION_UNKNOWN_LEVEL"
        elif implied.get("sample_quality") == "n_too_small":
            q5_status = "GLOBAL_SAMPLE_TOO_SMALL"

    # Meta-Audit labels
    meta_audit = {
        "kr_buy_bias_warning": True,
        "kr_buy_bias_source": "KCMI 2025 (Buy 93.1%, Sell 0.1%, 2020-2024)",
        "point_in_time_status": "snapshot",
        "point_in_time_note": (
            "single fetch; not yet a daily-accumulated point-in-time series. "
            "Naver/WiseReport historical entries may have been retroactively "
            "updated (Ljungqvist 2009)."
        ),
        "target_price_role": "sentiment_valuation_proxy",
        "target_price_role_source": (
            "Bradshaw, Brown, Huang 2013 -- 12-month target price end-of-period "
            "achievement 38%, MAFE ~45%"
        ),
    }

    quality = assess_data_quality(parsed)

    return {
        "schema_version": "0.2",
        "ticker": ticker,
        "company": company,
        "answers": {
            "Q1_target_price_change_pct": target_pct,
            "Q1_direction": target_dir,
            "Q2_eps_change_pct": eps_pct,
            "Q2_direction": eps_dir,
            "Q3_op_income_change_pct": op_pct,
            "Q3_direction": op_dir,
            "Q4_quadrant": quadrant,
            "Q5_global_vs_domestic": q5_status,
            "Q5_details": q5_details,
        },
        "raw_inputs": {
            "investment_opinion": parsed.get("investment_opinion"),
            "n_analysts": parsed.get("n_analysts"),
            "latest_target_price": parsed.get("latest_target_price"),
            "latest_target_price_date": parsed.get("chart_latest_target_date"),
            "prior_target_price": parsed.get("prior_target_price"),
            "target_price_change_label": parsed.get("target_price_change_label"),
            "Q1_source": q1_source,
            "static_target_price": parsed.get("static_target_price"),
            "static_eps": parsed.get("static_eps"),
            "static_per": parsed.get("static_per"),
            "close_price_latest": parsed.get("close_price_latest"),
            "close_price_source": parsed.get("close_price_source"),
            "close_price_as_of": parsed.get("close_price_as_of"),
            "close_price_from_wisereport_chart": parsed.get(
                "close_price_from_wisereport_chart"
            ),
            "chart_latest_target_price": parsed.get("chart_latest_target_price"),
            "q3_source": op_source,
            "opinion_breakdown": parsed.get("opinion_breakdown", {}).get("today", {}),
            "opinion_breakdown_prior": parsed.get("opinion_breakdown", {}).get("a_month_ago", {}),
            "per_firm_targets": parsed.get("per_firm_targets", {}),
            "quarterly_earnings": parsed.get("quarterly_earnings", {}),
            "annual_indicators": parsed.get("annual_indicators", {}),
        },
        "data_quality": quality,
        "meta_audit": meta_audit,
        "reconciliation": parsed.get("reconciliation", {}),
        "global_ib_named": parsed.get("global_ib_named", []),
        "parser_warnings": parsed.get("parser_warnings", []),
    }
