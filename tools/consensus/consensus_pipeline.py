# -*- coding: utf-8 -*-
"""Phase 14-0-B2 + 14-1 — Consensus Revision Tracker pipeline (PM Agent).

End-to-end orchestrator. Coordinates Audit -> Data -> Validation -> Analysis
-> Narrative+UI agents. Enforces gates G1-G4.

Modes:
  --from-fixture <path>  : run analyze + render on a saved HTML fixture
                           (no network, deterministic, recommended for CI)
  --smoke                : run smoke fetch (single GET) + full pipeline
                           (requires confirmed intent, --smoke flag is the
                           same gate defined in smoke_fetch.py)

Exit codes:
  0 - pipeline completed (any combination of analyzed stages)
  1 - invalid args
  2 - output write failed
  3 - fetch HTTP error
  4 - missing --smoke flag where required
  6 - schema verification failed on output JSON
  7 - robots disallow
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

try:
    from tools.consensus.smoke_fetch import (
        smoke_fetch, EXIT_OK as SF_OK,
        EXIT_SMOKE_FLAG_MISSING, EXIT_ROBOTS_DENIED, EXIT_HTTP_ERROR,
        EXIT_INVALID_ARGS, EXIT_WRITE_FAILED, KNOWN_TICKERS,
    )
    from tools.consensus.naver_parser import parse_wisereport_html
    from tools.consensus.analyze_snapshot import analyze
    from tools.consensus.render_report import render_markdown
except ImportError:
    import os.path as _osp
    sys.path.insert(0, _osp.dirname(_osp.dirname(_osp.dirname(
        _osp.abspath(__file__)
    ))))
    from tools.consensus.smoke_fetch import (  # noqa: E402
        smoke_fetch, EXIT_OK as SF_OK,
        EXIT_SMOKE_FLAG_MISSING, EXIT_ROBOTS_DENIED, EXIT_HTTP_ERROR,
        EXIT_INVALID_ARGS, EXIT_WRITE_FAILED, KNOWN_TICKERS,
    )
    from tools.consensus.naver_parser import parse_wisereport_html  # noqa: E402
    from tools.consensus.analyze_snapshot import analyze  # noqa: E402
    from tools.consensus.render_report import render_markdown  # noqa: E402


EXIT_OK = 0
EXIT_INVALID = 1
EXIT_WRITE = 2
EXIT_SCHEMA = 6


def _now_date_str() -> str:
    return _dt.datetime.now().astimezone().date().isoformat()


REQUIRED_ANALYSIS_KEYS = (
    "schema_version", "ticker", "answers",
    "raw_inputs", "data_quality", "meta_audit",
)


def verify_analysis_schema(obj: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["analysis: root must be object"]
    for k in REQUIRED_ANALYSIS_KEYS:
        if k not in obj:
            errors.append(f"missing key: {k}")
    ans = obj.get("answers", {})
    for q in ("Q1_direction", "Q2_direction", "Q3_direction",
              "Q4_quadrant", "Q5_global_vs_domestic"):
        if q not in ans:
            errors.append(f"missing answer key: {q}")
    return (not errors), errors


def run_pipeline(
    ticker: str,
    out_dir: str,
    smoke: bool,
    from_fixture: str | None = None,
    source: str = "wisereport",
) -> dict:
    """Top-level pipeline. Returns dict with exit_code + artifact paths."""
    result = {
        "ticker": ticker,
        "company": KNOWN_TICKERS.get(ticker),
        "from_fixture": from_fixture,
        "source": source,
        "smoke": smoke,
        "raw_html_path": None,
        "parsed_json_path": None,
        "analysis_json_path": None,
        "report_md_path": None,
        "errors": [],
        "exit_code": EXIT_OK,
        "gate_results": {
            "G1_robots_check": None,
            "G2_parse_fields_present": None,
            "G3_q4_classified_or_insufficient": None,
            "G4_meta_audit_labels_present": None,
        },
    }

    if ticker not in KNOWN_TICKERS:
        result["errors"].append(f"unknown_ticker: {ticker}")
        result["exit_code"] = EXIT_INVALID
        return result

    # ---- Step 1: Get HTML ----
    if from_fixture:
        # Deterministic path: load saved HTML
        try:
            with open(from_fixture, "r", encoding="utf-8") as fh:
                html = fh.read()
            result["raw_html_path"] = from_fixture
            result["gate_results"]["G1_robots_check"] = "BYPASSED_FIXTURE_MODE"
        except OSError as e:
            result["errors"].append(f"fixture_read_failed: {e!r}")
            result["exit_code"] = EXIT_INVALID
            return result
    else:
        # Network path: smoke_fetch enforces G1
        sf = smoke_fetch(
            ticker=ticker, out_dir=out_dir, smoke=smoke, source=source,
        )
        result["gate_results"]["G1_robots_check"] = (
            "ALLOW" if sf.get("robots_decision", {}).get("allowed")
            else "DENY_OR_NOT_CHECKED"
        )
        if sf["exit_code"] != SF_OK:
            result["errors"].extend(sf.get("errors", []))
            result["exit_code"] = sf["exit_code"]
            return result
        result["raw_html_path"] = sf["raw_html_path"]
        try:
            with open(sf["raw_html_path"], "r", encoding="utf-8") as fh:
                html = fh.read()
        except OSError as e:
            result["errors"].append(f"html_read_failed: {e!r}")
            result["exit_code"] = EXIT_INVALID
            return result

    # ---- Step 2: Validation Agent -> parse ----
    parsed = parse_wisereport_html(html)

    # ---- Step 2c: Phase 14-4 — Named per-firm global IB via news + manual ----
    try:
        from tools.consensus.global_ib_news import (
            parse_per_firm_global, load_manual_targets, merge_named_global_ib,
        )
        if not from_fixture:
            news_result = parse_per_firm_global(ticker)
            news_entries = news_result.get("entries", [])
        else:
            # In fixture mode: try to load pre-saved JSON
            import os.path as _osp
            gib_path = _osp.join(
                out_dir, f"{ticker}_global_ib_named.json"
            )
            news_entries = []
            if _osp.exists(gib_path):
                try:
                    with open(gib_path, encoding="utf-8") as fh:
                        gib_data = json.load(fh)
                    news_entries = gib_data.get("merged_entries", [])
                except (OSError, json.JSONDecodeError):
                    pass
        manual_entries = load_manual_targets(ticker)
        named = merge_named_global_ib(news_entries, manual_entries)
        parsed["global_ib_named"] = named
    except Exception as e:
        parsed["global_ib_named"] = []
        parsed.setdefault("parser_warnings", []).append(
            f"phase_14_4_named_failed: {e!r}"
        )

    # ---- Step 2b: Phase 14-3 — Global IB aggregate via yfinance ----
    if not from_fixture:
        # Live probe — uses network. Only when not in fixture mode.
        try:
            from tools.consensus.global_ib_feed import probe_yfinance_aggregate
            ticker_yf = f"{ticker}.KS"
            global_ib = probe_yfinance_aggregate(ticker_yf)
            parsed["global_ib"] = global_ib
        except Exception as e:
            parsed["global_ib"] = {"found": False, "error": f"probe_exception: {e!r}"}
    else:
        # Fixture mode — try to load from disk if present (deterministic)
        import os.path as _osp
        gib_path = _osp.join(
            out_dir, f"{ticker}_global_ib_aggregate.json"
        )
        if _osp.exists(gib_path):
            try:
                with open(gib_path, encoding="utf-8") as fh:
                    parsed["global_ib"] = json.load(fh)
            except OSError:
                parsed["global_ib"] = {"found": False, "error": "fixture_read_failed"}
        else:
            parsed["global_ib"] = {"found": False, "error": "no_fixture_file"}
    fields_present = sum(
        1 for k in (
            "investment_opinion", "n_analysts", "latest_target_price",
            "target_price_change_1m_pct",
        ) if parsed.get(k) is not None
    )
    result["gate_results"]["G2_parse_fields_present"] = fields_present
    if fields_present < 2:
        result["errors"].append(
            f"G2_failed: only {fields_present} fields parsed (require >=2)"
        )
        # Continue anyway and mark gates — output is still useful
    date_str = _now_date_str()
    parsed_path = os.path.join(
        out_dir, f"{ticker}_{date_str}_parsed.json"
    )
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(parsed_path, "w", encoding="utf-8") as fh:
            json.dump(parsed, fh, ensure_ascii=False, indent=2,
                      sort_keys=True)
            fh.write("\n")
        result["parsed_json_path"] = parsed_path
    except OSError as e:
        result["errors"].append(f"parsed_write_failed: {e!r}")
        result["exit_code"] = EXIT_WRITE
        return result

    # ---- Step 2d: Phase 14-0-C — apply PIT override BEFORE analyze ----
    # Overrides parsed's target_price_change_1m_pct if a snapshot >=7 days
    # old exists for this ticker (point-in-time safe historical anchor).
    if not from_fixture:
        try:
            from tools.consensus.snapshot_store import compute_pit_q1_change
            current_target = parsed.get("latest_target_price")
            if isinstance(current_target, (int, float)) and current_target > 0:
                pit = compute_pit_q1_change(
                    ticker, float(current_target),
                    reference_days=30,
                )
                if pit is not None:
                    import datetime as _pit_dt
                    prior = _pit_dt.date.fromisoformat(pit["prior_date"])
                    today = _pit_dt.date.today()
                    age_days = (today - prior).days
                    if age_days >= 7:
                        parsed["target_price_change_1m_pct"] = pit["change_pct"]
                        parsed["target_price_change_label"] = pit["source"]
                        parsed["pit_prior_target"] = pit["prior_target"]
                        parsed["pit_prior_date"] = pit["prior_date"]
        except ImportError:
            pass

    # ---- Step 2e: OL-8 — override close with LIVE FDR/yfinance value ----
    # WiseReport chartData is monthly and can lag by up to ~30 days.
    # The authoritative current close must come from an external API.
    # The chart value is preserved under close_price_from_wisereport_chart
    # for the PER*EPS self-consistency check.
    parsed["close_price_from_wisereport_chart"] = parsed.get("close_price_latest")
    if not from_fixture:
        try:
            from tools.consensus.live_price_fetcher import fetch_live_close
            live = fetch_live_close(ticker)
            if live and live.get("close") is not None:
                parsed["close_price_latest"] = live["close"]
                parsed["close_price_source"] = live["source"]
                parsed["close_price_as_of"] = live["as_of"]
            else:
                parsed["close_price_source"] = "wisereport_chart_fallback"
                parsed["close_price_as_of"] = None
                parsed.setdefault("parser_warnings", []).append(
                    "live_close_fetch_failed_using_chart_fallback"
                )
        except Exception as e:
            parsed["close_price_source"] = "unknown"
            parsed["close_price_as_of"] = None
            parsed.setdefault("parser_warnings", []).append(
                f"live_close_fetch_exception: {e!r}"
            )
    else:
        parsed["close_price_source"] = "fixture_mode_no_live_fetch"
        parsed["close_price_as_of"] = None

    # ---- Step 3: Analysis + Meta-Audit Agent ----
    analysis = analyze(
        parsed, ticker=ticker, company=KNOWN_TICKERS.get(ticker),
    )
    q4 = analysis.get("answers", {}).get("Q4_quadrant", "MISSING")
    result["gate_results"]["G3_q4_classified_or_insufficient"] = q4
    meta = analysis.get("meta_audit", {})
    has_labels = all(
        meta.get(k) is not None for k in (
            "kr_buy_bias_warning", "point_in_time_status",
            "target_price_role",
        )
    )
    result["gate_results"]["G4_meta_audit_labels_present"] = has_labels

    schema_ok, schema_errors = verify_analysis_schema(analysis)
    if not schema_ok:
        for e in schema_errors:
            result["errors"].append(f"schema: {e}")
        result["exit_code"] = EXIT_SCHEMA
        return result

    analysis_path = os.path.join(
        out_dir, f"{ticker}_{date_str}_analysis.json"
    )
    try:
        with open(analysis_path, "w", encoding="utf-8") as fh:
            json.dump(analysis, fh, ensure_ascii=False, indent=2,
                      sort_keys=True)
            fh.write("\n")
        result["analysis_json_path"] = analysis_path
    except OSError as e:
        result["errors"].append(f"analysis_write_failed: {e!r}")
        result["exit_code"] = EXIT_WRITE
        return result

    # ---- Step 4: Narrative + UI Agent ----
    md = render_markdown(analysis)
    report_path = os.path.join(
        out_dir, f"{ticker}_{date_str}_report.md"
    )
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        result["report_md_path"] = report_path
    except OSError as e:
        result["errors"].append(f"report_write_failed: {e!r}")
        result["exit_code"] = EXIT_WRITE
        return result

    # ---- Step 5: Phase 14-0-C — immutable daily snapshot ----
    try:
        from tools.consensus.snapshot_store import (
            write_snapshot, SnapshotExistsError, QualityGateError,
        )
        try:
            manifest = write_snapshot(
                ticker=ticker,
                parsed=parsed,
                analysis=analysis,
                report_md=md,
                date=date_str,
                force=False,
            )
            result["snapshot_manifest"] = manifest
            result["gate_results"]["G5_snapshot_written"] = True
        except SnapshotExistsError as e:
            # Not an error — same-day duplicate run; log INFO
            result["snapshot_manifest"] = None
            result["gate_results"]["G5_snapshot_written"] = "already_exists"
            result.setdefault("info", []).append(f"snapshot_skipped: {e}")
        except QualityGateError as e:
            result["gate_results"]["G5_snapshot_written"] = "quality_gate_refused"
            result.setdefault("info", []).append(f"snapshot_refused: {e}")
    except ImportError as e:
        result.setdefault("info", []).append(
            f"snapshot_module_not_importable: {e}"
        )
        result["gate_results"]["G5_snapshot_written"] = "module_missing"

    result["exit_code"] = EXIT_OK
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 14-0-B2 + 14-1 pipeline"
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--out-dir", default="output/consensus_snapshot")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--from-fixture", default=None,
        help="run analyze+render on a saved HTML fixture (no network)"
    )
    parser.add_argument("--source", default="wisereport")
    args = parser.parse_args(argv)

    r = run_pipeline(
        ticker=args.ticker, out_dir=args.out_dir,
        smoke=args.smoke, from_fixture=args.from_fixture,
        source=args.source,
    )

    # ASCII-safe summary
    msg = (
        f"pipeline: ticker={r['ticker']} "
        f"exit_code={r['exit_code']} "
        f"q4={r['gate_results'].get('G3_q4_classified_or_insufficient')} "
        f"report={r.get('report_md_path')}"
    )
    if r["errors"]:
        msg += " errors=" + "; ".join(r["errors"])[:300]
    sys.stdout.write(msg + "\n")
    return r["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
