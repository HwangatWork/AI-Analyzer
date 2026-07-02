# -*- coding: utf-8 -*-
"""US ticker snapshot builder.

Produces analysis.json / parsed.json / report.md for US tickers (NVDA, GOOGL,
VRT, etc.) using yfinance only. The Consensus Tracker dashboard tab was
originally built for Korean tickers (WiseReport HTML parsing) so a lot of
fields are structurally unavailable for US names. We fill what we can from
yfinance and mark the rest with `not_applicable_reason` so the UI can render
"US ticker — 해당 데이터 없음" gracefully.

Honest scope:
  - Available: aggregate target (mean/high/low/median), n_analysts,
    Buy/Hold/Sell breakdown (today + 1 month ago), close, currency,
    recommendation_mean/key.
  - NOT available: per-firm broker table, WiseReport arithmetic
    invariant (PER * EPS ≈ close), quarterly revenue/op_income actual,
    KCMI Korean-market bias context, Korean news-based Global IB.
  - Q1~Q4 depend on estimate-revision fields we cannot get from yfinance
    aggregate — those become INSUFFICIENT.

Usage:
    python tools/consensus/us_ticker_snapshot.py --ticker NVDA --smoke
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, Optional


DEFAULT_OUT_DIR = "output/consensus_snapshot"


US_TICKER_COMPANY_FALLBACK = {
    "NVDA": "NVIDIA Corporation",
    "GOOGL": "Alphabet Inc. (Class A)",
    "VRT": "Vertiv Holdings Co",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "AMZN": "Amazon.com, Inc.",
    "META": "Meta Platforms, Inc.",
    "TSLA": "Tesla, Inc.",
}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _yf_breakdown_to_dict(row) -> Optional[dict]:
    if not row:
        return None
    def _int_or_none(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        return None
    sb = _int_or_none(row.get("strongBuy"))
    b = _int_or_none(row.get("buy"))
    h = _int_or_none(row.get("hold"))
    s = _int_or_none(row.get("sell"))
    ss = _int_or_none(row.get("strongSell"))
    total = sum(x for x in (sb, b, h, s, ss) if x is not None)
    return {
        "strong_buy": sb, "buy": b, "hold": h,
        "sell": s, "strong_sell": ss,
        "total": total if total else None,
    }


def build_us_analysis(ticker: str) -> dict:
    """Fetch yfinance data for a US ticker and produce analysis-compatible dict.

    Returns dict with same top-level keys as Korean analysis.json:
      schema_version, ticker, company, answers, raw_inputs, data_quality,
      meta_audit, reconciliation, global_ib_named, parser_warnings,
      probed_at.
    """
    warnings: list[str] = []
    result: dict[str, Any] = {
        "schema_version": "0.3-us",
        "ticker": ticker,
        "company": None,
        "probed_at": _now_iso(),
        "answers": {},
        "raw_inputs": {},
        "data_quality": {"score": 0.0, "components": {}},
        "meta_audit": {},
        "reconciliation": {},
        "global_ib_named": [],
        "parser_warnings": warnings,
    }

    try:
        import yfinance as yf  # type: ignore
    except ImportError as e:
        warnings.append(f"yfinance_not_importable: {e!r}")
        result["company"] = US_TICKER_COMPANY_FALLBACK.get(ticker, ticker)
        _fill_meta_audit(result, ticker, has_data=False)
        result["data_quality"] = {"score": 0.0, "components": {"yfinance": False}}
        return result

    t = yf.Ticker(ticker)
    info = {}
    apt = {}
    rec_rows: list[dict] = []
    try:
        info = t.info or {}
    except Exception as e:
        warnings.append(f"info_failed: {e!r}")
    try:
        apt = t.analyst_price_targets or {}
    except Exception as e:
        warnings.append(f"analyst_price_targets_failed: {e!r}")
    try:
        rec_df = t.recommendations
        if rec_df is not None and not rec_df.empty:
            rec_rows = rec_df.to_dict(orient="records")
    except Exception as e:
        warnings.append(f"recommendations_failed: {e!r}")

    company = (
        info.get("shortName") or info.get("longName") or
        US_TICKER_COMPANY_FALLBACK.get(ticker) or ticker
    )
    result["company"] = company

    currency = info.get("currency") or "USD"
    target_mean = apt.get("mean") if apt else info.get("targetMeanPrice")
    target_high = apt.get("high") if apt else info.get("targetHighPrice")
    target_low = apt.get("low") if apt else info.get("targetLowPrice")
    target_median = apt.get("median") if apt else None
    close_latest = (
        apt.get("current") if apt else
        info.get("currentPrice") or info.get("regularMarketPrice")
    )
    n_analysts = info.get("numberOfAnalystOpinions")
    rec_mean = info.get("recommendationMean")
    rec_key = info.get("recommendationKey")

    row0 = next((r for r in rec_rows if r.get("period") == "0m"), None)
    row1 = next((r for r in rec_rows if r.get("period") == "-1m"), None)
    breakdown_today = _yf_breakdown_to_dict(row0)
    breakdown_prior = _yf_breakdown_to_dict(row1)

    raw = result["raw_inputs"]
    raw["investment_opinion"] = rec_mean  # 1=Strong Buy scale (Yahoo)
    raw["recommendation_key"] = rec_key
    raw["n_analysts"] = int(n_analysts) if isinstance(n_analysts, (int, float)) else None
    raw["latest_target_price"] = target_mean
    raw["latest_target_price_date"] = _today_iso()
    raw["prior_target_price"] = None  # need snapshot history
    raw["target_price_change_label"] = "insufficient"
    raw["Q1_source"] = "insufficient"
    raw["target_high"] = target_high
    raw["target_low"] = target_low
    raw["target_median"] = target_median
    raw["close_price_latest"] = close_latest
    raw["currency"] = currency
    raw["static_target_price"] = target_mean
    raw["static_eps"] = info.get("trailingEps") or info.get("forwardEps")
    raw["static_per"] = info.get("trailingPE") or info.get("forwardPE")
    raw["chart_latest_target_price"] = target_mean
    raw["opinion_breakdown"] = breakdown_today or {
        "strong_buy": None, "buy": None, "hold": None,
        "sell": None, "strong_sell": None, "total": None,
    }
    raw["opinion_breakdown_prior"] = breakdown_prior or {
        "strong_buy": None, "buy": None, "hold": None,
        "sell": None, "strong_sell": None, "total": None,
    }
    # Sections we cannot fill for US tickers via yfinance alone:
    raw["per_firm_targets"] = {
        "found": False, "n_firms": 0, "firms": [],
        "high_target": target_high, "low_target": target_low,
        "mean_target": target_mean,
        "not_applicable_reason": (
            "US tickers do not expose per-firm broker targets on free channels; "
            "aggregate range shown."
        ),
    }
    raw["quarterly_earnings"] = {
        "found": False,
        "not_applicable_reason": (
            "yfinance does not provide quarterly consensus vs actual "
            "surprise history for free."
        ),
    }
    raw["annual_indicators"] = {"found": False, "metrics": {}}

    # Q1~Q5 — mostly INSUFFICIENT until snapshot history + estimate feed
    ans = result["answers"]
    ans["Q1_direction"] = "INSUFFICIENT"
    ans["Q1_target_price_change_pct"] = None
    ans["Q2_direction"] = "INSUFFICIENT"
    ans["Q2_eps_change_pct"] = None
    ans["Q3_direction"] = "INSUFFICIENT"
    ans["Q3_op_income_change_pct"] = None
    ans["Q4_quadrant"] = "INSUFFICIENT"
    # Q5 for US ticker: yfinance already IS global — comparison to Korean
    # domestic set is not meaningful. Mark distinctly.
    ans["Q5_global_vs_domestic"] = "US_TICKER_NOT_APPLICABLE"
    ans["Q5_details"] = {
        "per_firm_jpm_gs_available": False,
        "note": "US ticker; yfinance aggregate is already global consensus.",
    }

    # Reconciliation — PER * EPS = close arithmetic check (available if all three)
    eps = raw["static_eps"]
    per = raw["static_per"]
    reconciliation: dict[str, Any] = {}
    if eps and per and close_latest:
        implied = eps * per
        diff_pct = (implied - close_latest) / close_latest * 100
        reconciliation["per_times_eps"] = implied
        reconciliation["close_latest"] = close_latest
        reconciliation["per_eps_close_diff_pct"] = diff_pct
    result["reconciliation"] = reconciliation

    # data_quality — component-weighted score
    components = {
        "target_mean": target_mean is not None,
        "n_analysts": n_analysts is not None,
        "close_price": close_latest is not None,
        "breakdown_today": bool(breakdown_today),
        "target_high_low": target_high is not None and target_low is not None,
    }
    score = sum(1 for v in components.values() if v) / len(components)
    result["data_quality"] = {
        "score": round(score, 3), "components": components,
    }

    _fill_meta_audit(result, ticker, has_data=bool(target_mean))
    return result


def _fill_meta_audit(result: dict, ticker: str, has_data: bool) -> None:
    result["meta_audit"] = {
        "us_ticker": True,
        "kr_buy_bias_warning": False,
        "kr_buy_bias_source": (
            "N/A — US ticker (KCMI Korean-market bias does not apply)"
        ),
        "point_in_time_status": "snapshot",
        "point_in_time_note": (
            "single yfinance fetch; no daily accumulation yet."
        ),
        "target_price_role": "sentiment_valuation_proxy",
        "target_price_role_source": (
            "Bradshaw, Brown, Huang 2013 — 12-month target price achievement 38%. "
            "Applies to US tickers as well; aggregate mean shown."
        ),
        "us_ticker_limitations": [
            "no per-firm broker table (only aggregate)",
            "no quarterly consensus surprise history",
            "no Korean-market-specific optimism-bias correction",
            "Q1~Q4 remain INSUFFICIENT until estimate-revision feed",
        ],
        "has_data": has_data,
    }


def render_us_report_md(analysis: dict) -> str:
    ticker = analysis.get("ticker", "?")
    company = analysis.get("company") or ticker
    raw = analysis.get("raw_inputs") or {}
    ans = analysis.get("answers") or {}
    curr = raw.get("currency") or "USD"
    def fmt_money(v):
        if v is None:
            return "N/A"
        if curr == "USD":
            return f"${v:,.2f}"
        return f"{v:,.0f}원"
    def fmt_pct(v):
        if v is None:
            return "N/A"
        return f"{v:+.2f}%"

    lines = [
        f"# Consensus Snapshot -- {company} ({ticker})",
        "",
        f"- 종목 시장: **US** (yfinance aggregate; Korean-specific 데이터 없음)",
        f"- 데이터 시점 상태: **snapshot** (daily 누적 시작 전)",
        f"- 데이터 품질 점수: **{analysis.get('data_quality',{}).get('score',0.0):.2f}** / 1.00",
        "",
        "## 기본 컨센서스 (yfinance 집계)",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 통화 | {curr} |",
        f"| 투자의견 (1=Strong Buy scale) | {raw.get('investment_opinion') if raw.get('investment_opinion') is not None else 'N/A'} |",
        f"| 추정기관 수 | {raw.get('n_analysts') or 'N/A'} |",
        f"| 평균 목표가 | {fmt_money(raw.get('latest_target_price'))} |",
        f"| 최고 목표가 | {fmt_money(raw.get('target_high'))} |",
        f"| 최저 목표가 | {fmt_money(raw.get('target_low'))} |",
        f"| 중간값 목표가 | {fmt_money(raw.get('target_median'))} |",
        f"| 현재 주가 | {fmt_money(raw.get('close_price_latest'))} |",
        "",
        "## 투자의견 분포",
        "",
    ]
    bd_t = raw.get("opinion_breakdown") or {}
    bd_p = raw.get("opinion_breakdown_prior") or {}
    lines.append("| 의견 | 오늘 | 1개월 전 |")
    lines.append("|---|---:|---:|")
    for key, label in [
        ("strong_buy", "Strong Buy"), ("buy", "Buy"), ("hold", "Hold"),
        ("sell", "Sell"), ("strong_sell", "Strong Sell"),
    ]:
        t = bd_t.get(key)
        p = bd_p.get(key)
        lines.append(
            f"| {label} | {t if t is not None else 0} | "
            f"{p if p is not None else 0} |"
        )
    lines.append(f"| **합계** | **{bd_t.get('total') or 0}** | **{bd_p.get('total') or 0}** |")
    lines.append("")

    lines.append("## AI 분석 Q1~Q5")
    lines.append("")
    lines.append("| 질문 | 결과 |")
    lines.append("|---|---|")
    for qk, label in [
        ("Q1_direction", "Q1 목표주가 추세"),
        ("Q2_direction", "Q2 EPS 추세"),
        ("Q3_direction", "Q3 영업이익 추세"),
        ("Q4_quadrant", "Q4 4사분면 분류"),
        ("Q5_global_vs_domestic", "Q5 글로벌 vs 국내"),
    ]:
        lines.append(f"| {label} | {ans.get(qk, 'N/A')} |")
    lines.append("")

    lines.append("## 한계 (정직)")
    lines.append("")
    for note in (analysis.get("meta_audit") or {}).get("us_ticker_limitations", []):
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## 참고")
    lines.append("")
    lines.append("- Bradshaw, Brown, Huang 2013: 12-month target price achievement 38%, MAFE ~45%. Applies to US targets too.")
    lines.append("- yfinance is an unofficial wrapper; endpoint stability is not guaranteed.")
    return "\n".join(lines) + "\n"


def write_us_snapshot(
    ticker: str,
    out_dir: str = DEFAULT_OUT_DIR,
    date: Optional[str] = None,
) -> dict:
    """Full pipeline: build analysis + write flat files + write immutable history."""
    date = date or _today_iso()
    analysis = build_us_analysis(ticker)
    # Parsed dict for US is empty-ish; mirror analysis for consistency
    parsed = {
        "schema_version": "0.3-us",
        "ticker": ticker,
        "company": analysis.get("company"),
        "us_ticker": True,
        "yfinance_probed_at": analysis.get("probed_at"),
    }
    report_md = render_us_report_md(analysis)

    os.makedirs(out_dir, exist_ok=True)

    # Flat files
    flat_analysis = os.path.join(out_dir, f"{ticker}_{date}_analysis.json")
    flat_parsed = os.path.join(out_dir, f"{ticker}_{date}_parsed.json")
    flat_report = os.path.join(out_dir, f"{ticker}_{date}_report.md")

    with open(flat_analysis, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(flat_parsed, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(parsed, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(flat_report, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report_md)

    # Immutable history via snapshot_store
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, SnapshotExistsError, QualityGateError,
        )
        try:
            manifest = write_snapshot(
                ticker=ticker, parsed=parsed, analysis=analysis,
                report_md=report_md, date=date, force=False,
            )
        except SnapshotExistsError:
            manifest = {"status": "already_exists"}
        except QualityGateError as e:
            manifest = {"status": f"quality_gate_refused: {e}"}
    except ImportError:
        manifest = {"status": "snapshot_store_not_importable"}

    return {
        "ticker": ticker, "date": date,
        "analysis_path": flat_analysis,
        "parsed_path": flat_parsed,
        "report_path": flat_report,
        "manifest": manifest,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True,
                   help="US ticker symbol, e.g. NVDA")
    p.add_argument("--smoke", action="store_true",
                   help="REQUIRED - confirms intent to make yfinance network call")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--date", default=None,
                   help="ISO date; default is today")
    args = p.parse_args(argv)

    if not args.smoke:
        sys.stderr.write(
            "ERROR: --smoke flag required (default-deny). US ticker snapshot "
            "makes outgoing yfinance calls.\n"
        )
        return 4

    r = write_us_snapshot(args.ticker, args.out_dir, args.date)
    sys.stdout.write(
        f"us_snapshot: ticker={r['ticker']} date={r['date']} "
        f"analysis={r['analysis_path']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
