# -*- coding: utf-8 -*-
"""Phase 14-0-B2 — WiseReport HTML parser (Validation Agent).

Pure function: takes raw HTML string, returns structured dict.
Standard library only (json, re).

Extracted fields (best-effort, marked null when absent):

  - investment_opinion          : numeric rating (e.g. 4.00 on 1-5 scale)
  - n_analysts                  : number of contributing analysts
  - target_price_series         : [(epoch_ms, value_or_null), ...] monthly
  - close_price_series          : [(epoch_ms, value_or_null), ...] monthly
  - latest_target_price         : last non-null target_price entry
  - prior_target_price          : entry 1 month before latest non-null
  - latest_target_price_date    : ISO date for latest_target_price
  - target_price_change_1m_pct  : percent change from prior to latest
  - estimates                   : {fy_label: {revenue, op_income, eps, ...}}
  - parser_warnings             : list[str]
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any, Optional


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"-?[\d,]+\.?\d*")
_CHART_DATA2_RE = re.compile(r"chartData2\s*=\s*(\{.*?\});", re.DOTALL)
_CHART_DATA3_RE = re.compile(r"chartData3\s*=\s*(\{.*?\});", re.DOTALL)
_RES_OBJ_RE     = re.compile(r"var\s+res\s*=\s*(\{[^;]+\});", re.DOTALL)


# Row mapping for EarnigList `res.data`. Verified empirically against the
# fixture (RCA notebook 2026-06-30):
#   data[0] = 매출액 consensus (pre-announcement)
#   data[1] = 매출액 actual (reported)
#   data[2] = 매출액 Surprise % = (actual - cons) / cons * 100
#   data[3] = 매출액 YoY %
#   data[4] = 매출액 QoQ % (extended row)
#   data[5] = 영업이익 consensus
#   data[6] = 영업이익 actual
#   data[7] = 영업이익 Surprise %
#   data[8] = 영업이익 YoY %
#   data[9] = 영업이익 QoQ %
QUARTERLY_ROW_LABELS = [
    "revenue_consensus", "revenue_actual", "revenue_surprise_pct",
    "revenue_yoy_pct", "revenue_qoq_pct",
    "op_income_consensus", "op_income_actual", "op_income_surprise_pct",
    "op_income_yoy_pct", "op_income_qoq_pct",
]


OPINION_BREAKDOWN_LABELS_KO_TO_EN = {
    "강력매수": "strong_buy",   # WiseReport label
    "적극매수": "strong_buy",   # alias seen on Naver Finance variants
    "매수": "buy",
    "중립": "hold",
    "보유": "hold",             # alias used on some pages
    "매도": "sell",
    "강력매도": "strong_sell",
    "적극매도": "strong_sell",
}


def _strip_html(s: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", s)).strip()


def _to_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s in {"-", "--", "N/A", "null"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _epoch_ms_to_iso_date(ms: float) -> str:
    return _dt.datetime.fromtimestamp(
        ms / 1000.0, tz=_dt.timezone.utc
    ).date().isoformat()


def parse_chart_data2(html: str) -> dict:
    """Extract the chartData2 JS object (target_price + close_price series).

    Returns:
      {
        "target_price_series": [{x_ms, y}, ...],
        "close_price_series":  [{x_ms, y}, ...],
        "found": bool,
      }
    """
    m = _CHART_DATA2_RE.search(html)
    if not m:
        return {
            "target_price_series": [],
            "close_price_series": [],
            "found": False,
        }
    blob = m.group(1)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {
            "target_price_series": [],
            "close_price_series": [],
            "found": False,
        }
    tp = [
        {"x_ms": item.get("x"), "y": item.get("y")}
        for item in data.get("target_price", [])
        if isinstance(item, dict)
    ]
    cp = [
        {"x_ms": item.get("x"), "y": item.get("y")}
        for item in data.get("close_price", [])
        if isinstance(item, dict)
    ]
    return {
        "target_price_series": tp,
        "close_price_series": cp,
        "found": True,
    }


def derive_target_price_trend(series: list[dict]) -> dict:
    """From the monthly target_price series, compute the latest non-null,
    its date, and 1-month change vs the prior non-null entry.
    """
    non_null = [
        e for e in series
        if e.get("y") is not None and isinstance(e.get("y"), (int, float))
    ]
    if not non_null:
        return {
            "latest_target_price": None,
            "latest_target_price_date": None,
            "prior_target_price": None,
            "target_price_change_1m_pct": None,
        }
    latest = non_null[-1]
    prior = non_null[-2] if len(non_null) >= 2 else None
    latest_y = float(latest["y"])
    latest_date = _epoch_ms_to_iso_date(float(latest["x_ms"]))
    prior_y = float(prior["y"]) if prior else None
    pct = None
    if prior_y and prior_y > 0:
        pct = (latest_y - prior_y) / prior_y * 100.0
    return {
        "latest_target_price": latest_y,
        "latest_target_price_date": latest_date,
        "prior_target_price": prior_y,
        "target_price_change_1m_pct": pct,
    }


def parse_static_consensus_table(html: str) -> dict:
    """Extract the AUTHORITATIVE current consensus row from WiseReport.

    Header order (WiseReport c1010001.aspx):
        투자의견 | 목표주가(원) | EPS(원) | PER(배) | 추정기관수
    Value row (cells in same order):
        4.00     | 3,177,083    | 307,655 | 8.54    | 24

    This is the *current* snapshot (authoritative). The chartData2 series
    is monthly history — its latest non-null entry can lag the static table
    by up to ~1 month and MUST NOT be used as 'current' target.

    Returns:
        {
          "investment_opinion": float | None,
          "target_price":       float | None,   # CURRENT consensus target
          "eps":                float | None,   # forward EPS estimate
          "per":                float | None,   # current trailing PER
          "n_analysts":         int | None,
          "cells_found":        int,
          "raw_cells":          list[str],
        }
    """
    out = {
        "investment_opinion": None,
        "target_price": None,
        "eps": None,
        "per": None,
        "n_analysts": None,
        "cells_found": 0,
        "raw_cells": [],
    }
    header_idx = html.find("추정기관수")
    if header_idx < 0:
        return out
    tr_start = html.find("<tr>", header_idx)
    if tr_start < 0:
        return out
    tr_end = html.find("</tr>", tr_start)
    row = html[tr_start:tr_end] if tr_end > 0 else html[tr_start:tr_start + 2000]
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
    clean_cells: list[str] = []
    parsed: list[Optional[float]] = []
    for cell in cells:
        clean = _strip_html(cell)
        clean_cells.append(clean)
        m = _NUM_RE.search(clean)
        parsed.append(_to_float(m.group(0)) if m else None)
    out["raw_cells"] = clean_cells
    out["cells_found"] = len(parsed)
    # Strict header-order mapping
    if len(parsed) >= 1:
        out["investment_opinion"] = parsed[0]
    if len(parsed) >= 2:
        out["target_price"] = parsed[1]
    if len(parsed) >= 3:
        out["eps"] = parsed[2]
    if len(parsed) >= 4:
        out["per"] = parsed[3]
    if len(parsed) >= 5:
        n = parsed[4]
        if n is not None:
            out["n_analysts"] = int(n) if isinstance(n, float) and n.is_integer() else n
    return out


def parse_opinion_and_analysts(html: str) -> dict:
    """Legacy helper kept for backward compatibility with existing tests.

    Now delegates to parse_static_consensus_table and returns just the
    opinion + n_analysts subset.
    """
    s = parse_static_consensus_table(html)
    return {
        "investment_opinion": s["investment_opinion"],
        "n_analysts": s["n_analysts"],
    }


def reconcile_sources(static: dict, chart: dict,
                       chart_close_latest: Optional[float]) -> dict:
    """Cross-check the two sources of truth.

    Returns dict with reconciliation flags + numeric discrepancies. Never
    raises; warnings list expresses any unresolved inconsistency.
    """
    warnings: list[str] = []
    notes: dict[str, Any] = {}

    # 1. PER * EPS ≈ close[-1] (within 1%) — internal arithmetic invariant
    if (static.get("per") is not None
            and static.get("eps") is not None
            and chart_close_latest is not None):
        implied = static["per"] * static["eps"]
        diff_pct = (implied - chart_close_latest) / chart_close_latest * 100
        notes["per_times_eps"] = implied
        notes["close_latest"] = chart_close_latest
        notes["per_eps_close_diff_pct"] = diff_pct
        if abs(diff_pct) > 1.0:
            warnings.append(
                f"per_eps_close_inconsistent: PER*EPS={implied:.0f} vs "
                f"close={chart_close_latest:.0f} (diff {diff_pct:+.2f}%)"
            )

    # 2. static_target vs chart[-1] target (allow historical lag, but flag big gap)
    if (static.get("target_price") is not None
            and chart.get("latest_target_price") is not None):
        s_t = static["target_price"]
        c_t = chart["latest_target_price"]
        if c_t > 0:
            gap_pct = (s_t - c_t) / c_t * 100
            notes["static_target"] = s_t
            notes["chart_latest_target"] = c_t
            notes["static_vs_chart_target_diff_pct"] = gap_pct
            if abs(gap_pct) > 50.0:
                # Extreme gap suggests one of the sources is wrong
                warnings.append(
                    f"static_chart_target_extreme_gap: static={s_t:.0f} vs "
                    f"chart={c_t:.0f} (diff {gap_pct:+.2f}%)"
                )

    return {"warnings": warnings, "notes": notes}


def parse_per_firm_targets(html: str) -> dict:
    """Parse the per-firm broker-level table (출처 / 작성일 / 목표가 ...).

    Header order (verified on WiseReport c1010001.aspx 2026-06-30 fixture):
        출처 | 작성일 | 목표가 | 이전목표가 | 변동률(%) | 투자의견 | 이전투자의견

    Returns:
      {
        "found": bool,
        "firms": [
          {"firm", "report_date", "target_price", "prior_target_price",
           "change_pct", "rating", "prior_rating"},
          ...
        ],
        "high_target": float | None,
        "low_target": float | None,
        "mean_target": float | None,
        "n_firms": int,
      }
    """
    out = {
        "found": False, "firms": [],
        "high_target": None, "low_target": None,
        "mean_target": None, "n_firms": 0,
    }
    # Locate the table containing the per-firm rows. Anchor on actual
    # WiseReport header text observed on 2026-06-30 fixture:
    # 제공처 / 최종일자 / 목표가 / 직전목표가 / 변동률 / 투자의견 / 직전투자의견.
    table_iter = re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
    target_table = None
    for tm in table_iter:
        body = tm.group(1)
        if "제공처" in body and "직전목표가" in body and "변동률" in body:
            target_table = body
            break
    if target_table is None:
        return out
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", target_table, re.DOTALL)
    targets: list[float] = []
    for tr in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if len(tds) < 7:
            continue
        cells = [_strip_html(c) for c in tds]
        # cells: [firm, date, target, prior_target, change_pct, rating, prior_rating]
        target_price = _to_float(re.sub(r"[^\d.\-]", "", cells[2])) if cells[2] else None
        prior_target = _to_float(re.sub(r"[^\d.\-]", "", cells[3])) if cells[3] else None
        change_pct = _to_float(re.sub(r"[^\d.\-]", "", cells[4])) if cells[4] else None
        if not cells[0] or target_price is None:
            continue
        out["firms"].append({
            "firm": cells[0],
            "report_date": cells[1],
            "target_price": target_price,
            "prior_target_price": prior_target,
            "change_pct": change_pct,
            "rating": cells[5] or None,
            "prior_rating": cells[6] or None,
        })
        targets.append(target_price)
    out["n_firms"] = len(out["firms"])
    if targets:
        out["found"] = True
        out["high_target"] = max(targets)
        out["low_target"] = min(targets)
        out["mean_target"] = sum(targets) / len(targets)
    return out


def parse_opinion_breakdown(html: str) -> dict:
    """Parse chartData3 → Buy/Hold/Sell breakdown (today + a_month_ago).

    Returns:
      {
        "today":       {strong_buy, buy, hold, sell, strong_sell, total},
        "a_month_ago": {strong_buy, buy, hold, sell, strong_sell, total},
        "found": bool,
      }
    Each count is int or None (null in HTML stays as None).
    """
    out = {
        "today": {"strong_buy": None, "buy": None, "hold": None,
                   "sell": None, "strong_sell": None, "total": None},
        "a_month_ago": {"strong_buy": None, "buy": None, "hold": None,
                         "sell": None, "strong_sell": None, "total": None},
        "found": False,
    }
    m = _CHART_DATA3_RE.search(html)
    if not m:
        return out
    try:
        d = json.loads(m.group(1))
    except json.JSONDecodeError:
        return out
    out["found"] = True
    for snapshot_key in ("today", "a_month_ago"):
        entries = d.get(snapshot_key, [])
        bucket = out[snapshot_key]
        running_total = 0
        any_present = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name_ko = entry.get("name")
            y = entry.get("y")
            field = OPINION_BREAKDOWN_LABELS_KO_TO_EN.get(name_ko)
            if not field:
                continue
            if y is not None:
                v = int(y) if isinstance(y, float) and y.is_integer() else y
                bucket[field] = v
                running_total += v if isinstance(v, (int, float)) else 0
                any_present = True
            else:
                bucket[field] = None
        if any_present:
            bucket["total"] = running_total
    return out


def parse_quarterly_earnings(html: str) -> dict:
    """Parse the EarnigList `var res = {...}` object → quarterly cons/actual.

    Returns:
      {
        "found": bool,
        "yymm": [str, ...],       # quarter periods, e.g. ["202509", "202512", "202603"]
        "announce_dates": [str],  # e.g. ["2025/10/29(...)", ...]
        "quarters": [
          {"yymm", "announce_date",
           "revenue_consensus", "revenue_actual", "revenue_surprise_pct",
           "revenue_yoy_pct", "revenue_qoq_pct",
           "op_income_consensus", "op_income_actual", "op_income_surprise_pct",
           "op_income_yoy_pct", "op_income_qoq_pct"},
          ...
        ],
      }
    Units: revenue/op_income are in 억원. Percent fields in %.
    """
    out = {"found": False, "yymm": [], "announce_dates": [], "quarters": []}
    m = _RES_OBJ_RE.search(html)
    if not m:
        return out
    try:
        res = json.loads(m.group(1))
    except json.JSONDecodeError:
        return out
    yymm = res.get("yymm", [])
    data = res.get("data", [])
    announce = res.get("yymmdd", [])
    if not yymm or not data:
        return out
    out["found"] = True
    out["yymm"] = list(yymm)
    out["announce_dates"] = list(announce)
    for q_idx, q_period in enumerate(yymm):
        # Each row dict uses 1-indexed keys "1","2","3"
        key = str(q_idx + 1)
        q: dict[str, Any] = {
            "yymm": q_period,
            "announce_date": announce[q_idx] if q_idx < len(announce) else None,
        }
        for row_idx, label in enumerate(QUARTERLY_ROW_LABELS):
            if row_idx < len(data) and isinstance(data[row_idx], dict):
                v = data[row_idx].get(key)
                q[label] = v
            else:
                q[label] = None
        out["quarters"].append(q)
    return out


def parse_annual_indicators(html: str) -> dict:
    """Parse the 주요지표 annual table (PER/EPS/BPS/EBITDA/DPS).

    Layout (inside the Markdown-like compact text seen between yymm headers):
      주요지표 | 2025/12(A) | 2026/12(E)
      PER      | 44.58      | 8.54
      PBR      | 15.06      | 5.45
      ...
      EPS      | 58,955원   | 307,655원
      ...

    Returns:
      {
        "found": bool,
        "fy_labels": ["2025/12(A)", "2026/12(E)"],
        "metrics": {metric_name: [v_fy0, v_fy1]},
      }
    """
    out = {"found": False, "fy_labels": [], "metrics": {}}
    # Locate "주요지표" then the values immediately after
    idx = html.find("주요지표")
    if idx < 0:
        return out
    # Find the section enclosing the table; use a window large enough
    chunk = html[idx:idx + 3500]
    # Build mapping of metric -> list of cell values by scanning row by row.
    # Strategy: split into <tr> blocks, look for known metric labels in <th>,
    # extract <td> numeric cells.
    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.DOTALL)
    metrics_of_interest = (
        "PER", "PBR", "PCR", "EV/EBITDA",
        "EPS", "BPS", "EBITDA", "주당DPS", "현금배당수익률",
    )
    for tr in tr_blocks:
        ths = re.findall(r"<th[^>]*>(.*?)</th>", tr, re.DOTALL)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if not ths or not tds:
            continue
        label = _strip_html(ths[0])
        if not label:
            continue
        if label in metrics_of_interest:
            vals: list[Optional[float]] = []
            for cell in tds:
                clean = _strip_html(cell)
                mnum = _NUM_RE.search(clean)
                vals.append(_to_float(mnum.group(0)) if mnum else None)
            out["metrics"][label] = vals
            out["found"] = True
    # Determine FY labels (look for "2025/12(A)" "2026/12(E)" pattern)
    fy_matches = re.findall(r"(20\d{2}/12)\(([AE])\)", chunk)
    fy_labels = []
    seen = set()
    for ym, ae in fy_matches:
        lbl = f"{ym}({ae})"
        if lbl not in seen:
            seen.add(lbl)
            fy_labels.append(lbl)
    out["fy_labels"] = fy_labels
    return out


def parse_estimates_table(html: str) -> dict:
    """Locate the 추정실적 / 주요지표 table with FY columns.

    Returns dict keyed by fiscal-year label (e.g. "2025/12(실적)",
    "2026/12(컨센서스)") mapping to metric → value dict.

    Best-effort: WiseReport HTML uses a complex nested table. We extract
    by row labels (매출액, 영업이익, 당기순이익, EPS, BPS, PER, PBR, ROE).

    If extraction fails the returned dict is empty.
    """
    out: dict[str, dict[str, Optional[float]]] = {}
    # Find FY column headers (e.g. "2025/12(실적)", "2026/12(컨센서스)")
    fy_headers = re.findall(
        r"(20\d{2}/\d{2})\(([^)]+)\)", html
    )
    # Deduplicate while preserving order
    seen = set()
    fy_labels: list[str] = []
    for ym, kind in fy_headers:
        label = f"{ym}({kind})"
        if label not in seen:
            seen.add(label)
            fy_labels.append(label)
    if not fy_labels:
        return out

    # Metric rows to extract
    metrics = ["매출액", "영업이익", "당기순이익", "EPS", "BPS", "PER", "PBR", "ROE"]
    for metric in metrics:
        idx = html.find(f">{metric}<")
        if idx < 0:
            idx = html.find(metric)
        if idx < 0:
            continue
        # Find first <tr> containing this metric
        tr_start = html.rfind("<tr", 0, idx)
        tr_end = html.find("</tr>", idx)
        if tr_start < 0 or tr_end < 0:
            continue
        row = html[tr_start:tr_end]
        # Get all <td>...</td> cells, excluding the first (label cell)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        # Also try <th>
        if not cells:
            cells = re.findall(r"<th[^>]*>(.*?)</th>", row, re.DOTALL)
        # Map each FY label to the corresponding cell, in order
        for i, fy_label in enumerate(fy_labels):
            if i >= len(cells):
                break
            clean = _strip_html(cells[i])
            mnum = _NUM_RE.search(clean)
            val = _to_float(mnum.group(0)) if mnum else None
            out.setdefault(fy_label, {})[metric] = val
    return out


def _latest_non_null_close(series: list[dict]) -> Optional[float]:
    non_null = [e["y"] for e in series
                if e.get("y") is not None
                and isinstance(e.get("y"), (int, float))]
    return float(non_null[-1]) if non_null else None


def parse_wisereport_html(html: str) -> dict:
    """Top-level parser. Returns full snapshot dict.

    Authoritative source selection (post RCA 2026-06-30):
      - CURRENT consensus (target / EPS / PER / opinion / n_analysts):
        STATIC TABLE  (parse_static_consensus_table)
      - HISTORICAL trend (1-month change):
        chartData2.target_price (parse_chart_data2 + derive_target_price_trend)
      - CURRENT close price:
        chartData2.close_price latest non-null

    Static table is treated as primary because chartData2's last monthly
    point typically lags by ~1 month and may be null for the current
    month while the static table is live.

    Reconciliation:
      - PER * EPS  ==  close_latest  (within 1%)
      - static_target  ~=  chart_latest_target  (within 50% — beyond is flagged)
    """
    warnings: list[str] = []
    chart = parse_chart_data2(html)
    if not chart["found"]:
        warnings.append("chart_data2_not_found")
    trend = derive_target_price_trend(chart["target_price_series"])
    static = parse_static_consensus_table(html)
    if static["cells_found"] < 5:
        warnings.append(
            f"static_table_incomplete: only {static['cells_found']} cells"
        )
    estimates = parse_estimates_table(html)
    if not estimates:
        warnings.append("estimates_table_not_found")

    close_latest = _latest_non_null_close(chart["close_price_series"])

    # Primary current target: static table; fallback: chart
    current_target = (
        static["target_price"] if static["target_price"] is not None
        else trend["latest_target_price"]
    )
    # Prior target: chart's latest non-null (one month ago)
    prior_target = trend["latest_target_price"]
    if (current_target is not None and prior_target is not None
            and prior_target > 0
            and abs(current_target - prior_target) > 1e-9):
        change_pct = (current_target - prior_target) / prior_target * 100.0
        change_label = "current_vs_chart_latest_nonnull"
    else:
        # Same value (e.g., when only chart available) — fall back to chart
        # internal trend (prior vs prior-prior)
        change_pct = trend["target_price_change_1m_pct"]
        prior_target = trend["prior_target_price"]
        change_label = "chart_internal_trend" if change_pct is not None else "insufficient"

    reconciliation = reconcile_sources(static, {
        "latest_target_price": trend["latest_target_price"],
    }, close_latest)
    warnings.extend(reconciliation["warnings"])

    # Phase 14-1-B additions
    opinion_breakdown = parse_opinion_breakdown(html)
    if not opinion_breakdown["found"]:
        warnings.append("opinion_breakdown_not_found")
    quarterly = parse_quarterly_earnings(html)
    if not quarterly["found"]:
        warnings.append("quarterly_earnings_not_found")
    annual_indic = parse_annual_indicators(html)
    if not annual_indic["found"]:
        warnings.append("annual_indicators_not_found")
    per_firm = parse_per_firm_targets(html)
    if not per_firm["found"]:
        warnings.append("per_firm_targets_not_found")

    # n_analysts cross-check vs breakdown total (internal invariant)
    if (static["n_analysts"] is not None
            and opinion_breakdown["today"]["total"] is not None
            and static["n_analysts"] != opinion_breakdown["today"]["total"]):
        warnings.append(
            f"n_analysts_breakdown_mismatch: static={static['n_analysts']} "
            f"breakdown_total={opinion_breakdown['today']['total']}"
        )

    return {
        "schema_version": "0.3",  # bump after Phase 14-1-B
        # Authoritative current values (from static table)
        "investment_opinion": static["investment_opinion"],
        "n_analysts": static["n_analysts"],
        "latest_target_price": current_target,
        "static_target_price": static["target_price"],
        "static_eps": static["eps"],
        "static_per": static["per"],
        "static_raw_cells": static["raw_cells"],
        # Trend
        "target_price_series": chart["target_price_series"],
        "close_price_series": chart["close_price_series"],
        "close_price_latest": close_latest,
        "chart_latest_target_price": trend["latest_target_price"],
        "chart_latest_target_date": trend["latest_target_price_date"],
        "prior_target_price": prior_target,
        "target_price_change_1m_pct": change_pct,
        "target_price_change_label": change_label,
        # Other
        "estimates": estimates,
        "annual_indicators": annual_indic,
        "quarterly_earnings": quarterly,
        "opinion_breakdown": opinion_breakdown,
        "per_firm_targets": per_firm,
        "reconciliation": reconciliation["notes"],
        "parser_warnings": warnings,
    }
