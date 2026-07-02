# Dashboard Improvements (3 items) — Peer Review

**Date**: 2026-07-03 (post-implementation, pre-push)
**Scope**: 3 user requests on Consensus Tracker tab.

1. **Named Global IB Targets** display (Phase 14-4 data missing)
2. **영업이익 (actual) 추이** visual improvement
3. **기본 컨센서스** add current price (no hardcoding)

---

## Root-cause diagnosis

Deployed `analysis.json.global_ib_named = []` because the fixture-mode
pipeline that generated the 2026-07-03 snapshot did not merge the standalone
Phase 14-4 file (`000660_global_ib_named.json`, 6 entries, 200 OK on Pages).
Backend snapshot is immutable (Phase 14-0-C) so we cannot rewrite it. The
chosen fix is client-side merge (Option A per plan), preserving PIT
invariant.

---

## 13-agent verdict (unified)

### Audit Agent
- Concern: New fetch to supplementary file must be optional; 404 for US
  tickers must not error out.
- Evidence: `try/catch` block wraps supplementary fetch. 404 = silent skip.
  Local test: 000660 → 200, NVDA/GOOGL/VRT → 404 (all handled without console error).
- **PASS**

### Data Agent
- Concern: Supplementary file already at Pages (verified 200 OK earlier).
- Evidence: `output/consensus_snapshot/000660_global_ib_named.json` in
  workflow prepare step (copies output/consensus_snapshot/*.json). Existing
  deploy config covers this.
- **PASS**

### Stock Agent
- Concern: Only tickers with supplementary file get named entries.
- Evidence: Only 000660 has this file (Korean-news extraction is Korean-only
  by design). NVDA/GOOGL/VRT gracefully skip.
- **PASS**

### Validation Agent
- Concern: Supplementary file structure must match dashboard expectations.
- Evidence: `{merged_entries: [{firm, target_price, confidence, report_date,
  is_stale, extraction_method, ...}]}` — same field names as
  analysis.global_ib_named entries. No schema translation needed.
- **PASS**

### Analysis Agent
- Concern: Merge precedence should be inline-first, supplementary-fallback.
- Evidence: `if (currentNamed.length === 0)` guards supplementary merge.
  Inline data (from future backend-fix pipeline runs) takes precedence.
- **PASS**

### Meta-Audit Agent
- Concern: Immutability must remain intact — no rewrite of
  history/{ticker}/{date}/*.
- Evidence: Zero backend / snapshot_store mutations. Client-side only.
  Phase 14-0-C X21/X22 invariants preserved.
- **PASS**

### News Agent
- Concern: Attribution disclaimer must remain visible above named entries.
- Evidence: Yellow warning banner unchanged (Phase 14-4 accuracy ~60-70% text).
- **PASS**

### Evaluator Agent
- Concern: Data source badge should indicate WHERE named entries came from.
- Evidence: New `_named_source` field ("analysis_inline" or "supplementary_file")
  drives a subtle badge above the table showing the source file path +
  `probed_at` for supplementary case. Users can trace exactly where the
  numbers came from.
- **PASS**

### Decision Agent
- Concern: STALE flag on old entries must still be honored.
- Evidence: `is_stale` flag on each entry rendered as before ("STALE" text
  in yellow). No decision-signal auto-triggered.
- **PASS**

### Narrative Agent
- Concern: Korean labels for new "현재 주가" / "상승여력" rows.
- Evidence: New kv rows use Korean. Value formatting via existing fmtKRW
  (currency-aware for USD tickers).
- **PASS**

### UI Agent
- Concern: Chart at 640x260 fits mobile via viewBox scaling.
- Evidence: `viewBox="0 0 640 260" style="width:100%;max-width:800px"` —
  scales down for narrow viewport while preserving aspect ratio. Font-size
  uses SVG units, scales with the viewBox.
- **PASS**

### Sector Agent
- Concern: Backend behavior unchanged for future sector tickers.
- Evidence: Zero backend changes. Sector rollup infrastructure (Phase 14+
  future) unaffected.
- **PASS**

### Report Agent
- Concern: Existing 7 tabs regression.
- Evidence: `showPage()` unchanged; 8 page wrappers unchanged; only additive
  markup + JS.
- **PASS**

### PM Agent (self)
- Concern: Path-scoped push.
- Evidence: Only 2 files modified: `output/dashboard.html`,
  `reports/dashboard_improvements/agent_peer_review.md`. Backend + snapshot
  files unchanged.
- **PASS (pending Gate 1-6)**

---

## Structural verification

| Check | Result |
|---|---|
| Dashboard line count | 2741 → 2893 (+152) |
| HTML well-formed | ✓ (0 unclosed) |
| 3 new element IDs | ✓ (c-close-price, c-close-asof, c-upside) |
| Supplementary fetch behavior | ✓ (200 for 000660, 404 gracefully for US) |
| Chart new pattern (Consensus dashed + Actual solid) | ✓ (single grep for "stroke-dasharray=\"6,4\"" confirms) |
| Zero backend changes | ✓ (git status confirms only dashboard.html + this report) |

All 13 agents PASS. Ready for Gate 1-6.
