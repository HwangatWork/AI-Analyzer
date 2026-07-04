# -*- coding: utf-8 -*-
"""Analysis + Meta-Audit unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.analyze_snapshot import (  # noqa: E402
    _direction_from_pct,
    classify_quadrant,
    assess_data_quality,
    analyze,
)


def test_direction_thresholds():
    assert _direction_from_pct(None) == "INSUFFICIENT"
    assert _direction_from_pct(5.0) == "UP"
    assert _direction_from_pct(-5.0) == "DOWN"
    assert _direction_from_pct(0.1) == "FLAT"
    assert _direction_from_pct(-0.1) == "FLAT"


def test_quadrant_true_upgrade():
    assert classify_quadrant("UP", "UP") == "TRUE_UPGRADE"


def test_quadrant_multiple_expansion():
    assert classify_quadrant("UP", "FLAT") == "MULTIPLE_EXPANSION"


def test_quadrant_overheated():
    assert classify_quadrant("UP", "DOWN") == "OVERHEATED"


def test_quadrant_conservative_ib():
    assert classify_quadrant("FLAT", "UP") == "CONSERVATIVE_IB"


def test_quadrant_insufficient_when_either_missing():
    assert classify_quadrant("INSUFFICIENT", "UP") == "INSUFFICIENT"
    assert classify_quadrant("UP", "INSUFFICIENT") == "INSUFFICIENT"


def test_quality_score_full():
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "target_price_change_1m_pct": 5.0,
        "estimates": {"2025/12(실적)": {"EPS": 1000}},
        "target_price_series": [{"y": 1}, {"y": 2}, {"y": 3}],
    }
    q = assess_data_quality(parsed)
    assert q["score"] == 1.0


def test_quality_score_empty():
    q = assess_data_quality({"target_price_series": []})
    assert q["score"] == 0.0


def test_analyze_marks_meta_audit_labels():
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "latest_target_price_date": "2026-05-29",
        "prior_target_price": 290_000,
        "target_price_change_1m_pct": 3.4,
        "estimates": {},
        "target_price_series": [],
        "parser_warnings": [],
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["meta_audit"]["kr_buy_bias_warning"] is True
    assert out["meta_audit"]["point_in_time_status"] == "snapshot"
    assert out["meta_audit"]["target_price_role"] == "sentiment_valuation_proxy"


def test_analyze_q5_marked_insufficient():
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "target_price_change_1m_pct": 1.0,
        "estimates": {},
        "target_price_series": [],
        "parser_warnings": [],
    }
    out = analyze(parsed, ticker="000660")
    assert out["answers"]["Q5_global_vs_domestic"] == "GLOBAL_DATA_INSUFFICIENT"


def test_analyze_q4_true_upgrade_path():
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "target_price_change_1m_pct": 5.0,
        "estimates": {
            "2025/12(실적)": {"EPS": 1000.0, "영업이익": 10_000.0},
            "2026/12(컨센서스)": {"EPS": 1100.0, "영업이익": 12_000.0},
        },
        "target_price_series": [],
        "parser_warnings": [],
    }
    out = analyze(parsed, ticker="000660")
    assert out["answers"]["Q1_direction"] == "UP"
    assert out["answers"]["Q2_direction"] == "UP"
    assert out["answers"]["Q3_direction"] == "UP"
    assert out["answers"]["Q4_quadrant"] == "TRUE_UPGRADE"


def test_analyze_q4_overheated_path():
    """target_price ↑ + EPS ↓ → OVERHEATED."""
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "target_price_change_1m_pct": 10.0,
        "estimates": {
            "2025/12(실적)": {"EPS": 1000.0},
            "2026/12(컨센서스)": {"EPS": 800.0},
        },
        "target_price_series": [],
        "parser_warnings": [],
    }
    out = analyze(parsed, ticker="000660")
    assert out["answers"]["Q4_quadrant"] == "OVERHEATED"


def test_analyze_q4_insufficient_when_eps_missing():
    parsed = {
        "investment_opinion": 4.0,
        "n_analysts": 24,
        "latest_target_price": 300_000,
        "target_price_change_1m_pct": 5.0,
        "estimates": {},
        "target_price_series": [],
        "parser_warnings": [],
    }
    out = analyze(parsed, ticker="000660")
    assert out["answers"]["Q4_quadrant"] == "INSUFFICIENT"
