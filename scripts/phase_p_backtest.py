# -*- coding: utf-8 -*-
"""Phase P (Purpose Return) — pre-registered backtest runner.

Runs P-1 / P-2 / P-3 / P-4 against the frozen pre-registration contract
(``output/phase_p_preregistration.json``). Refuses to run if the
pre-registration is uncommitted or absent.

Level 8+ evidence: each subcommand prints a numeric summary line and
writes ``output/phase_p_p{N}_results.json``. Exit code 0 on success.

Design notes (from peer review 2026-07-05):
- Sample size N=12 daily pipeline snapshots → all tests descriptive-only.
- P-4 is fully executable. P-1/P-2/P-3 are 5d-forward descriptive only;
  10d/20d horizons infeasible until sufficient forward data accumulates.
- HOLD/neutral = carry-over prior position (evaluator rule).
- Initial state = flat (0% invested), so first SELL is a no-cost no-op.
- Transaction cost 10 bps applied on state transitions only.
- Price data: yfinance (^GSPC) for SP500, FDR (KS11) for KOSPI.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
PREREG_PATH = ROOT / "output" / "phase_p_preregistration.json"
CACHE_DIR = ROOT / "output" / "backtest_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── pre-registration gate ────────────────────────────────────────────────

def _run(cmd: Sequence[str], check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{r.stderr}")
    return r.stdout


def _freeze_sha() -> str:
    out = _run(["git", "log", "--format=%H", "-1", "--", str(PREREG_PATH.relative_to(ROOT))])
    sha = out.strip()
    if not sha:
        raise RuntimeError(f"pre-registration file has no git history: {PREREG_PATH}")
    return sha


def _is_ancestor(sha: str, ref: str = "HEAD") -> bool:
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, ref],
        cwd=ROOT, capture_output=True, text=True,
    )
    return r.returncode == 0


def _disk_matches_head(rel_path: str) -> bool:
    head_content = _run(["git", "show", f"HEAD:{rel_path}"])
    disk_content = (ROOT / rel_path).read_text(encoding="utf-8")
    return head_content == disk_content


def assert_preregistration() -> Dict[str, Any]:
    if not PREREG_PATH.exists():
        raise SystemExit(f"pre-registration missing: {PREREG_PATH}")
    freeze = _freeze_sha()
    if not _is_ancestor(freeze):
        raise SystemExit(f"pre-registration freeze SHA {freeze} is not ancestor of HEAD")
    if not _disk_matches_head("output/phase_p_preregistration.json"):
        raise SystemExit(
            "pre-registration file has uncommitted edits — freeze violated. "
            "Commit the edits (new freeze) or revert before running."
        )
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    print(f"[gate] pre-registration OK; freeze_sha={freeze[:12]}")
    return prereg


# ── snapshot loading ─────────────────────────────────────────────────────

def load_snapshot(sha: str, path: str) -> Dict[str, Any]:
    raw = _run(["git", "show", f"{sha}:{path}"])
    return json.loads(raw)


# ── price fetching (external anchor per OL-7) ────────────────────────────

_PRICE_CACHE: Dict[str, Any] = {}


def fetch_prices_us(ticker: str, start: date, end: date) -> "pd.Series":
    import pandas as pd  # local import to keep import cost off gate path
    cache_key = f"us:{ticker}:{start}:{end}"
    if cache_key in _PRICE_CACHE:
        return _PRICE_CACHE[cache_key]
    cache_file = CACHE_DIR / f"us_{ticker.replace('^','')}_{start}_{end}.parquet"
    if cache_file.exists():
        s = pd.read_parquet(cache_file)["Close"]
        _PRICE_CACHE[cache_key] = s
        return s
    import yfinance as yf
    df = yf.download(ticker, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                     progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"no US price data for {ticker} {start}..{end}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(str(c) for c in col if c) for col in df.columns.values]
        close_col = next((c for c in df.columns if c.startswith("Close")), None)
        if close_col is None:
            raise RuntimeError(f"no Close column in yfinance result for {ticker}")
        s = df[close_col].rename("Close")
    else:
        s = df["Close"]
    s.index = pd.to_datetime(s.index).date
    s.name = "Close"
    pd.DataFrame({"Close": s}).to_parquet(cache_file)
    _PRICE_CACHE[cache_key] = s
    return s


def fetch_prices_kr(ticker: str, start: date, end: date) -> "pd.Series":
    import pandas as pd
    cache_key = f"kr:{ticker}:{start}:{end}"
    if cache_key in _PRICE_CACHE:
        return _PRICE_CACHE[cache_key]
    cache_file = CACHE_DIR / f"kr_{ticker}_{start}_{end}.parquet"
    if cache_file.exists():
        s = pd.read_parquet(cache_file)["Close"]
        _PRICE_CACHE[cache_key] = s
        return s
    import FinanceDataReader as fdr
    df = fdr.DataReader(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        raise RuntimeError(f"no KR price data for {ticker} {start}..{end}")
    s = df["Close"]
    s.index = pd.to_datetime(s.index).date
    s.name = "Close"
    pd.DataFrame({"Close": s}).to_parquet(cache_file)
    _PRICE_CACHE[cache_key] = s
    return s


# ── P-4: BUY/SELL/HOLD signal simulation ─────────────────────────────────

@dataclass
class SignalPoint:
    snapshot_date: date
    action: str            # BUY, SELL, HOLD, SELL/AVOID, WAIT, ...
    confidence_pct: float


def _normalize_action(raw: str) -> str:
    """Map raw action to {BUY, SELL, HOLD}."""
    if not raw:
        return "HOLD"
    r = raw.upper()
    if r.startswith("BUY"):
        return "BUY"
    if r.startswith("SELL"):
        return "SELL"
    return "HOLD"  # HOLD, WAIT, neutral, unknown


def _load_signals(prereg: Dict[str, Any], asset: str) -> List[SignalPoint]:
    """asset ∈ {'sp500', 'kospi'}. Returns chronological."""
    points: List[SignalPoint] = []
    for entry in prereg["data_snapshots"]["commit_shas"]:
        sha = entry["sha"]
        d = date.fromisoformat(entry["date"])
        snap = load_snapshot(sha, "output/decision.json")
        side = snap.get(asset, {})
        action_raw = side.get("action", "HOLD")
        conf = float(side.get("confidence_pct", 0) or 0)
        points.append(SignalPoint(snapshot_date=d, action=action_raw, confidence_pct=conf))
    points.sort(key=lambda p: p.snapshot_date)
    return points


def _apply_gate(action_norm: str, confidence: float, variant: str) -> str:
    """Return effective action per gate variant."""
    if variant == "unconditional":
        return action_norm
    if variant == "confidence_gte_60":
        if action_norm in ("BUY", "SELL") and confidence < 60:
            return "HOLD"
        return action_norm
    if variant == "confidence_gte_70":
        if action_norm in ("BUY", "SELL") and confidence < 70:
            return "HOLD"
        return action_norm
    raise ValueError(f"unknown variant: {variant}")


def _simulate(
    signals: List[SignalPoint],
    prices: "pd.Series",
    variant: str,
    tx_bps: int,
) -> Dict[str, Any]:
    """Signal-driven position simulation.

    Positions are updated on each snapshot_date at close. Between snapshots
    the position is held. Buy-and-hold benchmark computed over the same
    price series.
    """
    import numpy as np
    import pandas as pd

    if len(signals) == 0:
        raise RuntimeError("no signal points")
    start_d = signals[0].snapshot_date
    end_d = date.today()
    # slice prices to [start_d, end_d]
    prices = prices[(prices.index >= start_d) & (prices.index <= end_d)].sort_index()
    if len(prices) < 2:
        raise RuntimeError(f"insufficient price rows for {start_d}..{end_d}: {len(prices)}")

    # daily returns
    rets = prices.pct_change().fillna(0.0)

    # exposure schedule (target per trading day)
    tx_cost = tx_bps / 10000.0
    exposure = pd.Series(0.0, index=prices.index)
    cur_pos = 0.0  # initial: flat
    sig_iter = iter(signals)
    next_sig = next(sig_iter, None)
    trades: List[Dict[str, Any]] = []
    prior_exposure = 0.0

    # build a signal-by-date lookup
    sig_by_date = {}
    for s in signals:
        sig_by_date[s.snapshot_date] = s

    for d in prices.index:
        if d in sig_by_date:
            sp = sig_by_date[d]
            eff = _apply_gate(_normalize_action(sp.action), sp.confidence_pct, variant)
            if eff == "BUY":
                target = 1.0
            elif eff == "SELL":
                target = 0.0
            else:  # HOLD / carry-over
                target = cur_pos
            if target != cur_pos:
                trades.append({
                    "date": d.isoformat(),
                    "from": cur_pos,
                    "to": target,
                    "action_raw": sp.action,
                    "action_norm": _normalize_action(sp.action),
                    "action_effective": eff,
                    "confidence_pct": sp.confidence_pct,
                })
                cur_pos = target
        exposure.loc[d] = cur_pos

    # strategy pnl
    strat_gross = (exposure.shift(1).fillna(0.0) * rets).astype(float)
    # tx cost on absolute exposure changes (initial state = flat, so day-0
    # entry from 0→exposure[0] is counted as a real trade cost)
    prev_exposure = exposure.shift(1).fillna(0.0)
    changes = (exposure - prev_exposure).abs()
    tx_hit = changes * tx_cost
    strat_net = strat_gross - tx_hit
    strat_curve = (1.0 + strat_net).cumprod()

    # buy & hold
    bh_curve = prices / float(prices.iloc[0])

    # 50/50 constant mix (rebalanced daily)
    mix_ret = 0.5 * rets
    mix_curve = (1.0 + mix_ret).cumprod()

    def _sharpe(ret_series: "pd.Series") -> Optional[float]:
        r = ret_series.dropna()
        if len(r) < 2:
            return None
        std = float(r.std(ddof=1))
        if std == 0:
            return None
        return float(r.mean() / std * (252 ** 0.5))

    def _mdd(curve: "pd.Series") -> float:
        peak = curve.cummax()
        dd = (curve / peak) - 1.0
        return float(dd.min())

    bh_daily = rets.copy()
    mix_daily = mix_ret.copy()

    result = {
        "variant": variant,
        "asset": None,  # filled by caller
        "n_days": int(len(prices)),
        "n_trades": len(trades),
        "final_exposure_pct": float(cur_pos * 100.0),
        "avg_exposure_pct": float(exposure.mean() * 100.0),
        "strategy": {
            "cumulative_return_pct": float((strat_curve.iloc[-1] - 1.0) * 100.0),
            "sharpe": _sharpe(strat_net),
            "max_drawdown_pct": float(_mdd(strat_curve) * 100.0),
        },
        "benchmark_buy_and_hold": {
            "cumulative_return_pct": float((bh_curve.iloc[-1] - 1.0) * 100.0),
            "sharpe": _sharpe(bh_daily),
            "max_drawdown_pct": float(_mdd(bh_curve) * 100.0),
        },
        "benchmark_50_50_mix": {
            "cumulative_return_pct": float((mix_curve.iloc[-1] - 1.0) * 100.0),
            "sharpe": _sharpe(mix_daily),
            "max_drawdown_pct": float(_mdd(mix_curve) * 100.0),
        },
        "beta_matched_note": (
            "beta_matched benchmark = avg_exposure * buy_and_hold_return (linear scale)"
        ),
        "benchmark_beta_matched": {
            "cumulative_return_pct": float(
                exposure.mean() * ((bh_curve.iloc[-1] - 1.0)) * 100.0
            ),
        },
        "trades": trades,
        "price_span": {
            "start": prices.index[0].isoformat(),
            "end": prices.index[-1].isoformat(),
            "n_prices": int(len(prices)),
        },
    }
    return result


def run_p4(prereg: Dict[str, Any]) -> Dict[str, Any]:
    signals_sp = _load_signals(prereg, "sp500")
    signals_ks = _load_signals(prereg, "kospi")

    start_d = min(signals_sp[0].snapshot_date, signals_ks[0].snapshot_date)
    end_d = date.today() + timedelta(days=1)

    sp_prices = fetch_prices_us("^GSPC", start_d - timedelta(days=5), end_d)
    ks_prices = fetch_prices_kr("KS11", start_d - timedelta(days=5), end_d)

    out: Dict[str, Any] = {
        "id": "P-4",
        "kind": "descriptive_with_secondary_inferential",
        "generated_at": datetime.now(tz=None).isoformat(timespec="seconds"),
        "sample_size": len(signals_sp),
        "variants": {},
    }

    for variant in ("unconditional", "confidence_gte_60", "confidence_gte_70"):
        sp_res = _simulate(signals_sp, sp_prices, variant, tx_bps=10)
        sp_res["asset"] = "SP500"
        ks_res = _simulate(signals_ks, ks_prices, variant, tx_bps=10)
        ks_res["asset"] = "KOSPI"
        out["variants"][variant] = {"SP500": sp_res, "KOSPI": ks_res}

    # decision on primary criterion (per pre-reg P-4.success_criteria.primary)
    def _judge_one(v: str, asset: str) -> Dict[str, Any]:
        d = out["variants"][v][asset]
        strat_s = d["strategy"]["sharpe"]
        bh_s = d["benchmark_buy_and_hold"]["sharpe"]
        strat_cum = d["strategy"]["cumulative_return_pct"]
        bh_cum = d["benchmark_buy_and_hold"]["cumulative_return_pct"]
        mix_cum = d["benchmark_50_50_mix"]["cumulative_return_pct"]
        return {
            "asset": asset,
            "variant": v,
            "strat_sharpe": strat_s,
            "bh_sharpe": bh_s,
            "beats_bh_by_sharpe": (
                strat_s is not None and bh_s is not None and strat_s > bh_s
            ),
            "beats_bh_by_cum_return_pp": strat_cum - bh_cum,
            "beats_5050_by_cum_return_pp": strat_cum - mix_cum,
            "strategy_took_zero_trades": d["n_trades"] == 0,
            "avg_exposure_pct": d["avg_exposure_pct"],
        }

    out["primary_judgment_per_variant"] = [
        _judge_one(v, a) for v in out["variants"] for a in ("SP500", "KOSPI")
    ]
    return out


# ── P-1: indicator weight ranking hit rate ───────────────────────────────

def _first_trading_day_after(prices: "pd.Series", d: date, offset: int) -> Optional[date]:
    """Return the trading day at index offset positions after the last trading day <= d."""
    import pandas as pd
    idx = prices.index
    # find last idx <= d
    prior = [i for i in idx if i <= d]
    if not prior:
        return None
    anchor = prior[-1]
    pos = list(idx).index(anchor)
    fwd_pos = pos + offset
    if fwd_pos >= len(idx):
        return None
    return idx[fwd_pos]


def _forward_return(prices: "pd.Series", d: date, horizon: int) -> Optional[float]:
    p0_day = _first_trading_day_after(prices, d, 0)
    p1_day = _first_trading_day_after(prices, d, horizon)
    if p0_day is None or p1_day is None:
        return None
    p0 = float(prices.loc[p0_day]); p1 = float(prices.loc[p1_day])
    if p0 == 0:
        return None
    return (p1 / p0) - 1.0


def _wilson_ci(k: int, n: int, z: float = 1.645) -> Tuple[float, float]:
    """Wilson 90% CI. z=1.645 for 90%."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1.0 + z*z/n
    center = (phat + z*z/(2*n)) / denom
    half = (z * ((phat*(1-phat)/n + z*z/(4*n*n)) ** 0.5)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def run_p1(prereg: Dict[str, Any]) -> Dict[str, Any]:
    """Descriptive-only: for each snapshot, compute top5 vs bottom5 hit rate
    on 5d forward index direction. Aggregate across snapshots.
    """
    import pandas as pd
    horizon = 5
    top_hits: List[int] = []; top_total = 0
    bot_hits: List[int] = []; bot_total = 0
    per_snapshot: List[Dict[str, Any]] = []

    # fetch prices once
    dates = [date.fromisoformat(e["date"]) for e in prereg["data_snapshots"]["commit_shas"]]
    start = min(dates) - timedelta(days=5)
    end = date.today() + timedelta(days=1)
    sp_prices = fetch_prices_us("^GSPC", start, end)

    for entry in prereg["data_snapshots"]["commit_shas"]:
        sha = entry["sha"]; d = date.fromisoformat(entry["date"])
        try:
            snap = load_snapshot(sha, "output/final_results.json")
        except Exception as e:
            per_snapshot.append({"date": d.isoformat(), "sha": sha[:12], "error": str(e)})
            continue

        sigs = snap.get("market_signal", {}).get("indicator_signals", [])
        # sort by weight desc
        sigs_sorted = sorted(sigs, key=lambda x: float(x.get("weight", 0)), reverse=True)
        top = sigs_sorted[:5]; bot = sigs_sorted[-5:] if len(sigs_sorted) >= 10 else []

        fwd_r = _forward_return(sp_prices, d, horizon)
        if fwd_r is None:
            per_snapshot.append({"date": d.isoformat(), "sha": sha[:12],
                                  "reason": "forward_window_unavailable"})
            continue
        actual_up = fwd_r > 0
        t_hits = sum(1 for s in top if bool(s.get("bullish")) == actual_up)
        b_hits = sum(1 for s in bot if bool(s.get("bullish")) == actual_up)
        top_hits.append(t_hits); top_total += len(top)
        bot_hits.append(b_hits); bot_total += len(bot)
        per_snapshot.append({
            "date": d.isoformat(),
            "sha": sha[:12],
            "sp500_5d_forward_ret_pct": fwd_r * 100.0,
            "actual_up": actual_up,
            "top5_hit_count": t_hits,
            "top5_size": len(top),
            "bottom5_hit_count": b_hits,
            "bottom5_size": len(bot),
        })

    total_top_hits = sum(top_hits)
    total_bot_hits = sum(bot_hits)
    top_rate = total_top_hits / top_total if top_total else None
    bot_rate = total_bot_hits / bot_total if bot_total else None
    top_ci = _wilson_ci(total_top_hits, top_total)
    bot_ci = _wilson_ci(total_bot_hits, bot_total)

    return {
        "id": "P-1",
        "kind": "descriptive_only",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "horizon_bdays": horizon,
        "n_evaluable_snapshots": sum(1 for s in per_snapshot if "top5_hit_count" in s),
        "asset_tested": "SP500",
        "top5_hit_rate": top_rate,
        "top5_hits": total_top_hits,
        "top5_total": top_total,
        "top5_wilson90_ci": top_ci,
        "bottom5_hit_rate": bot_rate,
        "bottom5_hits": total_bot_hits,
        "bottom5_total": bot_total,
        "bottom5_wilson90_ci": bot_ci,
        "delta_top_minus_bottom": (
            (top_rate - bot_rate) if (top_rate is not None and bot_rate is not None) else None
        ),
        "per_snapshot": per_snapshot,
        "interpretation_rule": (
            "Descriptive only. Sample size below inferential threshold. "
            "Positive delta suggests weight ranking is directionally informative; "
            "no p-value asserted (prompt required N>=30, actual N is limited by 5d forward availability)."
        ),
    }


# ── P-2: contribution Top5 precision@5 (forward-window redefinition) ─────

def _resolve_prices_for_ticker(ticker: str, start: date, end: date) -> Optional["pd.Series"]:
    try:
        if ticker.endswith(".KS") or ticker.endswith(".KQ"):
            return fetch_prices_kr(ticker.split(".")[0], start, end)
        return fetch_prices_us(ticker, start, end)
    except Exception:
        return None


def _forward_return_ticker(ticker: str, d: date, horizon: int, cache_end: date) -> Optional[float]:
    import pandas as pd
    s = _resolve_prices_for_ticker(ticker, d - timedelta(days=5), cache_end)
    if s is None or len(s) == 0:
        return None
    return _forward_return(s, d, horizon)


def run_p2(prereg: Dict[str, Any]) -> Dict[str, Any]:
    horizon = 5
    per_snapshot: List[Dict[str, Any]] = []
    precisions: List[float] = []
    universe_union: set = set()

    # first pass: gather universe (union of all snapshot Top5 tickers, sp500 side only)
    entries = prereg["data_snapshots"]["commit_shas"]
    for entry in entries:
        try:
            snap = load_snapshot(entry["sha"], "output/final_results.json")
        except Exception:
            continue
        for x in snap.get("sp500_analysis", {}).get("contribution_top5", []):
            t = x.get("ticker")
            if t:
                universe_union.add(t)

    cache_end = date.today() + timedelta(days=1)

    for entry in entries:
        sha = entry["sha"]; d = date.fromisoformat(entry["date"])
        try:
            snap = load_snapshot(sha, "output/final_results.json")
        except Exception as e:
            per_snapshot.append({"date": d.isoformat(), "sha": sha[:12], "error": str(e)})
            continue
        pred_top5 = [x for x in snap.get("sp500_analysis", {}).get("contribution_top5", [])]
        pred_set = {x["ticker"] for x in pred_top5 if "ticker" in x}
        # compute empirical Top5 over T+1..T+5
        contribs: List[Tuple[str, float]] = []
        skipped = 0
        for t in universe_union:
            fwd = _forward_return_ticker(t, d, horizon, cache_end)
            if fwd is None:
                skipped += 1
                continue
            # weight by market cap from this snapshot if present, else equal weight
            mc = None
            for x in pred_top5:
                if x.get("ticker") == t:
                    mc = float(x.get("market_cap_b") or 0.0)
                    break
            weight = mc if (mc and mc > 0) else 1.0
            contribs.append((t, fwd * weight))
        if not contribs:
            per_snapshot.append({"date": d.isoformat(), "sha": sha[:12],
                                  "reason": "no forward returns available",
                                  "universe_size": len(universe_union)})
            continue
        contribs.sort(key=lambda kv: kv[1], reverse=True)
        empirical_top5 = {t for t, _ in contribs[:5]}
        intersect = pred_set & empirical_top5
        prec = len(intersect) / 5.0 if pred_set else None
        if prec is not None:
            precisions.append(prec)
        per_snapshot.append({
            "date": d.isoformat(),
            "sha": sha[:12],
            "predicted_top5": sorted(pred_set),
            "empirical_top5": sorted(empirical_top5),
            "intersection": sorted(intersect),
            "precision_at_5": prec,
            "universe_evaluated": len(contribs),
            "universe_skipped": skipped,
        })

    mean_prec = (sum(precisions) / len(precisions)) if precisions else None
    return {
        "id": "P-2",
        "kind": "descriptive_only_corrected_definition",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "horizon_bdays": horizon,
        "asset_tested": "SP500",
        "n_evaluable_snapshots": len(precisions),
        "universe_union_size": len(universe_union),
        "chance_baseline_precision_at_5": (
            5.0 / len(universe_union) if universe_union else None
        ),
        "mean_precision_at_5": mean_prec,
        "per_snapshot": per_snapshot,
        "correction_note": (
            "Prompt's P-2 same-day comparison was tautological (contribution_top5 is a past-window "
            "summary). Corrected: precision@5 vs empirically top-5 contributors over T+1..T+5 forward "
            "window, computed from external yfinance prices weighted by snapshot market cap. "
            "20d version not computable until 2026-08-03."
        ),
    }


# ── P-3: beneficiary Top5 forward return vs benchmark ────────────────────

def _passes_exclusion(x: Dict[str, Any]) -> Tuple[bool, str]:
    if x.get("warn_reason"):
        return False, "warn_reason present"
    ex = float(x.get("excess_return_pct") or 0)
    if ex > 200.0:
        return False, f"excess_return_pct {ex:.1f} > 200"
    nd = int(x.get("n_days") or 0)
    if nd < 180:
        return False, f"n_days {nd} < 180"
    return True, ""


def run_p3(prereg: Dict[str, Any]) -> Dict[str, Any]:
    horizon = 5
    entries = prereg["data_snapshots"]["commit_shas"]
    cache_end = date.today() + timedelta(days=1)

    dates = [date.fromisoformat(e["date"]) for e in entries]
    start = min(dates) - timedelta(days=5)
    end = date.today() + timedelta(days=1)
    sp_prices = fetch_prices_us("^GSPC", start, end)
    ks_prices = fetch_prices_kr("KS11", start, end)

    def _process(side_key: str, benchmark_prices, benchmark_name: str, asset_id: str) -> Dict[str, Any]:
        excesses: List[float] = []
        per_snap: List[Dict[str, Any]] = []
        for entry in entries:
            sha = entry["sha"]; d = date.fromisoformat(entry["date"])
            try:
                snap = load_snapshot(sha, "output/final_results.json")
            except Exception as e:
                per_snap.append({"date": d.isoformat(), "sha": sha[:12], "error": str(e)}); continue
            raw_top5 = snap.get(side_key, {}).get("beneficiary_top5", [])
            surviving: List[Dict[str, Any]] = []
            excluded: List[Dict[str, Any]] = []
            for x in raw_top5:
                keep, reason = _passes_exclusion(x)
                if keep:
                    surviving.append(x)
                else:
                    excluded.append({"ticker": x.get("ticker"), "reason": reason})
            if not surviving:
                per_snap.append({"date": d.isoformat(), "sha": sha[:12],
                                 "reason": "all_top5_excluded_by_filter",
                                 "excluded": excluded}); continue
            bench_fwd = _forward_return(benchmark_prices, d, horizon)
            if bench_fwd is None:
                per_snap.append({"date": d.isoformat(), "sha": sha[:12],
                                 "reason": "benchmark forward window unavailable",
                                 "surviving_tickers": [s.get("ticker") for s in surviving]}); continue
            returns = []
            for x in surviving:
                fwd = _forward_return_ticker(x.get("ticker", ""), d, horizon, cache_end)
                if fwd is not None:
                    returns.append((x.get("ticker"), fwd))
            if not returns:
                per_snap.append({"date": d.isoformat(), "sha": sha[:12],
                                 "reason": "no ticker fwd returns"}); continue
            mean_ret = sum(r for _, r in returns) / len(returns)
            excess = mean_ret - bench_fwd
            excesses.append(excess)
            per_snap.append({
                "date": d.isoformat(),
                "sha": sha[:12],
                "surviving": returns,
                "mean_return_pct": mean_ret * 100.0,
                "benchmark_return_pct": bench_fwd * 100.0,
                "excess_pct": excess * 100.0,
                "excluded": excluded,
            })
        return {
            "asset": asset_id,
            "benchmark": benchmark_name,
            "horizon_bdays": horizon,
            "n_evaluable_snapshots": len(excesses),
            "mean_excess_pct": (sum(excesses) / len(excesses) * 100.0) if excesses else None,
            "win_rate": (sum(1 for e in excesses if e > 0) / len(excesses)) if excesses else None,
            "per_snapshot": per_snap,
        }

    return {
        "id": "P-3",
        "kind": "descriptive_only",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "horizon_bdays": horizon,
        "exclusion_filter": [
            "warn_reason present",
            "excess_return_pct > 200",
            "n_days < 180",
        ],
        "SP500": _process("sp500_analysis", sp_prices, "^GSPC", "SP500"),
        "KOSPI": _process("kospi_analysis", ks_prices, "KS11", "KOSPI"),
        "correction_note": (
            "5d horizon only (10d/20d infeasible today). Original prompt required 20d excess>0 and "
            "win_rate>50%; that criterion is data-insufficient and cannot be judged."
        ),
    }


# ── main dispatcher ──────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase P backtest runner")
    parser.add_argument("cmd", choices=["p4", "p1", "p2", "p3", "gate"])
    args = parser.parse_args()

    prereg = assert_preregistration()

    if args.cmd == "gate":
        print("[gate] OK")
        return 0

    if args.cmd == "p4":
        result = run_p4(prereg)
        out_path = ROOT / "output" / "phase_p_p4_results.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        # Level 8 evidence line
        def _fmt(x, spec="+.3f"):
            return "None" if x is None else format(x, spec)
        for var in ("unconditional", "confidence_gte_60", "confidence_gte_70"):
            for asset in ("SP500", "KOSPI"):
                r = result["variants"][var][asset]
                strat = r["strategy"]
                bh = r["benchmark_buy_and_hold"]
                print(
                    f"P4 {asset:5s} {var:20s} "
                    f"strat_cum={_fmt(strat['cumulative_return_pct'])}%% "
                    f"bh_cum={_fmt(bh['cumulative_return_pct'])}%% "
                    f"strat_sharpe={_fmt(strat['sharpe'], '.3f')} "
                    f"bh_sharpe={_fmt(bh['sharpe'], '.3f')} "
                    f"strat_mdd={_fmt(strat['max_drawdown_pct'])}%% "
                    f"trades={r['n_trades']} avg_exp={r['avg_exposure_pct']:.1f}%%"
                )
        return 0

    if args.cmd == "p1":
        result = run_p1(prereg)
        out_path = ROOT / "output" / "phase_p_p1_results.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        top_r = result["top5_hit_rate"]; bot_r = result["bottom5_hit_rate"]
        print(
            f"P1 SP500 5d n_snap={result['n_evaluable_snapshots']} "
            f"top5={top_r if top_r is None else f'{top_r:.3f}'} "
            f"({result['top5_hits']}/{result['top5_total']}) "
            f"bot5={bot_r if bot_r is None else f'{bot_r:.3f}'} "
            f"({result['bottom5_hits']}/{result['bottom5_total']}) "
            f"delta={result['delta_top_minus_bottom']}"
        )
        return 0

    if args.cmd == "p2":
        result = run_p2(prereg)
        out_path = ROOT / "output" / "phase_p_p2_results.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        mp = result["mean_precision_at_5"]; base = result["chance_baseline_precision_at_5"]
        print(
            f"P2 SP500 5d n_snap={result['n_evaluable_snapshots']} "
            f"universe={result['universe_union_size']} "
            f"mean_prec@5={mp if mp is None else f'{mp:.3f}'} "
            f"baseline={base if base is None else f'{base:.3f}'}"
        )
        return 0

    if args.cmd == "p3":
        result = run_p3(prereg)
        out_path = ROOT / "output" / "phase_p_p3_results.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        for asset in ("SP500", "KOSPI"):
            d = result[asset]
            me = d["mean_excess_pct"]; wr = d["win_rate"]
            print(
                f"P3 {asset} 5d n_snap={d['n_evaluable_snapshots']} "
                f"mean_excess={me if me is None else f'{me:+.3f}%'} "
                f"win_rate={wr if wr is None else f'{wr:.3f}'}"
            )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
