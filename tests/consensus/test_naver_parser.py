# -*- coding: utf-8 -*-
"""Fixture-based parser tests (Validation Agent unit).

Uses tests/consensus/fixtures/wisereport_000660_sample.html — a real
WiseReport response saved during live smoke test (Phase 14-0-B2,
2026-06-30). No network access in any test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.naver_parser import (  # noqa: E402
    parse_chart_data2,
    derive_target_price_trend,
    parse_opinion_and_analysts,
    parse_wisereport_html,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "wisereport_000660_sample.html"
)


@pytest.fixture(scope="module")
def html_text():
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_exists():
    assert FIXTURE.exists()
    assert FIXTURE.stat().st_size > 50_000


def test_chart_data2_extracted(html_text):
    chart = parse_chart_data2(html_text)
    assert chart["found"] is True
    assert len(chart["target_price_series"]) >= 10
    assert len(chart["close_price_series"]) >= 10
    # Each entry has x_ms (epoch) and y (price or None)
    for entry in chart["target_price_series"]:
        assert "x_ms" in entry
        assert "y" in entry


def test_chart_data2_missing_returns_empty():
    chart = parse_chart_data2("<html>no chart</html>")
    assert chart["found"] is False
    assert chart["target_price_series"] == []


def test_target_price_trend_uses_latest_non_null(html_text):
    chart = parse_chart_data2(html_text)
    trend = derive_target_price_trend(chart["target_price_series"])
    assert trend["latest_target_price"] is not None
    assert trend["latest_target_price"] > 0
    assert trend["latest_target_price_date"] is not None
    # prior is the second-to-last non-null
    if trend["prior_target_price"] is not None:
        assert trend["target_price_change_1m_pct"] is not None


def test_target_price_trend_empty_series():
    trend = derive_target_price_trend([])
    assert trend["latest_target_price"] is None
    assert trend["target_price_change_1m_pct"] is None


def test_target_price_trend_single_entry():
    series = [{"x_ms": 1_700_000_000_000, "y": 300_000.0}]
    trend = derive_target_price_trend(series)
    assert trend["latest_target_price"] == 300_000.0
    assert trend["prior_target_price"] is None
    assert trend["target_price_change_1m_pct"] is None


def test_target_price_trend_skips_null_entries():
    series = [
        {"x_ms": 1_700_000_000_000, "y": 100_000.0},
        {"x_ms": 1_702_000_000_000, "y": None},  # gap
        {"x_ms": 1_704_000_000_000, "y": 120_000.0},
    ]
    trend = derive_target_price_trend(series)
    assert trend["latest_target_price"] == 120_000.0
    assert trend["prior_target_price"] == 100_000.0
    assert trend["target_price_change_1m_pct"] == pytest.approx(20.0, abs=1e-6)


def test_opinion_and_analysts_extracted(html_text):
    op = parse_opinion_and_analysts(html_text)
    # investment_opinion should be a small numeric rating 1.0 ~ 5.0
    assert op["investment_opinion"] is not None
    assert 1.0 <= op["investment_opinion"] <= 5.0
    # n_analysts is an integer 1..1000
    assert op["n_analysts"] is not None
    assert 1 <= int(op["n_analysts"]) <= 1000


def test_full_parse_returns_required_keys(html_text):
    result = parse_wisereport_html(html_text)
    required = {
        "schema_version", "investment_opinion", "n_analysts",
        "target_price_series", "close_price_series",
        "latest_target_price",
        "static_target_price", "static_eps", "static_per",
        "close_price_latest",
        "chart_latest_target_price", "chart_latest_target_date",
        "prior_target_price", "target_price_change_1m_pct",
        "target_price_change_label",
        "estimates", "reconciliation", "parser_warnings",
    }
    assert required.issubset(result.keys())


def test_static_table_extracts_authoritative_target_price(html_text):
    """RCA 2026-06-30: static table must take priority over chartData2."""
    result = parse_wisereport_html(html_text)
    # On the fixture, the static table holds 3,177,083 (authoritative
    # current consensus) while chartData2's latest non-null is 2,470,417
    # (one month old). The parser must prefer the static value.
    assert result["static_target_price"] == 3_177_083.0
    assert result["latest_target_price"] == result["static_target_price"]
    assert result["chart_latest_target_price"] == 2_470_417.0


def test_per_eps_close_invariant_within_1_percent(html_text):
    """RCA 2026-06-30: arithmetic invariant PER * EPS ~= close."""
    r = parse_wisereport_html(html_text)
    per = r["static_per"]
    eps = r["static_eps"]
    close = r["close_price_latest"]
    assert per is not None and eps is not None and close is not None
    implied = per * eps
    diff_pct = (implied - close) / close * 100
    assert abs(diff_pct) < 1.0, f"PER*EPS vs close diff {diff_pct:+.4f}%"


def test_reconciliation_records_static_vs_chart_gap(html_text):
    r = parse_wisereport_html(html_text)
    rec = r["reconciliation"]
    assert "static_target" in rec
    assert "chart_latest_target" in rec
    assert "static_vs_chart_target_diff_pct" in rec


def test_full_parse_empty_html_marks_warnings():
    result = parse_wisereport_html("<html></html>")
    assert "chart_data2_not_found" in result["parser_warnings"]
    assert result["latest_target_price"] is None
