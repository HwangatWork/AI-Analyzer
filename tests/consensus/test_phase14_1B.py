# -*- coding: utf-8 -*-
"""Phase 14-1-B unit tests (parser completeness)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.naver_parser import (  # noqa: E402
    parse_opinion_breakdown,
    parse_quarterly_earnings,
    parse_annual_indicators,
    parse_per_firm_targets,
    parse_wisereport_html,
)
from tools.consensus.analyze_snapshot import analyze  # noqa: E402


FIXTURE = (
    Path(__file__).parent / "fixtures" / "wisereport_000660_sample.html"
)


@pytest.fixture(scope="module")
def html_text():
    return FIXTURE.read_text(encoding="utf-8")


# ---------- Opinion breakdown ----------

def test_opinion_breakdown_today_sums_to_static_n_analysts(html_text):
    parsed = parse_wisereport_html(html_text)
    today = parsed["opinion_breakdown"]["today"]
    static_n = parsed["n_analysts"]
    assert today["total"] == static_n, (
        f"breakdown total {today['total']} != static n_analysts {static_n}"
    )


def test_opinion_breakdown_uses_strong_buy_label(html_text):
    """WiseReport uses 강력매수, not 적극매수 (regression for Phase 14-1-B fix)."""
    today = parse_opinion_breakdown(html_text)["today"]
    assert today["strong_buy"] is not None
    assert today["buy"] is not None


def test_opinion_breakdown_empty_html():
    ob = parse_opinion_breakdown("<html></html>")
    assert ob["found"] is False
    assert ob["today"]["total"] is None


# ---------- Quarterly earnings ----------

def test_quarterly_earnings_has_3_quarters(html_text):
    qe = parse_quarterly_earnings(html_text)
    assert qe["found"] is True
    assert len(qe["quarters"]) == 3
    assert qe["yymm"] == ["202509", "202512", "202603"]


def test_quarterly_op_income_yoy_positive_for_recent_cycle(html_text):
    """Semiconductor super-cycle: SK hynix op income YoY% should be > 50%."""
    qe = parse_quarterly_earnings(html_text)
    latest = qe["quarters"][-1]
    assert latest["op_income_yoy_pct"] is not None
    assert latest["op_income_yoy_pct"] > 50.0


def test_quarterly_surprise_sign_convention(html_text):
    """Verify Surprise % = (actual - consensus) / consensus * 100 by recomputing."""
    qe = parse_quarterly_earnings(html_text)
    for q in qe["quarters"]:
        cons = q["op_income_consensus"]
        act = q["op_income_actual"]
        surprise = q["op_income_surprise_pct"]
        if cons and act and surprise is not None and cons != 0:
            expected = (act - cons) / cons * 100
            assert abs(surprise - expected) < 0.5, (
                f"{q['yymm']}: reported surprise {surprise} != "
                f"recomputed {expected:.2f}"
            )


# ---------- Annual indicators ----------

def test_annual_indicators_extract_PER_EPS(html_text):
    ai = parse_annual_indicators(html_text)
    assert ai["found"] is True
    assert "PER" in ai["metrics"]
    assert "EPS" in ai["metrics"]
    # 2026 PER should match static table per (8.54)
    per_vals = ai["metrics"]["PER"]
    assert len(per_vals) >= 2
    assert abs(per_vals[1] - 8.54) < 0.01


# ---------- Per-firm targets ----------

def test_per_firm_targets_found_with_at_least_15_firms(html_text):
    pft = parse_per_firm_targets(html_text)
    assert pft["found"] is True
    assert pft["n_firms"] >= 15
    # high > low > 0
    assert pft["high_target"] > pft["low_target"] > 0
    # mean between low and high
    assert pft["low_target"] <= pft["mean_target"] <= pft["high_target"]


def test_per_firm_includes_user_requested_brokers(html_text):
    """User explicitly asked for 미래에셋 and 삼성증권. Both must be present."""
    pft = parse_per_firm_targets(html_text)
    firm_names = [f["firm"] for f in pft["firms"]]
    assert any("미래에셋" in n for n in firm_names), \
        f"미래에셋 missing, got: {firm_names}"
    assert any("삼성" in n for n in firm_names), \
        f"삼성 missing, got: {firm_names}"


def test_per_firm_target_change_consistent(html_text):
    """For each firm row, change_pct ≈ (target - prior) / prior * 100."""
    pft = parse_per_firm_targets(html_text)
    bad = []
    for f in pft["firms"]:
        t, p, c = f["target_price"], f["prior_target_price"], f["change_pct"]
        if t and p and c is not None and p > 0:
            expected = (t - p) / p * 100
            if abs(c - expected) > 0.5:
                bad.append((f["firm"], c, expected))
    assert not bad, f"change_pct inconsistencies: {bad[:3]}"


# ---------- Q3 analyzer integration ----------

def test_Q3_op_income_uses_quarterly_yoy(html_text):
    parsed = parse_wisereport_html(html_text)
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q3_direction"] == "UP"
    assert out["answers"]["Q3_op_income_change_pct"] > 50.0
    assert "latest_quarter_yoy" in out["raw_inputs"]["q3_source"]


# ---------- Internal invariant: breakdown total ≡ n_analysts ----------

def test_n_analysts_breakdown_mismatch_warning_absent_on_clean_data(html_text):
    parsed = parse_wisereport_html(html_text)
    mismatches = [w for w in parsed["parser_warnings"]
                   if "n_analysts_breakdown_mismatch" in w]
    assert not mismatches, f"unexpected mismatch warning: {mismatches}"
