# -*- coding: utf-8 -*-
"""Phase 14-3 unit tests (Global IB feed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.global_ib_feed import (  # noqa: E402
    derive_implied_global, probe_attempts_log,
)
from tools.consensus.analyze_snapshot import analyze  # noqa: E402


def test_attempts_log_has_5_or_more():
    attempts = probe_attempts_log()
    assert len(attempts) >= 5
    # Each entry has required keys
    for a in attempts:
        for k in ("source", "purpose", "result", "robots_status"):
            assert k in a


def test_derive_implied_global_arithmetic():
    """X12 invariant in unit form."""
    yf_agg = {"n_analysts": 37, "target_mean": 3_105_259.0}
    domestic = {"n_firms": 25, "mean_target": 3_106_000.0}
    out = derive_implied_global(yf_agg, domestic)
    assert out["n_implied_global"] == 12
    # Recompute weighted mean
    lhs = 37 * 3_105_259.0
    dom_n = 37 - 12
    rhs = dom_n * 3_106_000.0 + 12 * out["implied_global_mean_target"]
    assert abs(lhs - rhs) / lhs < 1e-9


def test_derive_implied_global_handles_n_too_small():
    yf_agg = {"n_analysts": 25, "target_mean": 3_000_000.0}
    domestic = {"n_firms": 24, "mean_target": 3_000_000.0}
    out = derive_implied_global(yf_agg, domestic)
    assert out["sample_quality"] == "n_too_small"


def test_derive_implied_global_handles_negative_decomposition():
    """If domestic > yfinance count, return unavailable."""
    yf_agg = {"n_analysts": 10, "target_mean": 3_000_000.0}
    domestic = {"n_firms": 25, "mean_target": 3_000_000.0}
    out = derive_implied_global(yf_agg, domestic)
    assert out["sample_quality"] == "n_too_small"


def test_derive_implied_global_handles_missing_input():
    out = derive_implied_global({}, {})
    assert out["n_implied_global"] is None
    assert out["sample_quality"] == "unavailable"


def test_analyze_q5_aligned_when_gap_small():
    """Q5: when implied gap is within 5%, status = ALIGNED_DIRECTION_AND_LEVEL."""
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083, "static_target_price": 3_177_083,
        "static_eps": 307_655, "static_per": 8.54,
        "close_price_latest": 2_628_000,
        "chart_latest_target_price": 2_470_417,
        "prior_target_price": 2_470_417,
        "target_price_change_1m_pct": 28.61,
        "target_price_change_label": "current_vs_chart_latest_nonnull",
        "estimates": {}, "target_price_series": [],
        "parser_warnings": [], "reconciliation": {},
        "annual_indicators": {}, "quarterly_earnings": {
            "found": True,
            "quarters": [{"yymm": "202603", "op_income_yoy_pct": 397.47}],
        },
        "opinion_breakdown": {"today": {"total": 24}},
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
        "global_ib": {
            "found": True, "n_analysts": 37, "target_mean": 3_105_259.0,
        },
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q5_global_vs_domestic"] == "ALIGNED_DIRECTION_AND_LEVEL"
    assert out["answers"]["Q5_details"]["implied"]["n_implied_global"] == 12


def test_analyze_q5_global_lower_when_negative_gap():
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083, "static_target_price": 3_177_083,
        "static_eps": 307_655, "static_per": 8.54,
        "close_price_latest": 2_628_000,
        "chart_latest_target_price": 2_470_417,
        "prior_target_price": 2_470_417,
        "target_price_change_1m_pct": 28.61,
        "target_price_change_label": "current_vs_chart_latest_nonnull",
        "estimates": {}, "target_price_series": [],
        "parser_warnings": [], "reconciliation": {},
        "annual_indicators": {}, "quarterly_earnings": {
            "found": True,
            "quarters": [{"yymm": "202603", "op_income_yoy_pct": 397.47}],
        },
        "opinion_breakdown": {"today": {"total": 24}},
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_500_000.0},  # higher Korean mean
        "global_ib": {
            "found": True, "n_analysts": 37, "target_mean": 3_100_000.0,  # lower
        },
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    # Expected: implied global < domestic by more than 5%
    impl = out["answers"]["Q5_details"]["implied"]
    assert impl["gap_pct"] < -5.0
    assert out["answers"]["Q5_global_vs_domestic"] == "ALIGNED_DIRECTION_GLOBAL_LOWER"


def test_analyze_q5_insufficient_when_no_global_data():
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083,
        "target_price_change_1m_pct": 28.61,
        "estimates": {}, "target_price_series": [],
        "parser_warnings": [],
        "global_ib": {"found": False},  # no data
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q5_global_vs_domestic"] == "GLOBAL_DATA_INSUFFICIENT"


def test_q5_details_per_firm_jpm_gs_marked_unavailable():
    """Honest labeling per Meta-Audit Agent's pre-implementation concern."""
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083,
        "target_price_change_1m_pct": 28.61,
        "estimates": {}, "target_price_series": [],
        "parser_warnings": [],
        "global_ib": {
            "found": True, "n_analysts": 37, "target_mean": 3_105_259.0,
        },
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q5_details"]["per_firm_jpm_gs_available"] is False
