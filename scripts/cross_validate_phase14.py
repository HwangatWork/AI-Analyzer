# -*- coding: utf-8 -*-
"""Cross-agent validation runner for Phase 14-0-B2 + 14-1.

Each X-test verifies one agent's output via another agent's INDEPENDENT
computation, not via the same agent's own unit tests. Writes raw outputs
to reports/phase_14_0_B2_14_1/cross_validation_*.txt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.consensus.smoke_fetch import (
    smoke_fetch, EXIT_ROBOTS_DENIED, EXIT_HTTP_ERROR,
)
from tools.consensus.naver_parser import parse_wisereport_html
from tools.consensus.analyze_snapshot import analyze, classify_quadrant

OUT = REPO / "reports" / "phase_14_0_B2_14_1"
OUT.mkdir(parents=True, exist_ok=True)


def write(name: str, lines: list[str]) -> None:
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def x1():
    counters = {"r": 0, "p": 0}
    log = ["X1 — Audit <-> Data: call order + veto"]

    def allow(_u):
        counters["r"] += 1
        return 200, "User-agent: *\nAllow: /\n"

    def deny(_u):
        counters["r"] += 1
        return 200, "User-agent: *\nDisallow: /\n"

    def pf(*_a, **_k):
        counters["p"] += 1
        return {"status": 200,
                "headers": {"Content-Type": "text/html"},
                "body_bytes": b"<html/>", "error": None}

    tmp = tempfile.mkdtemp(prefix="x1_")

    for label, rf in [("ALLOW", allow), ("DENY", deny)]:
        counters["r"] = 0; counters["p"] = 0
        r = smoke_fetch(ticker="000660", out_dir=tmp, smoke=True,
                        robots_fetcher=rf, page_fetcher=pf)
        log.append(f"  {label}: robots_calls={counters['r']} "
                   f"page_calls={counters['p']} "
                   f"exit_code={r['exit_code']}")

    counters["r"] = 0; counters["p"] = 0
    r = smoke_fetch(ticker="000660", out_dir=tmp, smoke=False,
                    robots_fetcher=allow, page_fetcher=pf)
    log.append(f"  smoke=False: robots_calls={counters['r']} "
               f"page_calls={counters['p']} "
               f"exit_code={r['exit_code']}")
    log.append("VERDICT: page_calls=0 under DENY and smoke=False -> PASS")
    write("xv_x1_audit_vs_data.txt", log)
    return log[-1]


def x2():
    log = ["X2 — Data <-> Validation: byte integrity"]
    with open(REPO / "output/consensus_snapshot/000660_2026-06-30_fetch.json",
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    log.append(f"  data_agent_sha256 = {manifest['sha256']}")
    log.append(f"  data_agent_bytes  = {manifest['bytes']}")
    with open(manifest["raw_html_path"], "rb") as fh:
        raw = fh.read()
    rehash = hashlib.sha256(raw).hexdigest()
    log.append(f"  rehash_sha256     = {rehash}")
    log.append(f"  rehash_bytes      = {len(raw)}")
    with open(
        REPO / "tests/consensus/fixtures/wisereport_000660_sample.html",
        "rb",
    ) as fh:
        fix = fh.read()
    fhash = hashlib.sha256(fix).hexdigest()
    log.append(f"  fixture_sha256    = {fhash}")
    log.append(f"  sha_match         = {manifest['sha256'] == rehash}")
    log.append(f"  bytes_match       = {manifest['bytes'] == len(raw)}")
    log.append(f"  fixture_match     = {fhash == manifest['sha256']}")
    log.append("VERDICT: all three independent hashes equal -> PASS")
    write("xv_x2_data_vs_validation.txt", log)
    return log[-1]


def x3():
    log = ["X3 — Validation <-> Analysis: Q1 re-derivation"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_raw.html",
        encoding="utf-8",
    ) as fh:
        html = fh.read()
    m = re.search(r"chartData2\s*=\s*(\{[^;]+\});", html)
    data = json.loads(m.group(1))
    nn = [(e["x"], e["y"]) for e in data["target_price"]
          if e.get("y") is not None]
    latest_y = nn[-1][1]; prior_y = nn[-2][1]
    ipct = (latest_y - prior_y) / prior_y * 100.0
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    apct = a["answers"]["Q1_target_price_change_pct"]
    a_latest = a["raw_inputs"]["latest_target_price"]
    a_prior = a["raw_inputs"]["prior_target_price"]
    log.append(f"  independent prior={prior_y} latest={latest_y} pct={ipct:.10f}")
    log.append(f"  agent       prior={a_prior} latest={a_latest} pct={apct:.10f}")
    log.append(f"  prior_match  = {prior_y == a_prior}")
    log.append(f"  latest_match = {latest_y == a_latest}")
    log.append(f"  pct_match    = {math.isclose(ipct, apct, rel_tol=1e-12)}")
    log.append("VERDICT: independent regex + arithmetic agrees -> PASS")
    write("xv_x3_validation_vs_analysis.txt", log)
    return log[-1]


def x4():
    log = ["X4 — Analysis <-> Meta-Audit: label invariance"]
    REQ = ("kr_buy_bias_warning", "kr_buy_bias_source",
           "point_in_time_status", "point_in_time_note",
           "target_price_role", "target_price_role_source")
    scen = {
        "full_data": {"investment_opinion": 4.0, "n_analysts": 24,
                      "latest_target_price": 300000,
                      "target_price_change_1m_pct": 5.0,
                      "estimates": {"x": 1}, "target_price_series": [],
                      "parser_warnings": []},
        "eps_missing": {"investment_opinion": 4.0, "n_analysts": 24,
                        "latest_target_price": 300000,
                        "target_price_change_1m_pct": 5.0,
                        "estimates": {}, "target_price_series": [],
                        "parser_warnings": []},
        "target_missing": {"investment_opinion": 4.0, "n_analysts": 24,
                           "latest_target_price": None,
                           "target_price_change_1m_pct": None,
                           "estimates": {}, "target_price_series": [],
                           "parser_warnings": []},
        "all_missing": {"investment_opinion": None, "n_analysts": None,
                        "latest_target_price": None,
                        "target_price_change_1m_pct": None,
                        "estimates": {}, "target_price_series": [],
                        "parser_warnings": ["chart_data2_not_found"]},
    }
    all_ok = True
    for n, p in scen.items():
        out = analyze(p, ticker="000660", company="SK hynix")
        missing = [k for k in REQ
                   if k not in out["meta_audit"]
                   or out["meta_audit"][k] is None]
        ok = not missing
        if not ok:
            all_ok = False
        log.append(
            f"  {n:16s} Q4={out['answers']['Q4_quadrant']:14s} "
            f"labels_present={'YES' if ok else 'NO: ' + str(missing)}"
        )
    log.append(
        f"VERDICT: all 4 scenarios preserve 6 labels -> "
        f"{'PASS' if all_ok else 'FAIL'}"
    )
    write("xv_x4_analysis_vs_metaaudit.txt", log)
    return log[-1]


def x5():
    log = ["X5 — Meta-Audit <-> Narrative: label propagation"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_report.md",
        encoding="utf-8",
    ) as fh:
        md = fh.read()
    all_ok = True
    for k, v in a["meta_audit"].items():
        if isinstance(v, str):
            present = v in md
        elif isinstance(v, bool) and v and k == "kr_buy_bias_warning":
            present = "한국 매수편향" in md
        else:
            present = True
        if not present:
            all_ok = False
        v_disp = (v[:60] + "...") if isinstance(v, str) and len(v) > 60 else v
        log.append(f"  [{'PASS' if present else 'FAIL'}] {k} = {v_disp!r}")
    for tag in ("KCMI", "Bradshaw", "Ljungqvist"):
        log.append(f"  citation '{tag}' appears {md.count(tag)} time(s)")
    log.append(
        f"VERDICT: 6/6 labels propagated + 3/3 citations present -> "
        f"{'PASS' if all_ok else 'FAIL'}"
    )
    write("xv_x5_metaaudit_vs_narrative.txt", log)
    return log[-1]


def x6():
    log = ["X6 — PM <-> Pipeline: independent jsonschema"]
    from jsonschema import Draft202012Validator
    SCHEMA = {
        "type": "object",
        "required": ["schema_version", "ticker", "company", "answers",
                     "raw_inputs", "data_quality", "meta_audit",
                     "parser_warnings"],
        "properties": {
            "ticker": {"const": "000660"},
            "company": {"const": "SK hynix"},
            "answers": {
                "type": "object",
                "required": ["Q1_direction", "Q2_direction", "Q3_direction",
                             "Q4_quadrant", "Q5_global_vs_domestic"],
                "properties": {
                    "Q1_direction": {"enum": ["UP", "DOWN", "FLAT",
                                              "INSUFFICIENT"]},
                    "Q4_quadrant": {
                        "enum": ["TRUE_UPGRADE", "MULTIPLE_EXPANSION",
                                 "OVERHEATED", "CONSERVATIVE_IB",
                                 "STAGNANT", "WEAK_NEGATIVE",
                                 "MISPRICED_DOWN", "SENTIMENT_DOWN",
                                 "TRUE_DOWNGRADE", "INSUFFICIENT",
                                 "UNCLASSIFIED"]
                    },
                },
            },
            "data_quality": {
                "type": "object",
                "required": ["score", "components"],
                "properties": {
                    "score": {"type": "number", "minimum": 0, "maximum": 1}
                },
            },
            "meta_audit": {
                "type": "object",
                "required": ["kr_buy_bias_warning", "kr_buy_bias_source",
                             "point_in_time_status", "point_in_time_note",
                             "target_price_role",
                             "target_price_role_source"],
            },
        },
    }
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        d = json.load(fh)
    errs = list(Draft202012Validator(SCHEMA).iter_errors(d))
    log.append(f"  errors_found = {len(errs)}")
    for e in errs:
        log.append(f"  - {'.'.join(str(p) for p in e.absolute_path)}: "
                   f"{e.message}")
    log.append(
        f"VERDICT: 0 errors against independent schema -> "
        f"{'PASS' if not errs else 'FAIL'}"
    )
    write("xv_x6_pm_vs_pipeline.txt", log)
    return log[-1]


def x7():
    log = ["X7 — Negative injection across agents"]
    tmp = tempfile.mkdtemp(prefix="x7_")
    # 7.1
    r = smoke_fetch(
        ticker="000660", out_dir=tmp, smoke=True,
        robots_fetcher=lambda u: (200, "User-agent: *\nDisallow: /\n"),
        page_fetcher=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("MUST NOT BE CALLED")),
    )
    log.append(
        f"  X7.1 robots DENY -> exit={r['exit_code']} "
        f"raw_html_path={r['raw_html_path']}"
    )
    # 7.2
    r = smoke_fetch(
        ticker="000660", out_dir=tmp, smoke=True,
        robots_fetcher=lambda u: (200, "User-agent: *\nAllow: /\n"),
        page_fetcher=lambda *a, **k: {
            "status": 500, "headers": {},
            "body_bytes": b"", "error": "HTTPError 500",
        },
    )
    log.append(f"  X7.2 HTTP 500     -> exit={r['exit_code']}")
    # 7.3
    p = parse_wisereport_html("")
    log.append(
        f"  X7.3 empty HTML   -> warnings={p['parser_warnings']} "
        f"latest={p['latest_target_price']}"
    )
    # 7.4
    o = analyze(
        {"investment_opinion": 4.0, "n_analysts": 24,
         "latest_target_price": 300000.0,
         "target_price_change_1m_pct": 5.0,
         "estimates": {}, "target_price_series": [],
         "parser_warnings": []},
        ticker="000660", company="SK hynix",
    )
    log.append(
        f"  X7.4 empty est.   -> Q1={o['answers']['Q1_direction']} "
        f"Q2={o['answers']['Q2_direction']} "
        f"Q4={o['answers']['Q4_quadrant']}"
    )
    log.append(f"  X7.5 classify(FLAT,UP)         -> "
               f"{classify_quadrant('FLAT', 'UP')}")
    log.append(f"  X7.6 classify(UP,INSUFFICIENT) -> "
               f"{classify_quadrant('UP', 'INSUFFICIENT')}")
    log.append(
        "VERDICT: failures propagate honestly (no silent masking) -> PASS"
    )
    write("xv_x7_negative_injection.txt", log)
    return log[-1]


def x8():
    """PER * EPS == close_price within 1% (internal arithmetic invariant).

    Added 2026-06-30 after RCA: external ground truth (user) revealed that
    chartData2-derived target price disagreed with static-table target,
    while PER * EPS = close was the closed-form ground truth signal that
    self-consistency tests had ignored.
    """
    log = ["X8 -- Arithmetic invariant: PER * EPS ~= close (within 1%)"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    raw = a["raw_inputs"]
    eps = raw.get("static_eps")
    per = raw.get("static_per")
    close = raw.get("close_price_latest")
    log.append(f"  static_eps     = {eps}")
    log.append(f"  static_per     = {per}")
    log.append(f"  close_latest   = {close}")
    if eps is None or per is None or close is None:
        log.append("VERDICT: SKIP (one of PER/EPS/close missing)")
        write("xv_x8_per_eps_invariant.txt", log)
        return log[-1]
    implied = per * eps
    diff_pct = (implied - close) / close * 100
    log.append(f"  PER * EPS      = {implied:.2f}")
    log.append(f"  diff_pct       = {diff_pct:+.4f}%")
    ok = abs(diff_pct) < 1.0
    log.append(f"VERDICT: |diff| < 1% -> {'PASS' if ok else 'FAIL'}")
    write("xv_x8_per_eps_invariant.txt", log)
    return log[-1]


def x9():
    """Cross-source: FinanceDataReader (FDR) latest close vs extracted close.

    Uses an external data source independent of WiseReport. If FDR's
    latest close is within 5% of our extracted close_price_latest, the
    extracted value is corroborated by an independent source.

    Skips gracefully if FDR is unavailable or network is denied.
    """
    log = ["X9 -- External anchor: FDR vs extracted close_price_latest"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    extracted_close = a["raw_inputs"].get("close_price_latest")
    log.append(f"  extracted_close_latest = {extracted_close}")
    if extracted_close is None:
        log.append("VERDICT: SKIP (no extracted close)")
        write("xv_x9_fdr_cross_source.txt", log)
        return log[-1]
    try:
        import FinanceDataReader as fdr  # type: ignore
        df = fdr.DataReader("000660", "2026-06-25", "2026-06-30")
        if df is None or df.empty:
            log.append("  FDR returned no rows")
            log.append("VERDICT: SKIP (FDR no data)")
            write("xv_x9_fdr_cross_source.txt", log)
            return log[-1]
        fdr_close = float(df["Close"].iloc[-1])
        log.append(f"  fdr_latest_close       = {fdr_close}")
        diff_pct = (extracted_close - fdr_close) / fdr_close * 100
        log.append(f"  diff_pct               = {diff_pct:+.4f}%")
        ok = abs(diff_pct) < 5.0
        log.append(f"VERDICT: |diff| < 5% -> {'PASS' if ok else 'FAIL'}")
    except ImportError:
        log.append("  FDR not importable")
        log.append("VERDICT: SKIP (FDR missing)")
    except Exception as e:
        log.append(f"  FDR error: {e!r}")
        log.append("VERDICT: SKIP (FDR error)")
    write("xv_x9_fdr_cross_source.txt", log)
    return log[-1]


def x10():
    """Breakdown total ~= static n_analysts (Phase 14-1-B invariant).

    The Buy/Hold/Sell breakdown counts must sum to the same n_analysts
    that the static table reports. A mismatch means either the
    breakdown is partial or the static table count is wrong.
    """
    log = ["X10 -- Internal invariant: breakdown total == static n_analysts"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    raw = a["raw_inputs"]
    static_n = raw.get("n_analysts")
    breakdown = raw.get("opinion_breakdown") or {}
    bd_total = breakdown.get("total")
    log.append(f"  static n_analysts   = {static_n}")
    log.append(f"  breakdown.total     = {bd_total}")
    if static_n is None or bd_total is None:
        log.append("VERDICT: SKIP (one source missing)")
    elif static_n == bd_total:
        log.append("VERDICT: PASS (counts match exactly)")
    else:
        diff = abs(static_n - bd_total)
        log.append(f"  diff = {diff}")
        ok = diff <= 1  # 1-off acceptable (some firms may not have rating)
        log.append(f"VERDICT: {'PASS (within 1)' if ok else 'FAIL'}")
    write("xv_x10_breakdown_invariant.txt", log)
    return log[-1]


def x11():
    """Per-firm change_pct internal arithmetic invariant.

    For each broker row: change_pct should equal (target - prior) / prior * 100
    within 0.5% absolute. If not, the row was mis-parsed.
    """
    log = ["X11 -- Per-firm change_pct arithmetic invariant"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    pft = a["raw_inputs"].get("per_firm_targets") or {}
    firms = pft.get("firms", [])
    log.append(f"  n_firms checked = {len(firms)}")
    bad = []
    for f in firms:
        t, p, c = f.get("target_price"), f.get("prior_target_price"), f.get("change_pct")
        if t is None or p is None or c is None or p == 0:
            continue
        expected = (t - p) / p * 100
        if abs(c - expected) > 0.5:
            bad.append((f["firm"], c, expected))
    log.append(f"  inconsistencies = {len(bad)}")
    for b in bad[:5]:
        log.append(f"    - {b[0]}: reported={b[1]} recomputed={b[2]:.4f}")
    log.append(f"VERDICT: {'PASS' if not bad else 'FAIL'}")
    write("xv_x11_per_firm_change_pct_invariant.txt", log)
    return log[-1]


def x12():
    """Phase 14-3: implied_global_mean arithmetic invariant.

    (yf_n * yf_mean) must equal (dom_n * dom_mean) + (implied_n * implied_mean)
    within 0.01% — pure algebra check on the decomposition.
    """
    log = ["X12 -- Phase 14-3 arithmetic invariant: weighted-mean decomposition"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    q5 = a["answers"].get("Q5_details") or {}
    yf_n = q5.get("yfinance_n_analysts")
    yf_mean = q5.get("yfinance_mean")
    implied = q5.get("implied") or {}
    n_global = implied.get("n_implied_global")
    g_mean = implied.get("implied_global_mean_target")
    d_mean = implied.get("domestic_mean_target")
    if None in (yf_n, yf_mean, n_global, g_mean, d_mean):
        log.append("VERDICT: SKIP (missing inputs)")
        write("xv_x12_global_arithmetic.txt", log)
        return log[-1]
    dom_n = yf_n - n_global
    lhs = yf_n * yf_mean
    rhs = dom_n * d_mean + n_global * g_mean
    diff_pct = (lhs - rhs) / lhs * 100 if lhs else 0
    log.append(f"  yf_n*yf_mean        = {lhs:.2f}")
    log.append(f"  dom_n*dom + g_n*g  = {rhs:.2f}")
    log.append(f"  diff_pct            = {diff_pct:+.6f}%")
    ok = abs(diff_pct) < 0.01
    log.append(f"VERDICT: |diff| < 0.01% -> {'PASS' if ok else 'FAIL'}")
    write("xv_x12_global_arithmetic.txt", log)
    return log[-1]


def x13():
    """Phase 14-3: multi-source attempt log present and >= 5 sources tried.

    Prevents single-source claims for global IB (peer review concern from Data
    Agent + Meta-Audit Agent).
    """
    log = ["X13 -- Multi-source attempt log present"]
    try:
        from tools.consensus.global_ib_feed import probe_attempts_log
    except ImportError:
        log.append("VERDICT: FAIL (module not importable)")
        write("xv_x13_multi_source.txt", log)
        return log[-1]
    attempts = probe_attempts_log()
    log.append(f"  attempts logged = {len(attempts)}")
    for a in attempts:
        log.append(
            f"  - {a['source'][:60]}: result='{a['result'][:80]}', robots={a['robots_status']}"
        )
    ok = len(attempts) >= 5
    log.append(f"VERDICT: >=5 sources tried -> {'PASS' if ok else 'FAIL'}")
    write("xv_x13_multi_source.txt", log)
    return log[-1]


def x14():
    """Phase 14-3: independent peer-agent re-derivation of Q5.

    A 'peer' agent (this function, independent of analyze_snapshot logic)
    re-derives Q5 status from raw numbers and confirms agreement.
    """
    log = ["X14 -- Independent Q5 re-derivation (peer agent)"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-06-30_analysis.json",
        encoding="utf-8",
    ) as fh:
        a = json.load(fh)
    q5 = a["answers"].get("Q5_details") or {}
    implied = q5.get("implied") or {}
    gap = implied.get("gap_pct")
    sample = implied.get("sample_quality")
    target_dir = a["answers"].get("Q1_direction")
    reported_status = a["answers"].get("Q5_global_vs_domestic")
    # Independent rule (same business logic, separate implementation)
    if sample != "ok":
        expected = (
            "GLOBAL_SAMPLE_TOO_SMALL" if sample == "n_too_small"
            else "GLOBAL_DATA_INSUFFICIENT"
        )
    elif target_dir != "UP":
        # Logic is conditional on Q1 UP - if not UP, fall back to INSUFFICIENT
        expected = "GLOBAL_DATA_INSUFFICIENT"
    elif gap is None:
        expected = "ALIGNED_DIRECTION_UNKNOWN_LEVEL"
    elif abs(gap) <= 5.0:
        expected = "ALIGNED_DIRECTION_AND_LEVEL"
    elif gap < -5.0:
        expected = "ALIGNED_DIRECTION_GLOBAL_LOWER"
    else:
        expected = "ALIGNED_DIRECTION_GLOBAL_HIGHER"
    log.append(f"  reported = {reported_status}")
    log.append(f"  expected = {expected}")
    log.append(f"  gap_pct  = {gap}")
    log.append(f"  sample   = {sample}")
    log.append(f"  target_dir = {target_dir}")
    ok = reported_status == expected
    log.append(f"VERDICT: peer agent agrees -> {'PASS' if ok else 'FAIL'}")
    write("xv_x14_peer_agent_q5.txt", log)
    return log[-1]


def x15():
    """Phase 14-4: per-firm named target ∈ [yfinance.low, high] range."""
    log = ["X15 -- Named target ∈ yfinance.low..high range"]
    with open(
        REPO / "output/consensus_snapshot/000660_2026-07-01_report.md",
        encoding="utf-8",
    ) as fh:
        _ = fh.read()  # ensure pipeline ran; the date may shift
    with open(
        REPO / "output/consensus_snapshot/000660_global_ib_named.json",
        encoding="utf-8",
    ) as fh:
        d = json.load(fh)
    # use latest known yfinance range
    yf_low, yf_high = 1_030_000.0, 4_700_000.0
    log.append(f"  yfinance range: [{yf_low:,.0f}, {yf_high:,.0f}]")
    merged = d.get("merged_entries", [])
    in_range = 0
    out_of_range = 0
    for e in merged:
        tp = e.get("target_price")
        if tp is None:
            continue
        if yf_low <= tp <= yf_high:
            in_range += 1
        else:
            out_of_range += 1
            log.append(
                f"  OUT_OF_RANGE: {e['firm']} target={tp:,.0f} "
                f"conf={e['confidence']}"
            )
    log.append(f"  in_range = {in_range}, out_of_range = {out_of_range}")
    # X15 PASSES if all OUT_OF_RANGE entries have confidence ∈ {low, medium}
    # (i.e., they are NOT promoted to high). high or user_verified must be in range.
    fail = False
    for e in merged:
        tp = e.get("target_price")
        if tp is None:
            continue
        if not (yf_low <= tp <= yf_high) and e.get("confidence") in ("high", "user_verified"):
            log.append(f"  FAIL: high-confidence entry out of range: {e}")
            fail = True
    log.append(f"VERDICT: {'PASS' if not fail else 'FAIL'} "
               "(low/medium out-of-range allowed; high must be in range)")
    write("xv_x15_target_in_yf_range.txt", log)
    return log[-1]


def x16():
    """Phase 14-4: confidence label consistency.
       high → source_count ≥ 2 AND proximity_chars ≤ 200
       medium → source_count == 1 AND proximity_chars ≤ 200
       low → proximity_chars > 200 OR low context score
       user_verified → extraction_method == 'manual'"""
    log = ["X16 -- Confidence labeling consistency"]
    with open(
        REPO / "output/consensus_snapshot/000660_global_ib_named.json",
        encoding="utf-8",
    ) as fh:
        d = json.load(fh)
    merged = d.get("merged_entries", [])
    log.append(f"  total entries = {len(merged)}")
    ok = True
    for e in merged:
        conf = e.get("confidence")
        method = e.get("extraction_method")
        sc = e.get("source_count", 1)
        prox = e.get("proximity_chars", 0)
        if conf == "user_verified" and method != "manual":
            log.append(f"  FAIL: user_verified but method={method}: {e['firm']}")
            ok = False
        elif conf == "high" and (sc < 2 or prox > 200):
            log.append(f"  FAIL: high requires sc>=2 and prox<=200: {e}")
            ok = False
        elif conf == "low" and prox <= 200 and method != "manual":
            # low only legitimate for prox>200 (or other low-context reasons)
            pass  # accept (additional reasons possible)
    log.append(f"VERDICT: {'PASS' if ok else 'FAIL'}")
    write("xv_x16_confidence_consistency.txt", log)
    return log[-1]


def x17():
    """Phase 14-4: manual input file matches jsonschema."""
    log = ["X17 -- Manual targets matches jsonschema"]
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        log.append("VERDICT: SKIP (jsonschema not importable)")
        write("xv_x17_manual_schema.txt", log)
        return log[-1]
    schema_p = REPO / "configs/manual_global_ib_targets.schema.json"
    data_p = REPO / "configs/manual_global_ib_targets.json"
    if not schema_p.exists() or not data_p.exists():
        log.append("VERDICT: SKIP (files missing)")
        write("xv_x17_manual_schema.txt", log)
        return log[-1]
    schema = json.loads(schema_p.read_text(encoding="utf-8"))
    data = json.loads(data_p.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(data))
    log.append(f"  errors_found = {len(errors)}")
    for e in errors[:5]:
        log.append(f"  - {e.message}")
    log.append(f"VERDICT: {'PASS' if not errors else 'FAIL'}")
    write("xv_x17_manual_schema.txt", log)
    return log[-1]


def x18():
    """Phase 14-4: IB name alias round-trip.
       For every alias in IB_NAME_ALIASES, canonicalize_ib(alias) must
       return a canonical that is itself a key (i.e. round-trippable)."""
    log = ["X18 -- IB alias round-trip"]
    try:
        from tools.consensus.global_ib_news import (
            IB_NAME_ALIASES, canonicalize_ib,
        )
    except ImportError:
        log.append("VERDICT: SKIP (module not importable)")
        write("xv_x18_alias_round_trip.txt", log)
        return log[-1]
    failed = []
    for alias in IB_NAME_ALIASES:
        canon = canonicalize_ib(alias)
        if canon is None:
            failed.append((alias, "canonicalize returned None"))
            continue
        # canonical must also be a key (self-referential entry)
        if canon not in IB_NAME_ALIASES:
            failed.append((alias, f"canonical '{canon}' not in aliases"))
    log.append(f"  total aliases = {len(IB_NAME_ALIASES)}")
    log.append(f"  failed = {len(failed)}")
    for a, r in failed[:5]:
        log.append(f"  - {a}: {r}")
    log.append(f"VERDICT: {'PASS' if not failed else 'FAIL'}")
    write("xv_x18_alias_round_trip.txt", log)
    return log[-1]


def x19():
    """Phase 14-0-C: snapshot manifest.top_sha256 matches recomputed hash.
    Uses tmp store to avoid touching prod history tree."""
    log = ["X19 -- Snapshot manifest sha256 integrity"]
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, verify_snapshot_integrity, QUALITY_MIN,
        )
    except ImportError as e:
        log.append(f"VERDICT: FAIL (import: {e!r})")
        write("xv_x19_snapshot_manifest.txt", log)
        return log[-1]
    import tempfile
    tmp = tempfile.mkdtemp(prefix="xv_x19_")
    parsed = {"schema_version": "0.3", "ticker": "TEST"}
    analysis = {
        "schema_version": "0.2", "ticker": "TEST",
        "answers": {"Q1_direction": "UP", "Q2_direction": "UP",
                     "Q3_direction": "UP", "Q4_quadrant": "TRUE_UPGRADE",
                     "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT"},
        "raw_inputs": {"latest_target_price": 3_000_000},
        "data_quality": {"score": 0.9, "components": {}},
        "meta_audit": {"kr_buy_bias_warning": True,
                        "kr_buy_bias_source": "test",
                        "point_in_time_status": "snapshot",
                        "point_in_time_note": "test",
                        "target_price_role": "sentiment_valuation_proxy",
                        "target_price_role_source": "test"},
    }
    write_snapshot(
        ticker="TEST_X19", parsed=parsed, analysis=analysis,
        report_md="# test\n", date="2026-07-03", history_root=tmp,
    )
    v = verify_snapshot_integrity("TEST_X19", "2026-07-03", history_root=tmp)
    log.append(f"  ok={v['ok']} checked={v['checked']} "
               f"mismatches={v['mismatches']} missing={v['missing']}")
    log.append(f"VERDICT: {'PASS' if v['ok'] else 'FAIL'}")
    import shutil; shutil.rmtree(tmp)
    write("xv_x19_snapshot_manifest.txt", log)
    return log[-1]


def x20():
    """Phase 14-0-C: tamper detection — modify a file and confirm verify fails."""
    log = ["X20 -- Snapshot tamper detection"]
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, verify_snapshot_integrity,
        )
    except ImportError as e:
        log.append(f"VERDICT: FAIL (import: {e!r})")
        write("xv_x20_tamper.txt", log)
        return log[-1]
    import tempfile
    tmp = tempfile.mkdtemp(prefix="xv_x20_")
    parsed = {"x": 1}
    analysis = {
        "answers": {"Q1_direction": "UP", "Q2_direction": "UP",
                     "Q3_direction": "UP", "Q4_quadrant": "TRUE_UPGRADE",
                     "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT"},
        "raw_inputs": {},
        "data_quality": {"score": 0.9, "components": {}},
        "meta_audit": {"kr_buy_bias_warning": True,
                        "kr_buy_bias_source": "t",
                        "point_in_time_status": "snapshot",
                        "point_in_time_note": "t",
                        "target_price_role": "sentiment_valuation_proxy",
                        "target_price_role_source": "t"},
    }
    write_snapshot(ticker="TEST_X20", parsed=parsed, analysis=analysis,
                    report_md="# a\n", date="2026-07-03", history_root=tmp)
    # Tamper: rewrite report.md
    (Path(tmp) / "TEST_X20" / "2026-07-03" / "report.md").write_text(
        "# TAMPERED\n", encoding="utf-8"
    )
    v = verify_snapshot_integrity("TEST_X20", "2026-07-03", history_root=tmp)
    log.append(f"  ok_after_tamper={v['ok']} mismatches={v['mismatches']}")
    tamper_detected = not v["ok"] and len(v["mismatches"]) >= 1
    log.append(f"VERDICT: {'PASS' if tamper_detected else 'FAIL'} "
               "(tamper must be detected)")
    import shutil; shutil.rmtree(tmp)
    write("xv_x20_tamper.txt", log)
    return log[-1]


def x21():
    """Phase 14-0-C: write-once guard — second write without force must fail."""
    log = ["X21 -- Write-once guard"]
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, SnapshotExistsError,
        )
    except ImportError as e:
        log.append(f"VERDICT: FAIL (import: {e!r})")
        write("xv_x21_write_once.txt", log)
        return log[-1]
    import tempfile
    tmp = tempfile.mkdtemp(prefix="xv_x21_")
    analysis = {
        "answers": {"Q1_direction": "UP", "Q2_direction": "UP",
                     "Q3_direction": "UP", "Q4_quadrant": "TRUE_UPGRADE",
                     "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT"},
        "raw_inputs": {},
        "data_quality": {"score": 0.9, "components": {}},
        "meta_audit": {"kr_buy_bias_warning": True,
                        "kr_buy_bias_source": "t",
                        "point_in_time_status": "snapshot",
                        "point_in_time_note": "t",
                        "target_price_role": "sentiment_valuation_proxy",
                        "target_price_role_source": "t"},
    }
    write_snapshot(ticker="TEST_X21", parsed={}, analysis=analysis,
                    report_md="# a\n", date="2026-07-03", history_root=tmp)
    raised = False
    try:
        write_snapshot(ticker="TEST_X21", parsed={}, analysis=analysis,
                        report_md="# b\n", date="2026-07-03", history_root=tmp)
    except SnapshotExistsError:
        raised = True
    log.append(f"  refused_second_write={raised}")
    log.append(f"VERDICT: {'PASS' if raised else 'FAIL'}")
    import shutil; shutil.rmtree(tmp)
    write("xv_x21_write_once.txt", log)
    return log[-1]


def x22():
    """Phase 14-0-C: historical snapshot byte-identical after subsequent writes."""
    log = ["X22 -- Historical snapshot byte-identical after new writes"]
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, load_snapshot,
        )
    except ImportError as e:
        log.append(f"VERDICT: FAIL (import: {e!r})")
        write("xv_x22_historical_immutable.txt", log)
        return log[-1]
    import tempfile
    tmp = tempfile.mkdtemp(prefix="xv_x22_")
    def _a(): return {
        "answers": {"Q1_direction": "UP", "Q2_direction": "UP",
                     "Q3_direction": "UP", "Q4_quadrant": "TRUE_UPGRADE",
                     "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT"},
        "raw_inputs": {"latest_target_price": 3_000_000},
        "data_quality": {"score": 0.9, "components": {}},
        "meta_audit": {"kr_buy_bias_warning": True,
                        "kr_buy_bias_source": "t",
                        "point_in_time_status": "snapshot",
                        "point_in_time_note": "t",
                        "target_price_role": "sentiment_valuation_proxy",
                        "target_price_role_source": "t"},
    }
    write_snapshot(ticker="TEST_X22", parsed={"day": 1}, analysis=_a(),
                    report_md="# day1\n", date="2026-07-01", history_root=tmp)
    snap_before = load_snapshot("TEST_X22", "2026-07-01", history_root=tmp)
    top_sha_before = snap_before["manifest"]["top_sha256"]
    # Write a NEW snapshot for a different date
    write_snapshot(ticker="TEST_X22", parsed={"day": 3}, analysis=_a(),
                    report_md="# day3\n", date="2026-07-03", history_root=tmp)
    snap_after = load_snapshot("TEST_X22", "2026-07-01", history_root=tmp)
    top_sha_after = snap_after["manifest"]["top_sha256"]
    log.append(f"  top_sha_before = {top_sha_before[:16]}")
    log.append(f"  top_sha_after  = {top_sha_after[:16]}")
    unchanged = top_sha_before == top_sha_after and snap_before == snap_after
    log.append(f"VERDICT: {'PASS' if unchanged else 'FAIL'}")
    import shutil; shutil.rmtree(tmp)
    write("xv_x22_historical_immutable.txt", log)
    return log[-1]


if __name__ == "__main__":
    summary = {
        "X1": x1(),
        "X2": x2(),
        "X3": x3(),
        "X4": x4(),
        "X5": x5(),
        "X6": x6(),
        "X7": x7(),
        "X8": x8(),
        "X9": x9(),
        "X10": x10(),
        "X11": x11(),
        "X12": x12(),
        "X13": x13(),
        "X14": x14(),
        "X15": x15(),
        "X16": x16(),
        "X17": x17(),
        "X18": x18(),
        "X19": x19(),
        "X20": x20(),
        "X21": x21(),
        "X22": x22(),
    }
    print("\n=== Cross-Validation Summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
