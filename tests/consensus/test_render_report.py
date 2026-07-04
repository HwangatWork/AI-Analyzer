# -*- coding: utf-8 -*-
"""Narrative + UI Agent unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.render_report import (  # noqa: E402
    render_markdown,
    QUADRANT_NARRATIVE,
)


def _sample_analysis(quadrant: str = "TRUE_UPGRADE") -> dict:
    return {
        "ticker": "000660",
        "company": "SK hynix",
        "answers": {
            "Q1_target_price_change_pct": 5.0,
            "Q1_direction": "UP",
            "Q2_eps_change_pct": 8.0,
            "Q2_direction": "UP",
            "Q3_op_income_change_pct": 10.0,
            "Q3_direction": "UP",
            "Q4_quadrant": quadrant,
            "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT",
        },
        "raw_inputs": {
            "investment_opinion": 4.0,
            "n_analysts": 24,
            "latest_target_price": 300_000.0,
            "latest_target_price_date": "2026-06-29",
            "prior_target_price": 285_000.0,
        },
        "data_quality": {"score": 0.85, "components": {}},
        "meta_audit": {
            "kr_buy_bias_warning": True,
            "kr_buy_bias_source": "KCMI 2025",
            "point_in_time_status": "snapshot",
            "point_in_time_note": "single fetch",
            "target_price_role": "sentiment_valuation_proxy",
            "target_price_role_source": "Bradshaw 2013",
        },
        "parser_warnings": [],
    }


def test_render_contains_company_and_ticker():
    md = render_markdown(_sample_analysis())
    assert "SK hynix" in md
    assert "000660" in md


def test_render_marks_quadrant():
    md = render_markdown(_sample_analysis("TRUE_UPGRADE"))
    assert "TRUE_UPGRADE" in md
    assert QUADRANT_NARRATIVE["TRUE_UPGRADE"].split(".")[0][:10] in md


def test_render_includes_kcmi_warning():
    md = render_markdown(_sample_analysis())
    assert "한국 매수편향" in md
    assert "KCMI" in md


def test_render_includes_bradshaw_footnote():
    md = render_markdown(_sample_analysis())
    assert "Bradshaw" in md
    assert "38%" in md  # achievement rate quoted


def test_render_q5_insufficient_path():
    md = render_markdown(_sample_analysis())
    assert "GLOBAL_DATA_INSUFFICIENT" in md


def test_render_handles_missing_values():
    a = _sample_analysis("INSUFFICIENT")
    a["raw_inputs"]["latest_target_price"] = None
    a["answers"]["Q1_target_price_change_pct"] = None
    a["answers"]["Q2_eps_change_pct"] = None
    md = render_markdown(a)
    assert "N/A" in md


def test_render_is_cp949_safe_in_critical_lines():
    """The Markdown should not contain U+2014 (em dash). It may contain Korean
    characters which are fine for file output (UTF-8) but the success line
    must remain ASCII-safe stdout-compatible."""
    md = render_markdown(_sample_analysis())
    assert "—" not in md  # no em-dash anywhere


def test_render_lists_parser_warnings_when_present():
    a = _sample_analysis()
    a["parser_warnings"] = ["chart_data2_not_found"]
    md = render_markdown(a)
    assert "chart_data2_not_found" in md
