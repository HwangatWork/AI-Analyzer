# Consensus Tracker Accuracy Framework

**Established**: 2026-07-04 after user-requested audit revealed that
`raw_inputs.close_price_latest` in the SK hynix snapshot was 7.7% stale vs
FDR/yfinance live data.

## Design principles

1. **NO hardcoded ticker values in code.** All numerics must originate
   from a fetch (yfinance / FDR / WiseReport / user manual input) with
   the source recorded. Regression test
   `test_registry_no_hardcoded_numeric_values` enforces this on the
   ticker registry.
2. **Verify before improve.** Any UI or UX change is preceded by
   `scripts/consensus_accuracy_daily.py` execution and a review of the
   resulting audit matrix.
3. **Self-improvement loop.** Daily re-fetch → diff vs snapshot →
   pending_requests entry when |diff| exceeds threshold → 3-day
   consecutive persistence → memory lesson candidate.

## Data flow

```
┌───────────────────┐   daily   ┌──────────────────────────────┐
│ FDR (KRX)         │──────────▶│                              │
├───────────────────┤           │ consensus_accuracy_daily.py   │
│ yfinance (US+KR)  │──────────▶│                              │
└───────────────────┘           │  1. fetch live close         │
                                │  2. read latest snapshot     │
                                │  3. compute diff %           │
                                │  4. streak counter           │
                                │  5. threshold check          │
                                └──┬───────────────┬───────────┘
                                   │               │
                                   ▼               ▼
                    ┌─────────────────────┐   ┌──────────────────────┐
                    │ live_prices.json    │   │ pending_requests.json│
                    │ (dashboard-consumed)│   │ (streaks >= threshold)│
                    └─────────────────────┘   └──────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │ dashboard.html (consensus tracker)  │
                    │  - fetch analysis.json (snapshot)   │
                    │  - fetch live_prices.json (fresh)   │
                    │  - overlay LIVE close on UI         │
                    │  - recalc upside% with live basis   │
                    │  - stale badge if snapshot > 2% off │
                    └─────────────────────────────────────┘
```

## Files

- `scripts/consensus_accuracy_daily.py` — daily fetch + audit runner
- `output/consensus_snapshot/live_prices.json` — dashboard-consumed daily
  live prices (schema: `{generated_at, generator, prices: {ticker: {close,
  currency, as_of, source, market, name}}}`)
- `output/consensus_snapshot/_accuracy_state.json` — internal streak
  counter, not exposed to dashboard
- `output/dashboard.html` — `renderBasicConsensus(analysis, livePrice)`
  overlays live over snapshot
- `tests/consensus/test_accuracy_daily.py` — 10 regression tests

## Ticker registry

```python
TICKER_REGISTRY = {
    "000660": {"market": "KR", "fdr_symbol": "000660", "yf_symbol": "000660.KS", ...},
    "NVDA":   {"market": "US", "fdr_symbol": None, "yf_symbol": "NVDA", ...},
    ...
}
```

Registry keys/values are **identity + fetch strategy only** — never
numeric ticker values. Test enforces this.

## Thresholds

- `STALE_THRESHOLD_PCT = 5.0` — diff exceeding this triggers pending
- `CONSECUTIVE_DAYS_FOR_LESSON = 3` — streak triggers lesson candidate

Values are documented as module constants; both are configurable via CLI
flag.

## Usage

```bash
# Dry-run summary
python scripts/consensus_accuracy_daily.py

# Persist live_prices.json + pending_requests
python scripts/consensus_accuracy_daily.py --write

# Subset of tickers
python scripts/consensus_accuracy_daily.py --write --tickers 000660,NVDA

# Custom threshold
python scripts/consensus_accuracy_daily.py --write --threshold-pct 3.0
```

## Self-improvement loop (Phase D)

1. **Daily execution**: cron or workflow schedule invokes with `--write`.
2. **Streak accumulation**: `_accuracy_state.json` tracks per-ticker
   consecutive stale days.
3. **Pending registration**: On stale day, appends to
   `pending_requests.json` with ticker + diff + note.
4. **Lesson candidate**: On streak >= 3, prints candidate line (future:
   auto-invoke `memory_lesson_save` via AgentMemory MCP).
5. **Next session recall**: Claude session start routine reads
   `pending_requests.json` and may invoke
   `memory_smart_search("consensus accuracy")` to load past lessons.

The loop closes autonomously: user doesn't need to notice stale data;
system does.

## Verification (Level 10)

- Live command execution: `python scripts/consensus_accuracy_daily.py --write`
- Raw exit codes / logs: `reports/accuracy_audit_YYYY-MM-DD/`
- Edge cases: yfinance import fail / FDR empty / snapshot missing /
  ticker not in registry — all handled without crash
- Simulation: `test_read_snapshot_close_uses_latest_history` with fake
  history tree
- Regression: 10 pytest tests
- Documentation: this file

## Post-audit findings (2026-07-04)

| Ticker | Live close | Snapshot close | Diff | Action |
|---|---|---|---|---|
| 000660 | 2,425,000 (FDR) | 2,628,000 (WiseReport 2026-07-03 snapshot) | +8.37% STALE | pending appended, dashboard will show LIVE badge |
| NVDA | 194.83 (yfinance) | 194.83 | 0% | OK |
| GOOGL | 359.91 (yfinance) | 359.91 | 0% | OK |
| VRT | 300.53 (yfinance) | 300.53 | 0% | OK |

Root cause of 000660 gap: WiseReport chart's `close_price` field lags
KRX official close by 5+ trading days (chart data is historical monthly).
Live overlay resolves the display issue; the snapshot itself remains
immutable per Phase 14-0-C invariant.
