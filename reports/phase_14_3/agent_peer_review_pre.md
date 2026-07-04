# Phase 14-3 Pre-implementation Peer Review (13 agents)

**Date**: 2026-06-30
**Phase goal**: Add global IB (JPM, Goldman Sachs, MS, BofA) target prices for
SK hynix (000660) to address user's outstanding Q5 GLOBAL_DATA_INSUFFICIENT.

Each agent registers a concern/question BEFORE code is written. PM aggregates
and resolves below.

---

## Pre-implementation concerns by agent

### Audit Agent
- Concern: Most candidate sources (Bloomberg, Reuters, FactSet) are paid-API
  with strict ToS. **Free public sources** are limited to news aggregators and
  Yahoo/Finnhub free tiers. robots.txt for each must be checked LIVE before
  fetch.
- Required gate: NO fetch on any URL until robots.txt is fetched and parsed.

### Data Agent
- Concern: Korean stocks (000660) typically have **sparse global IB coverage**
  in free sources. yfinance `000660.KS` may return empty for `recommendations`
  or `upgrades_downgrades`. Finnhub free tier has very limited non-US ticker
  coverage.
- Required: probe MULTIPLE sources before claiming "no data". Document each
  attempt with status + bytes + visible-firm-list.

### Stock Agent
- Concern: Ticker mapping varies across sources:
  - Naver / KOSPI: 000660
  - yfinance / Yahoo: 000660.KS
  - ADR / OTC: HXSCL or HXSCY
  - Bloomberg: 000660 KS Equity
- Required: ticker normalization map; never silently swap one for another.

### Validation Agent
- Concern: Different sources report target prices in different units
  (KRW per share, USD per ADR, USD per local share equivalent). Must capture
  currency + unit; never aggregate cross-currency without explicit conversion.

### Analysis Agent
- Concern: Q5 (global vs domestic) requires **comparable methodology** -
  same forecast horizon, same fiscal year basis. If global IB targets are
  ADR-based USD targets, naive comparison against KRW domestic targets
  produces false signals.
- Required: only label Q5 as resolved (not INSUFFICIENT) when at least
  2 global IB entries are KRW-denominated for 000660 directly.

### Meta-Audit Agent
- Concern: Easy to claim "found 1 JPM mention" but the mention might be
  outdated, a re-quote of an older report, or about a different metric.
  Need EVIDENCE_PHRASE (verbatim quote) per global IB entry so a human can
  verify.
- Required: schema includes `source_url`, `evidence_phrase`, `report_date`
  per global IB entry. INSUFFICIENT is preferred to false-positive.

### News Agent
- Concern: Google News RSS can surface global IB headlines but the headline
  itself rarely contains the numeric target (just "JPM raises SK hynix").
  Full article body may be paywall. RSS is a discovery layer, not a value
  extractor.
- Required: treat news as "discovery only"; numeric extraction requires
  article body access OR explicit confirmation from another source.

### Evaluator Agent
- Concern: Data quality score must reflect coverage breadth. If only 1 global
  IB found vs Phase 14-1-B's 25 domestic brokers, Q5 confidence is structurally
  low and must be flagged.

### Decision Agent
- Concern: Adding sparse global data could mislead future BUY/SELL logic if
  Q5 says "ALIGNED" based on N=1 sample. Decision Agent will refuse to act on
  Q5 until N >= 2 distinct global IBs.

### Narrative Agent
- Concern: User originally asked for "J.P. Morgan, Goldman Sachs" by name.
  If we cannot find them, the report must say so EXPLICITLY rather than
  glossing with "GLOBAL_DATA_INSUFFICIENT".
- Required: render a "Global IB attempt log" section listing each source
  probed and the result.

### UI Agent
- Concern: Per-region table (Korea vs Global) needs visual separation, not a
  single sorted list, so the user can see the divide.

### Sector Agent
- Concern: 반도체 sector has known higher global IB coverage than other
  Korean sectors. If we test on a different sector ticker, results may be
  even more sparse - this phase should NOT extrapolate.

### Report Agent
- Concern: Final report path must remain `output/consensus_snapshot/000660_*.md`
  for downstream pipeline compatibility. No new directories unless documented.

### PM Agent (me, integrating)
- Concern: After 9 rounds of meta-critique earlier, this phase risks LLM-only
  speculation. Must execute live and capture raw outputs (not just claim).

---

## PM Resolution (pre-implementation)

| Concern | Resolution |
|---|---|
| Audit robots.txt | Use existing `tools/consensus/robots_check.py`; probe 5 candidates |
| Sparse data probability | Treat sparseness as a legitimate finding, document each attempt |
| Ticker normalization | Build `TICKER_ALIASES` map; pass per-source variant |
| Currency / unit | Add `currency` and `unit_per_share` fields to schema |
| Q5 false-positive | Require N >= 2 distinct global IBs before changing Q5 from INSUFFICIENT |
| Evidence phrase | Schema mandates `evidence_phrase` for every global IB entry |
| News-as-value | News pipeline marks `confidence = "discovery_only"`; numeric needs corroboration |
| Decision Agent veto | Q5 = "ALIGNED" or "DIVERGED" only when N >= 2; else INSUFFICIENT |
| Honest narrative | New section "Global IB attempt log" appears in report regardless of result |
| Live execution | Every external request goes through smoke_fetch / robots_check; outputs saved |

Code may now proceed. Post-implementation peer review will be in
`agent_peer_review_post.md` after live execution.
