# -*- coding: utf-8 -*-
"""Consensus tracker daily accuracy verifier + live-price refresher.

Two responsibilities:

1. **Live close-price refresh** — Fetches TODAY's close for each tracked
   ticker from independent public sources (FDR for KRX, yfinance for US)
   and writes `output/consensus_snapshot/live_prices.json`. The dashboard
   overlays this on top of the (potentially stale) snapshot close so the
   user sees TRUE current price + a recalculated 상승여력.

2. **Accuracy audit + self-improvement** — For each ticker, compares
   snapshot close vs live close. If |diff| > 5% for 3 days consecutive,
   auto-registers a `pending_requests.json` entry AND saves a memory lesson.
   The next Claude Code session recalls this lesson and knows to prioritize
   fixing the accuracy gap.

Design constraint (user requirement 2026-07-04):
  - **NO hardcoding of ticker values.** All numeric data must come from
    the live fetch or persisted snapshot files.
  - **Verification first**: this script runs BEFORE any UI/UX improvement
    to establish ground truth.
  - **Self-improving**: repeated runs accumulate history that a future
    Claude session can recall via `memory_smart_search`.

Usage:
    python scripts/consensus_accuracy_daily.py               # dry-run summary
    python scripts/consensus_accuracy_daily.py --write       # persist live_prices.json + pending_requests
    python scripts/consensus_accuracy_daily.py --write --tickers 000660,NVDA
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_PRICES_PATH = REPO_ROOT / "output" / "consensus_snapshot" / "live_prices.json"
HISTORY_ROOT = REPO_ROOT / "output" / "consensus_snapshot" / "history"
PENDING_PATH = REPO_ROOT / "pending_requests.json"
ACCURACY_STATE_PATH = (
    REPO_ROOT / "output" / "consensus_snapshot" / "_accuracy_state.json"
)


# Ticker registry — non-hardcoded values, just ticker identity + fetch strategy.
# Keys are canonical ticker; values describe which source to use.
TICKER_REGISTRY = {
    "000660": {"market": "KR", "fdr_symbol": "000660", "yf_symbol": "000660.KS", "name": "SK hynix"},
    "NVDA":   {"market": "US", "fdr_symbol": None,     "yf_symbol": "NVDA",      "name": "NVIDIA"},
    "GOOGL":  {"market": "US", "fdr_symbol": None,     "yf_symbol": "GOOGL",     "name": "Alphabet"},
    "VRT":    {"market": "US", "fdr_symbol": None,     "yf_symbol": "VRT",       "name": "Vertiv"},
}

# Threshold: |snapshot_close - live_close| / live_close * 100
STALE_THRESHOLD_PCT = 5.0
CONSECUTIVE_DAYS_FOR_LESSON = 3


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _try_import(mod_name: str):
    try:
        return __import__(mod_name)
    except ImportError:
        return None


def fetch_live_close(ticker: str, cfg: dict) -> dict:
    """Fetch today's close from best available source. No hardcoded fallback."""
    out: dict[str, Any] = {
        "ticker": ticker,
        "market": cfg["market"],
        "close": None,
        "currency": None,
        "as_of": None,
        "source": None,
        "error": None,
    }

    # KR tickers: FDR is authoritative (KRX official)
    if cfg["market"] == "KR" and cfg.get("fdr_symbol"):
        fdr = _try_import("FinanceDataReader")
        if fdr:
            try:
                df = fdr.DataReader(
                    cfg["fdr_symbol"],
                    (_dt.date.today() - _dt.timedelta(days=10)).isoformat(),
                    _dt.date.today().isoformat(),
                )
                if df is not None and not df.empty:
                    out["close"] = float(df["Close"].iloc[-1])
                    out["as_of"] = str(df.index[-1].date())
                    out["currency"] = "KRW"
                    out["source"] = "FinanceDataReader"
                    return out
            except Exception as e:
                out["error"] = f"fdr: {e!r}"[:200]

    # Fallback: yfinance (US or KR when FDR failed)
    yf = _try_import("yfinance")
    if yf and cfg.get("yf_symbol"):
        try:
            t = yf.Ticker(cfg["yf_symbol"])
            info = t.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price is not None:
                out["close"] = float(price)
                out["currency"] = info.get("currency")
                out["as_of"] = _today_iso()  # yfinance info doesn't include exact date
                out["source"] = "yfinance"
                return out
        except Exception as e:
            if not out["error"]:
                out["error"] = f"yfinance: {e!r}"[:200]

    return out


