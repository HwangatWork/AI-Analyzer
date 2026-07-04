# -*- coding: utf-8 -*-
"""Regression tests for tools/consensus/live_price_fetcher.py.

Mock-only (no network). Verifies:
- Returns None on library import failure (graceful)
- Returns None on empty API result
- Auto-dispatches by ticker format
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus import live_price_fetcher as lpf


def test_fetch_live_close_dispatch_kr_by_format(monkeypatch):
    calls = []
    def fake_kr(sym):
        calls.append(("kr", sym))
        return {"close": 2_425_000.0, "as_of": "2026-07-04",
                "source": "FinanceDataReader", "currency": "KRW"}
    def fake_us(sym):
        calls.append(("us", sym))
        return None
    monkeypatch.setattr(lpf, "fetch_live_close_kr", fake_kr)
    monkeypatch.setattr(lpf, "fetch_live_close_us", fake_us)

    r = lpf.fetch_live_close("000660")
    assert r["source"] == "FinanceDataReader"
    assert r["close"] == 2_425_000.0
    assert calls == [("kr", "000660")]


def test_fetch_live_close_dispatch_us_by_format(monkeypatch):
    calls = []
    monkeypatch.setattr(lpf, "fetch_live_close_kr",
                        lambda sym: calls.append(("kr", sym)) or None)
    monkeypatch.setattr(lpf, "fetch_live_close_us",
                        lambda sym: calls.append(("us", sym))
                        or {"close": 194.83, "as_of": "2026-07-04",
                            "source": "yfinance", "currency": "USD"})

    r = lpf.fetch_live_close("NVDA")
    assert r["source"] == "yfinance"
    assert calls == [("us", "NVDA")]


def test_fetch_live_close_kr_handles_missing_library(monkeypatch):
    # Simulate FinanceDataReader missing.
    import builtins
    orig_import = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "FinanceDataReader":
            raise ImportError("simulated")
        return orig_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert lpf.fetch_live_close_kr("000660") is None


def test_fetch_live_close_kr_handles_empty_df(monkeypatch):
    import types

    class FakeDF:
        empty = True

    class FakeFdr:
        @staticmethod
        def DataReader(*a, **kw):
            return FakeDF()

    monkeypatch.setitem(sys.modules, "FinanceDataReader", FakeFdr)
    assert lpf.fetch_live_close_kr("000660") is None


def test_fetch_live_close_us_handles_missing_price(monkeypatch):
    class FakeTicker:
        info = {"currentPrice": None, "regularMarketPrice": None}

    class FakeYf:
        @staticmethod
        def Ticker(sym):
            return FakeTicker()

    monkeypatch.setitem(sys.modules, "yfinance", FakeYf)
    assert lpf.fetch_live_close_us("NVDA") is None
