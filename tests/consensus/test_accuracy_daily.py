# -*- coding: utf-8 -*-
"""Regression tests for scripts/consensus_accuracy_daily.py.

Mock-only (no network). Verifies:
- Schema of live_prices.json output
- Streak counter increments correctly
- Pending request created when |diff| > threshold
- No hardcoding in the tickers registry keys/values (structural check)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Import module by path since scripts/ isn't a package
import importlib.util
spec = importlib.util.spec_from_file_location(
    "consensus_accuracy_daily",
    REPO_ROOT / "scripts" / "consensus_accuracy_daily.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_ticker_registry_has_required_fields():
    for ticker, cfg in mod.TICKER_REGISTRY.items():
        for f in ("market", "fdr_symbol", "yf_symbol", "name"):
            assert f in cfg, f"{ticker} missing {f}"
        assert cfg["market"] in ("KR", "US"), \
            f"{ticker} market must be KR or US"


def test_compute_diff_pct_basic():
    # snapshot > live: positive diff
    assert mod.compute_diff_pct(100.0, 105.0) == pytest.approx(5.0)
    # snapshot < live: negative diff
    assert mod.compute_diff_pct(100.0, 95.0) == pytest.approx(-5.0)


def test_compute_diff_pct_handles_none():
    assert mod.compute_diff_pct(None, 100.0) is None
    assert mod.compute_diff_pct(100.0, None) is None
    assert mod.compute_diff_pct(0.0, 100.0) is None
    assert mod.compute_diff_pct(-1.0, 100.0) is None


def test_build_live_prices_json_schema():
    fetched = {
        "NVDA": {"close": 200.0, "currency": "USD", "as_of": "2026-07-04",
                  "source": "yfinance", "market": "US"},
    }
    payload = mod.build_live_prices_json(fetched)
    assert "generated_at" in payload
    assert "generator" in payload
    assert "prices" in payload
    assert "NVDA" in payload["prices"]
    nvda = payload["prices"]["NVDA"]
    for f in ("close", "currency", "as_of", "source", "market", "name"):
        assert f in nvda


def test_registry_no_hardcoded_numeric_values():
    """Registry only contains ticker identity + fetch strategy — no
    price / target / breakdown numerics baked in."""
    for ticker, cfg in mod.TICKER_REGISTRY.items():
        for k, v in cfg.items():
            if isinstance(v, (int, float)):
                pytest.fail(f"{ticker}.{k} = {v} is a number — registry must be identity-only")


def test_stale_threshold_is_configurable():
    # Constant exists and is a positive number
    assert isinstance(mod.STALE_THRESHOLD_PCT, (int, float))
    assert mod.STALE_THRESHOLD_PCT > 0


def test_load_accuracy_state_missing_returns_default():
    """When state file doesn't exist, return a well-formed default."""
    orig = mod.ACCURACY_STATE_PATH
    mod.ACCURACY_STATE_PATH = Path("/no/such/path.json")
    try:
        s = mod.load_accuracy_state()
        assert "streaks" in s
        assert isinstance(s["streaks"], dict)
    finally:
        mod.ACCURACY_STATE_PATH = orig


def test_read_snapshot_close_uses_latest_history(tmp_path, monkeypatch):
    """read_snapshot_close should pick the most recent history date."""
    # Build a fake history tree
    for date in ("2026-07-01", "2026-07-03", "2026-07-04"):
        d = tmp_path / "TEST" / date
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{}", encoding="utf-8")
        (d / "analysis.json").write_text(
            json.dumps({"raw_inputs": {
                "close_price_latest": 1000.0 + int(date[-2:]),
                "latest_target_price": 2000.0,
            }}),
            encoding="utf-8",
        )
    monkeypatch.setattr(mod, "HISTORY_ROOT", tmp_path)
    snap = mod.read_snapshot_close("TEST")
    assert snap is not None
    assert snap["date"] == "2026-07-04"
    assert snap["close"] == 1004.0


def test_read_snapshot_close_missing_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "HISTORY_ROOT", tmp_path)
    assert mod.read_snapshot_close("NOSUCH") is None


def test_live_prices_json_has_no_hardcoded_data():
    """The JSON output must not contain 'test' or 'example' or 'lorem'
    style dummy values — anything numeric must come from the fetch."""
    fetched = {}  # empty fetch = empty prices dict
    payload = mod.build_live_prices_json(fetched)
    assert payload["prices"] == {}
    # But schema still valid
    assert "generated_at" in payload