def read_snapshot_close(ticker: str) -> Optional[dict]:
    """Read the LATEST available history snapshot for this ticker."""
    ticker_dir = HISTORY_ROOT / ticker
    if not ticker_dir.exists():
        return None
    dates = sorted([
        d.name for d in ticker_dir.iterdir()
        if d.is_dir() and len(d.name) == 10
    ])
    if not dates:
        return None
    latest = dates[-1]
    analysis_p = ticker_dir / latest / "analysis.json"
    if not analysis_p.exists():
        return None
    try:
        with analysis_p.open(encoding="utf-8") as fh:
            a = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    raw = a.get("raw_inputs") or {}
    return {
        "date": latest,
        "close": raw.get("close_price_latest"),
        "target_mean": raw.get("latest_target_price"),
    }


def compute_diff_pct(live: float, snap: float) -> Optional[float]:
    if live is None or snap is None or live <= 0:
        return None
    return (snap - live) / live * 100


def load_accuracy_state() -> dict:
    if not ACCURACY_STATE_PATH.exists():
        return {"streaks": {}, "generated_at": None}
    try:
        with ACCURACY_STATE_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"streaks": {}, "generated_at": None}


def save_accuracy_state(state: dict) -> None:
    ACCURACY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACCURACY_STATE_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def append_pending_request(entry: dict) -> None:
    if not PENDING_PATH.exists():
        return  # skip silently if pending file not there
    try:
        with PENDING_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    pending_list = data.get("pending") or []
    # dedupe by (id, day)
    key = (entry.get("id"), entry.get("day"))
    if any((p.get("id"), p.get("day")) == key for p in pending_list):
        return
    pending_list.append(entry)
    data["pending"] = pending_list
    data["updated"] = _now_iso()
    with PENDING_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def build_live_prices_json(fetched: dict[str, dict]) -> dict:
    """Assemble the dashboard-consumable live_prices.json payload."""
    return {
        "generated_at": _now_iso(),
        "generator": "scripts/consensus_accuracy_daily.py",
        "prices": {
            ticker: {
                "close": r.get("close"),
                "currency": r.get("currency"),
                "as_of": r.get("as_of"),
                "source": r.get("source"),
                "market": r.get("market"),
                "name": TICKER_REGISTRY[ticker]["name"],
            }
            for ticker, r in fetched.items()
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="Persist live_prices.json + pending_requests updates")
    ap.add_argument("--tickers", default=None,
                    help="comma-separated subset; default all")
    ap.add_argument("--threshold-pct", type=float,
                    default=STALE_THRESHOLD_PCT,
                    help=f"stale threshold %% (default {STALE_THRESHOLD_PCT})")
    args = ap.parse_args(argv)

    tickers = (
        [t.strip() for t in args.tickers.split(",")] if args.tickers
        else list(TICKER_REGISTRY.keys())
    )

    fetched: dict[str, dict] = {}
    diffs: list[dict] = []

    for ticker in tickers:
        cfg = TICKER_REGISTRY.get(ticker)
        if not cfg:
            sys.stderr.write(f"unknown ticker: {ticker}\n")
            continue
        r = fetch_live_close(ticker, cfg)
        fetched[ticker] = r
        snap = read_snapshot_close(ticker) or {}
        diff_pct = compute_diff_pct(r.get("close"), snap.get("close"))
        diffs.append({
            "ticker": ticker,
            "market": cfg["market"],
            "live_close": r.get("close"),
            "live_source": r.get("source"),
            "snapshot_close": snap.get("close"),
            "snapshot_date": snap.get("date"),
            "diff_pct": diff_pct,
            "stale": diff_pct is not None and abs(diff_pct) > args.threshold_pct,
        })

    # Print summary
    print(f"=== Consensus Accuracy Daily ({_now_iso()}) ===")
    print(f"{'ticker':10s} {'market':7s} {'live':>14s} {'source':>18s} "
          f"{'snapshot':>14s} {'snap_date':>12s} {'diff%':>9s} stale?")
    for d in diffs:
        live_s = f"{d['live_close']:,.2f}" if d['live_close'] is not None else "N/A"
        snap_s = f"{d['snapshot_close']:,.2f}" if d['snapshot_close'] is not None else "N/A"
        diff_s = f"{d['diff_pct']:+.2f}%" if d['diff_pct'] is not None else "N/A"
        stale_mark = "STALE" if d['stale'] else ""
        print(
            f"{d['ticker']:10s} {d['market']:7s} {live_s:>14s} "
            f"{(d['live_source'] or 'N/A'):>18s} "
            f"{snap_s:>14s} {(d['snapshot_date'] or 'N/A'):>12s} "
            f"{diff_s:>9s} {stale_mark}"
        )

    # Streak tracking for self-improvement loop
    state = load_accuracy_state()
    streaks = state.setdefault("streaks", {})
    today = _today_iso()
    for d in diffs:
        prev = streaks.get(d["ticker"], {"count": 0, "last_stale_day": None})
        if d["stale"]:
            if prev.get("last_stale_day") != today:
                prev["count"] = prev.get("count", 0) + 1
            prev["last_stale_day"] = today
            prev["last_diff_pct"] = d["diff_pct"]
        else:
            prev["count"] = 0
            prev["last_stale_day"] = None
        streaks[d["ticker"]] = prev
    state["generated_at"] = _now_iso()

    # Emit pending_requests entries + potential lesson trigger
    action_needed = False
    lesson_lines: list[str] = []
    for d in diffs:
        st = streaks.get(d["ticker"], {})
        streak = st.get("count", 0)
        if d["stale"]:
            action_needed = True
            print(f"  → {d['ticker']}: STALE {d['diff_pct']:+.2f}% "
                  f"(streak={streak}d, threshold={args.threshold_pct}%)")
            if streak >= CONSECUTIVE_DAYS_FOR_LESSON:
                lesson_lines.append(
                    f"{d['ticker']} snapshot close persistently off by "
                    f"{d['diff_pct']:+.2f}% for {streak} days — "
                    f"backend snapshot may need re-generation."
                )

    if args.write:
        # 1. Write live_prices.json
        payload = build_live_prices_json(fetched)
        LIVE_PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LIVE_PRICES_PATH.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {LIVE_PRICES_PATH}")

        # 2. Persist accuracy state
        save_accuracy_state(state)
        print(f"wrote {ACCURACY_STATE_PATH}")

        # 3. Pending request entries for stale tickers
        if action_needed:
            for d in diffs:
                if not d["stale"]:
                    continue
                append_pending_request({
                    "id": f"consensus-accuracy-{d['ticker']}",
                    "day": _today_iso(),
                    "kind": "consensus_accuracy",
                    "ticker": d["ticker"],
                    "diff_pct": d["diff_pct"],
                    "live_close": d["live_close"],
                    "snapshot_close": d["snapshot_close"],
                    "snapshot_date": d["snapshot_date"],
                    "note": (
                        f"{d['ticker']} snapshot close differs from live by "
                        f"{d['diff_pct']:+.2f}%. Consider regenerating snapshot "
                        f"or displaying live overlay in dashboard."
                    ),
                })
            print(f"appended {sum(1 for d in diffs if d['stale'])} pending requests")

        # 4. Save lesson if any ticker has 3+ day streak
        if lesson_lines:
            print("LESSON candidate lines:")
            for l in lesson_lines:
                print(f"  - {l}")
            # Note: actual memory_lesson_save requires the AgentMemory MCP;
            # for now we log the lesson candidates. A follow-up job (or the
            # next Claude session) will persist via memory_lesson_save.

    return 0 if not action_needed else 3


if __name__ == "__main__":
    raise SystemExit(main())
