# -*- coding: utf-8 -*-
"""Live close-price fetcher for consensus snapshots.

Single source of truth for close prices used by the snapshot pipeline.
Snapshot's ``close_price_latest`` MUST come from an external API (FDR
for KR, yfinance for US), NOT from WiseReport chartData which lags by
~1 month.

Rationale (OL-8): the parser handles HTML scraping only; API-fetched
values (like current close) belong to a separate fetcher. This
separation prevents stale monthly chart data from being mis-used as
the authoritative current price.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional


def fetch_live_close_kr(fdr_symbol: str) -> Optional[dict]:
    """Fetch latest close from FinanceDataReader (KRX). Returns dict
    or None on any failure (no exceptions leak)."""
    try:
        import FinanceDataReader as fdr  # noqa: F401
    except Exception:
        return None
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(
            fdr_symbol,
            (_dt.date.today() - _dt.timedelta(days=10)).isoformat(),
            _dt.date.today().isoformat(),
        )
        if df is None or df.empty:
            return None
        return {
            "close": float(df["Close"].iloc[-1]),
            "as_of": str(df.index[-1].date()),
            "source": "FinanceDataReader",
            "currency": "KRW",
        }
    except Exception:
        return None


def fetch_live_close_us(yf_symbol: str) -> Optional[dict]:
    """Fetch latest close from yfinance."""
    try:
        import yfinance as yf  # noqa: F401
    except Exception:
        return None
    try:
        import yfinance as yf
        t = yf.Ticker(yf_symbol)
        info = t.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            return None
        return {
            "close": float(price),
            "as_of": _dt.date.today().isoformat(),
            "source": "yfinance",
            "currency": info.get("currency") or "USD",
        }
    except Exception:
        return None


def fetch_live_close(ticker: str) -> Optional[dict]:
    """Auto-dispatch by ticker format. 6-digit numeric → KR (FDR),
    otherwise → US (yfinance)."""
    if ticker.isdigit() and len(ticker) == 6:
        return fetch_live_close_kr(ticker)
    return fetch_live_close_us(ticker)
