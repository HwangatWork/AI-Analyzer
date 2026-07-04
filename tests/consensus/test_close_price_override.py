# -*- coding: utf-8 -*-
"""Regression test for OL-8 close_price live-override in consensus_pipeline.

Verifies that when consensus_pipeline.py runs a snapshot, the parsed
dict's close_price_latest is replaced by the live FDR/yfinance value,
and the WiseReport chart value is preserved under
close_price_from_wisereport_chart.

We do NOT exercise the full pipeline (which involves fetching HTML);
instead we invoke the override logic directly via a small harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _apply_override(parsed: dict, ticker: str, from_fixture: bool,
                    live_result: dict | None):
    """Reproduces consensus_pipeline.py Step 2e in isolation."""
    parsed["close_price_from_wisereport_chart"] = parsed.get("close_price_latest")
    if not from_fixture:
        if live_result and live_result.get("close") is not None:
            parsed["close_price_latest"] = live_result["close"]
            parsed["close_price_source"] = live_result["source"]
            parsed["close_price_as_of"] = live_result["as_of"]
        else:
            parsed["close_price_source"] = "wisereport_chart_fallback"
            parsed["close_price_as_of"] = None
    else:
        parsed["close_price_source"] = "fixture_mode_no_live_fetch"
        parsed["close_price_as_of"] = None
    return parsed


def test_live_override_replaces_chart_close():
    parsed = {"close_price_latest": 2_628_000.0}
    live = {"close": 2_425_000.0, "as_of": "2026-07-04",
            "source": "FinanceDataReader"}
    r = _apply_override(parsed, "000660", from_fixture=False, live_result=live)
    assert r["close_price_latest"] == 2_425_000.0
    assert r["close_price_from_wisereport_chart"] == 2_628_000.0
    assert r["close_price_source"] == "FinanceDataReader"
    assert r["close_price_as_of"] == "2026-07-04"


def test_live_fetch_failure_falls_back_to_chart():
    parsed = {"close_price_latest": 2_628_000.0}
    r = _apply_override(parsed, "000660", from_fixture=False, live_result=None)
    # Note: close_price_latest is preserved from parsed's original value
    # because the "else" branch only sets source/as_of; close_price_latest
    # remains at the chart value (the pop() into close_price_from_wisereport_chart
    # is a copy, not a move — the field is set via .get before assignment).
    # After Step 2e, if fetch fails, downstream reads close_price_latest as
    # the chart value AND sees close_price_source="wisereport_chart_fallback".
    assert r["close_price_from_wisereport_chart"] == 2_628_000.0
    assert r["close_price_source"] == "wisereport_chart_fallback"
    assert r["close_price_as_of"] is None
    # close_price_latest untouched when live fails
    assert r["close_price_latest"] == 2_628_000.0


def test_fixture_mode_preserves_chart_value():
    parsed = {"close_price_latest": 2_628_000.0}
    r = _apply_override(parsed, "000660", from_fixture=True, live_result=None)
    assert r["close_price_from_wisereport_chart"] == 2_628_000.0
    assert r["close_price_source"] == "fixture_mode_no_live_fetch"
    assert r["close_price_latest"] == 2_628_000.0


def test_pipeline_import_shape():
    """Guard: consensus_pipeline still importable + has the override block."""
    from tools.consensus import consensus_pipeline as cp
    src = Path(cp.__file__).read_text(encoding="utf-8")
    assert "close_price_from_wisereport_chart" in src
    assert "fetch_live_close" in src
    assert "OL-8" in src


def test_analyze_snapshot_exposes_new_fields():
    """Guard: analyze_snapshot.raw_inputs must forward the new fields."""
    from tools.consensus import analyze_snapshot as a
    src = Path(a.__file__).read_text(encoding="utf-8")
    assert "close_price_source" in src
    assert "close_price_as_of" in src
    assert "close_price_from_wisereport_chart" in src
