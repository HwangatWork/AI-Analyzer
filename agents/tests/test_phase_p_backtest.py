# -*- coding: utf-8 -*-
"""Regression tests for scripts/phase_p_backtest.py.

Real-data only (FIX-G): loads snapshots from git history, not synthetic fixtures.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "phase_p_backtest", SCRIPTS / "phase_p_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_p_backtest"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pp():
    return _load_module()


# ── Pre-registration gate ────────────────────────────────────────────────

def test_preregistration_gate_valid(pp):
    """Freeze SHA must be an ancestor of HEAD and disk == HEAD."""
    prereg = pp.assert_preregistration()
    assert prereg["schema_version"] == 1
    assert prereg["data_snapshots"]["count"] == 12
    assert len(prereg["data_snapshots"]["commit_shas"]) == 12


# ── Statistical helpers ──────────────────────────────────────────────────

def test_wilson_ci_zero_events(pp):
    lo, hi = pp._wilson_ci(0, 10)
    assert lo == 0.0
    assert hi > 0.0


def test_wilson_ci_all_hits(pp):
    lo, hi = pp._wilson_ci(10, 10)
    assert lo < 1.0
    assert hi == 1.0


def test_wilson_ci_half(pp):
    lo, hi = pp._wilson_ci(5, 10)
    assert 0.2 < lo < 0.5
    assert 0.5 < hi < 0.9


def test_wilson_ci_empty(pp):
    lo, hi = pp._wilson_ci(0, 0)
    assert (lo, hi) == (0.0, 0.0)


# ── Signal normalization ─────────────────────────────────────────────────

def test_normalize_action_sell_avoid_maps_to_sell(pp):
    """Real snapshots use 'SELL/AVOID' — must normalize to SELL."""
    assert pp._normalize_action("SELL/AVOID") == "SELL"


def test_normalize_action_buy_variants(pp):
    assert pp._normalize_action("BUY") == "BUY"
    assert pp._normalize_action("buy strong") == "BUY"


def test_normalize_action_hold_default(pp):
    assert pp._normalize_action("HOLD") == "HOLD"
    assert pp._normalize_action("WAIT") == "HOLD"
    assert pp._normalize_action("neutral") == "HOLD"
    assert pp._normalize_action("") == "HOLD"


# ── Gate variants ────────────────────────────────────────────────────────

def test_apply_gate_unconditional_passes_all(pp):
    assert pp._apply_gate("BUY", 0, "unconditional") == "BUY"
    assert pp._apply_gate("SELL", 5, "unconditional") == "SELL"


def test_apply_gate_60_blocks_low_confidence(pp):
    assert pp._apply_gate("BUY", 59.9, "confidence_gte_60") == "HOLD"
    assert pp._apply_gate("BUY", 60.0, "confidence_gte_60") == "BUY"
    assert pp._apply_gate("SELL", 40, "confidence_gte_60") == "HOLD"


def test_apply_gate_70_stricter(pp):
    assert pp._apply_gate("BUY", 69.9, "confidence_gte_70") == "HOLD"
    assert pp._apply_gate("BUY", 70.0, "confidence_gte_70") == "BUY"


def test_apply_gate_unknown_raises(pp):
    with pytest.raises(ValueError):
        pp._apply_gate("BUY", 50, "confidence_gte_99")


# ── Exclusion filter (P-3) ───────────────────────────────────────────────

def test_passes_exclusion_warn_reason_excludes(pp):
    ok, reason = pp._passes_exclusion({
        "warn_reason": "extreme return",
        "excess_return_pct": 100,
        "n_days": 240,
    })
    assert ok is False
    assert "warn_reason" in reason


def test_passes_exclusion_extreme_return_excludes(pp):
    ok, reason = pp._passes_exclusion({
        "excess_return_pct": 250,
        "n_days": 240,
    })
    assert ok is False
    assert "excess_return_pct" in reason


def test_passes_exclusion_short_history_excludes(pp):
    ok, reason = pp._passes_exclusion({
        "excess_return_pct": 20,
        "n_days": 100,
    })
    assert ok is False
    assert "n_days" in reason


def test_passes_exclusion_clean_ticker_passes(pp):
    ok, reason = pp._passes_exclusion({
        "excess_return_pct": 30,
        "n_days": 240,
    })
    assert ok is True


# ── Real-snapshot integration (FIX-G) ────────────────────────────────────

def test_load_snapshot_real_pipeline_commit(pp):
    """Load one real snapshot (2026-06-19 c944701) and verify schema.

    FIX-G: uses actual git history, not synthetic fixture.
    """
    snap = pp.load_snapshot("c9447019383bda690a86ae6263b62c1812f0a8ee",
                             "output/decision.json")
    assert "sp500" in snap and "kospi" in snap
    assert "action" in snap["sp500"]
    # Historical fact: 2026-06-19 had SP500 SELL/AVOID, KOSPI HOLD (from git)
    assert snap["sp500"]["action"] == "SELL/AVOID"


def test_p4_results_json_matches_frozen_contract(pp):
    """After running P-4, output must contain all 3 variants x 2 assets."""
    out = ROOT / "output" / "phase_p_p4_results.json"
    if not out.exists():
        pytest.skip("P-4 not run yet — run scripts/phase_p_backtest.py p4 first")
    d = json.loads(out.read_text(encoding="utf-8"))
    for v in ("unconditional", "confidence_gte_60", "confidence_gte_70"):
        assert v in d["variants"]
        for a in ("SP500", "KOSPI"):
            assert a in d["variants"][v]
            r = d["variants"][v][a]
            assert "strategy" in r and "benchmark_buy_and_hold" in r
            assert "benchmark_50_50_mix" in r
            # Frozen fact: 12 snapshots produced 0 BUY signals -> 0 trades
            assert r["n_trades"] == 0
            assert r["avg_exposure_pct"] == 0.0


def test_p1_results_top5_less_than_bottom5_in_window(pp):
    """Frozen observation: this window shows top5 hit rate below bottom5.
    Test locks the observation so future changes to weight ranking that
    accidentally restore this signature won't pass silently."""
    out = ROOT / "output" / "phase_p_p1_results.json"
    if not out.exists():
        pytest.skip("P-1 not run yet")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["n_evaluable_snapshots"] == 6
    assert d["top5_total"] == 30
    assert d["bottom5_total"] == 30
    # honest historical fact recorded 2026-07-05
    assert d["top5_hits"] == 11
    assert d["bottom5_hits"] == 18


def test_p2_universe_is_narrow(pp):
    out = ROOT / "output" / "phase_p_p2_results.json"
    if not out.exists():
        pytest.skip("P-2 not run yet")
    d = json.loads(out.read_text(encoding="utf-8"))
    # Frozen fact: union of 12 snapshots' contribution_top5 = 8 unique tickers
    assert d["universe_union_size"] == 8


def test_p3_sp500_zero_evaluable_due_to_warn_reason(pp):
    """Frozen finding: 100% of SP500 beneficiary_top5 tickers carry warn_reason.
    After pre-registered exclusion filter, zero evaluable snapshots remain.
    """
    out = ROOT / "output" / "phase_p_p3_results.json"
    if not out.exists():
        pytest.skip("P-3 not run yet")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["SP500"]["n_evaluable_snapshots"] == 0
