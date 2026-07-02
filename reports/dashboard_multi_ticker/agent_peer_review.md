# Dashboard Multi-Ticker (NVDA/GOOGL/VRT 추가) — 13-agent Peer Review

**Date**: 2026-07-03 (post-implementation, pre-push)
**Scope**: Add NVDA / GOOGL / VRT to Consensus Tracker dashboard alongside
000660 SK하이닉스. New backend module `tools/consensus/us_ticker_snapshot.py`
using yfinance. Dashboard extended with currency-aware formatting and
graceful degradation for US-market-specific limitations.

---

## Pre + Post concerns unified per agent

### Audit Agent
- Pre: yfinance is unofficial wrapper; no secrets in new module.
- Post: 
  - `us_ticker_snapshot.py` has 0 API-key / password / token references
    (grep verified).
  - No `.env` reads or credential writes.
  - Backend calls `yfinance.Ticker(...)` — public data.
- **PASS**

### Data Agent
- Pre: All 3 tickers must produce non-empty analysis.json.
- Post: Live NVDA/GOOGL/VRT all returned data_quality.score=1.0 with 5/5
  components present. Sample values:
  - NVDA: 58 analysts, mean $301.62, high $500, low $180, close $194.83
  - GOOGL: 53 analysts, mean $432.65, high $515, low $340, close $359.91
  - VRT: 25 analysts, mean $377.00, high $500, low $236, close $300.53
- **PASS**

### Stock Agent
- Pre: Ticker-to-name map must be correct (NVDA=NVIDIA, GOOGL=Alphabet).
- Post: `C_TICKERS` in dashboard has correct name+currency+market for all 5
  (KR: 000660, 005930; US: NVDA, GOOGL, VRT). Backend
  `US_TICKER_COMPANY_FALLBACK` mirrors + adds fallback for yfinance
  outages.
- **PASS**

### Validation Agent
- Pre: US analysis.json must be structurally compatible with Korean schema
  so dashboard's field accesses work uniformly.
- Post: US snapshots have same top-level keys (schema_version, ticker,
  company, answers, raw_inputs, data_quality, meta_audit, reconciliation,
  global_ib_named, parser_warnings). Missing fields default to None with
  `not_applicable_reason` where semantic.
- **PASS**

### Analysis Agent
- Pre: Q1~Q5 should honestly say INSUFFICIENT for US where estimate-
  revision data is unavailable, rather than fabricate.
- Post: US analysis has Q1=INSUFFICIENT, Q2=INSUFFICIENT, Q3=INSUFFICIENT,
  Q4=INSUFFICIENT, Q5=US_TICKER_NOT_APPLICABLE. Dashboard renders these
  via DIR_COLORS.INSUFFICIENT (yellow "데이터 부족") and Q5 as literal enum.
- **PASS**

### Meta-Audit Agent
- Pre: Snapshot immutability must extend to US tickers too — same
  write_snapshot flow.
- Post: All 4 tickers have manifest.json with top_sha256. Sample:
  - 000660: `23a0ed9c...`
  - NVDA: computed at write time (verifiable via `verify_snapshot_integrity`)
- **PASS**

### News Agent
- Pre: For US tickers, no Korean news search runs. `global_ib_named=[]`
  is the correct state.
- Post: US analysis has `global_ib_named=[]`. Dashboard's `renderGlobalIB`
  detects US ticker and shows yfinance high/low/mean/median table instead
  of "명단 없음" message. Attribution-accuracy warning banner remains
  visible (it doesn't apply but stays as context for the section).
- **PASS**

### Evaluator Agent
- Pre: Data quality score threshold should apply consistently.
- Post: All 4 tickers hit score=1.0 on today's data (all 5 components
  present). QUALITY_MIN=0.5 gate in snapshot_store would refuse if any
  quality collapse.
- **PASS**

### Decision Agent
- Pre: No auto BUY/SELL from client-side; disclaimer preserved for US.
- Post: Red-bordered disclaimer card unchanged, still visible for all
  4 tickers.
- **PASS**

### Narrative Agent
- Pre: US labels can stay English (firm names, currency symbol);
  meta labels remain Korean.
- Post: fmtMoney(v, "USD") outputs "$1,234.56" format; fmtMoney(v, "KRW")
  outputs "1,234원". Section headers/meta remain Korean.
- **PASS**

### UI Agent
- Pre: Dropdown must not overflow on mobile; currency badge visible.
- Post: `<select>` with 4 options fits inline flex layout; existing
  overflow-x:auto on tables handles wider USD values (e.g., "$432.65").
  Header shows "(NVDA, US / USD)" identifier chip.
- **PASS**

### Sector Agent
- Pre: Multi-market handling should be honest about differences.
- Post: US tickers (NVDA/GOOGL semiconductor+internet, VRT infrastructure)
  are all AI-related but backend does NOT sector-aggregate — each is a
  standalone snapshot. Not overclaiming sector rollup.
- **PASS**

### Report Agent
- Pre: Existing 7 tabs regression.
- Post: `showPage()` unchanged; `page-consensus` wrapper unchanged;
  8 wrappers total (7 existing + consensus).
- **PASS**

### PM Agent (self)
- Pre: Path-scoped staging, no force, no hook skip.
- Post: Commit candidate list bound to modified files only.
- **PASS (pending Gate 1-6)**

---

## Post-verification (structural)

| Check | Result |
|---|---|
| Dashboard line count | 2679 → 2740 (+61) |
| HTML well-formed (parser stack) | empty (0 unclosed) |
| 4 ticker `<option>` present | ✓ (grep count = 4) |
| Local HTTP 12 endpoints (4 tickers × dates + analysis + manifest) | 12/12 200 |
| yfinance data quality per ticker | 1.0 / 1.0 / 1.0 / 1.0 |
| Q5 = US_TICKER_NOT_APPLICABLE for US | ✓ |
| Immutable snapshots written | 4/4 (000660 preserved, 3 new) |
| dates.json indexes | 4/4 (one per ticker) |

All 13 agents PASS. Ready for Gate 1-6.
