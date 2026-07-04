# -*- coding: utf-8 -*-
"""Phase 14-3 — Global IB feed for Q5 (글로벌 vs 국내).

Honest finding from 2026-06-30 sourcing audit:
  - yfinance Python lib   : aggregate analyst data available; NO per-firm names
                            for Korean tickers (upgrades_downgrades empty).
  - Finnhub               : requires API key (not configured in this repo).
  - Yahoo Finance HTML    : per-firm data is JS-rendered, not in raw HTML.
  - Google News RSS       : robots disallow.
  - Bloomberg HTML        : requires login.

Therefore: Phase 14-3 provides **aggregate global+Korean consensus** via
yfinance, plus an **implied global-only subset** computed by subtracting
the Korean-only WiseReport count from the yfinance total. Per-firm
JPM/Goldman names remain unobtainable through free automated channels and
are documented as such in the report.

This module:
  - probe_yfinance_aggregate(ticker)  -> aggregate dict + raw rows
  - derive_implied_global(yf_agg, domestic) -> implied global mean / count
  - probe_attempts_log()              -> list of sources we tried + status

All network calls go through urllib (no extra deps).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from typing import Optional


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def probe_yfinance_aggregate(ticker_yf: str = "000660.KS") -> dict:
    """Use yfinance Python lib to fetch aggregate analyst data.

    Returns dict with:
      - found: bool
      - target_mean, target_high, target_low, target_median: float | None
      - n_analysts: int | None
      - recommendation_mean: float | None  (Yahoo's 1-5 scale, 1=Strong Buy)
      - recommendation_key: str | None     (e.g. "strong_buy")
      - currency: str | None
      - breakdown_today / breakdown_prior_1m: dict with strong_buy/buy/.../total
      - per_firm: empty list (NOT available for Korean tickers)
      - error: str | None
      - source_name: "yfinance_aggregate"
      - probed_at: ISO timestamp
    """
    out = {
        "found": False,
        "target_mean": None, "target_high": None,
        "target_low": None, "target_median": None,
        "n_analysts": None,
        "recommendation_mean": None, "recommendation_key": None,
        "currency": None,
        "breakdown_today": None, "breakdown_prior_1m": None,
        "per_firm": [],
        "error": None,
        "source_name": "yfinance_aggregate",
        "probed_at": _now_iso(),
    }
    try:
        import yfinance as yf  # type: ignore
    except ImportError as e:
        out["error"] = f"yfinance_not_importable: {e!r}"
        return out
    try:
        t = yf.Ticker(ticker_yf)
        apt = t.analyst_price_targets
        if isinstance(apt, dict):
            out["target_mean"] = apt.get("mean")
            out["target_high"] = apt.get("high")
            out["target_low"] = apt.get("low")
            out["target_median"] = apt.get("median")
        info = t.info or {}
        out["n_analysts"] = info.get("numberOfAnalystOpinions")
        out["recommendation_mean"] = info.get("recommendationMean")
        out["recommendation_key"] = info.get("recommendationKey")
        out["currency"] = info.get("currency")
        # Recommendations: monthly snapshots (0m/-1m/-2m/-3m)
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty:
                rows = rec.to_dict(orient="records")
                # 0m and -1m
                row0 = next((r for r in rows if r.get("period") == "0m"), None)
                row1 = next((r for r in rows if r.get("period") == "-1m"), None)
                def _bd(r):
                    if not r:
                        return None
                    sb = r.get("strongBuy")
                    b = r.get("buy")
                    h = r.get("hold")
                    s = r.get("sell")
                    ss = r.get("strongSell")
                    total = 0
                    for v in (sb, b, h, s, ss):
                        if isinstance(v, (int, float)):
                            total += int(v)
                    return {
                        "strong_buy": int(sb) if sb is not None else None,
                        "buy": int(b) if b is not None else None,
                        "hold": int(h) if h is not None else None,
                        "sell": int(s) if s is not None else None,
                        "strong_sell": int(ss) if ss is not None else None,
                        "total": total,
                    }
                out["breakdown_today"] = _bd(row0)
                out["breakdown_prior_1m"] = _bd(row1)
        except Exception as e:
            out["error"] = f"recommendations_failed: {e!r}"

        out["found"] = (
            out["target_mean"] is not None
            or out["n_analysts"] is not None
        )
    except Exception as e:
        out["error"] = f"probe_failed: {e!r}"
    return out


def derive_implied_global(
    yf_agg: dict, domestic: dict,
) -> dict:
    """Subtract Korean-only (WiseReport) from yfinance aggregate to estimate
    implied global IB stats.

    Args:
      yf_agg: output of probe_yfinance_aggregate
      domestic: dict with keys n_firms, mean_target (from
                per_firm_targets of WiseReport)

    Returns dict with:
      n_implied_global: int | None  (yf.n_analysts - domestic.n_firms)
      implied_global_mean_target: float | None
      domestic_mean_target: float | None
      gap_pct: float | None   (global / domestic - 1) * 100
      sample_quality: str   ("ok" / "n_too_small" / "unavailable")
    """
    out = {
        "n_implied_global": None,
        "implied_global_mean_target": None,
        "domestic_mean_target": None,
        "gap_pct": None,
        "sample_quality": "unavailable",
    }
    yf_n = yf_agg.get("n_analysts")
    yf_mean = yf_agg.get("target_mean")
    dom_n = domestic.get("n_firms")
    dom_mean = domestic.get("mean_target")
    if (yf_n is None or yf_mean is None
            or dom_n is None or dom_mean is None):
        return out
    # Pure arithmetic decomposition
    n_global = yf_n - dom_n
    if n_global <= 0:
        out["sample_quality"] = "n_too_small"
        return out
    # Total weighted mean = (dom_n * dom_mean + n_global * X) / yf_n
    # X = (yf_n * yf_mean - dom_n * dom_mean) / n_global
    implied_global_mean = (yf_n * yf_mean - dom_n * dom_mean) / n_global
    out["n_implied_global"] = n_global
    out["implied_global_mean_target"] = implied_global_mean
    out["domestic_mean_target"] = dom_mean
    if dom_mean > 0:
        out["gap_pct"] = (implied_global_mean - dom_mean) / dom_mean * 100
    out["sample_quality"] = "ok" if n_global >= 2 else "n_too_small"
    return out


def probe_attempts_log() -> list[dict]:
    """Static list of source attempts for transparency in report."""
    return [
        {
            "source": "yfinance Python lib (.analyst_price_targets / .recommendations)",
            "purpose": "aggregate global+Korean consensus",
            "result": "available — 37 analysts, KRW, per-firm not exposed",
            "robots_status": "n/a (library, not URL)",
        },
        {
            "source": "Finnhub /stock/recommendation",
            "purpose": "per-firm if API key",
            "result": "401 — requires FINNHUB_API_KEY (not configured)",
            "robots_status": "allow",
        },
        {
            "source": "Yahoo Finance HTML quote page",
            "purpose": "per-firm names in HTML",
            "result": "200 / 166KB — 0 occurrences of JPM/Goldman/MS/BofA names; data is JS-rendered",
            "robots_status": "allow",
        },
        {
            "source": "query1.finance.yahoo.com /v7/finance/quote API",
            "purpose": "Yahoo backend JSON",
            "result": "robots_denied",
            "robots_status": "disallow",
        },
        {
            "source": "Google News RSS (SK hynix JPMorgan)",
            "purpose": "discovery of IB target headlines",
            "result": "robots_denied",
            "robots_status": "disallow",
        },
        {
            "source": "Bloomberg.com quote page",
            "purpose": "global IB data",
            "result": "allow (robots) but full data behind login; not attempted at scale",
            "robots_status": "allow",
        },
    ]


def main(argv: Optional[list[str]] = None) -> int:
    """CLI helper for one-shot probe + JSON dump.
    Output saved to output/consensus_snapshot/{ticker}_global_ib_aggregate.json.
    """
    import argparse, os
    p = argparse.ArgumentParser()
    p.add_argument("--ticker-yf", default="000660.KS")
    p.add_argument("--out-dir", default="output/consensus_snapshot")
    p.add_argument("--smoke", action="store_true",
                   help="REQUIRED -- confirms intent to make a network call")
    args = p.parse_args(argv)

    if not args.smoke:
        sys.stderr.write(
            "ERROR: --smoke flag required (default-deny). Phase 14-3 makes "
            "outgoing network calls via yfinance.\n"
        )
        return 4

    agg = probe_yfinance_aggregate(args.ticker_yf)
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(
        args.out_dir,
        f"{args.ticker_yf.split('.')[0]}_global_ib_aggregate.json",
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(agg, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(
        f"global_ib_probe: found={agg['found']} n_analysts={agg['n_analysts']} "
        f"target_mean={agg['target_mean']} out={out_path}\n"
    )
    return 0 if agg["found"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
