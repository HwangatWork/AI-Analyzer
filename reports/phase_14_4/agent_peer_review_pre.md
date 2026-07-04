# Phase 14-4 Pre-implementation Peer Review

**Date**: 2026-07-01
**Goal**: Extract per-firm global IB targets (JPM/GS/MS etc.) for SK hynix via
Korean news search (Path A) + manual input fallback (Path B).
**Trigger**: Phase 14-3 only tried financial data pages; news channels were
prematurely dismissed after one Google News robots block.

Each agent registers a concern. PM resolves below.

---

## Per-agent pre-concerns

### Audit Agent
- Concern: News sites change robots policy frequently. Single audit at phase
  start is insufficient; must re-check robots immediately before each fetch.
- Required: defensive inline robots re-check in `search_news` and
  `fetch_and_extract_targets`.

### Data Agent
- Concern: Search result pages and article pages have different robots rules
  even within the same domain. Yahoo Finance had this exact case (HTML page
  allowed, backend API denied).
- Required: probe BOTH the search URL pattern AND a sample article URL per
  source before adding to KOREAN_NEWS_SOURCES.

### News Agent (self-critical — its own RSS-only approach is being extended)
- Concern: `_fetch_article_text()` in `run_news_agent.py:206` was designed for
  English Google News. It strips `<script>/<style>` but may miss Korean
  encoding nuances (EUC-KR fallback) and Korean article structure (Naver news
  uses different DOM).
- Required: encoding detection identical to `smoke_fetch._detect_encoding`;
  test with at least 1 EUC-KR fixture.

### Validation Agent
- Concern: Regex `목표(주)?가...(\d{1,3}(?:[,.]?\d{3})*)원` is greedy and may
  capture stock PRICE near "주가" not TARGET PRICE. Need to anchor on
  "목표주가" specifically and reject if matched fragment is too far from
  IB name in the text (>200 chars away).
- Required: extraction returns a `proximity_chars` field; entries with
  proximity > 200 are demoted to confidence "low".

### Stock Agent
- Concern: News may mention "SK하이닉스" but actually be about a SUBSIDIARY
  or competitor. Ambiguity check: the IB+ticker must co-occur in the same
  article paragraph.
- Required: paragraph-level scoping when extracting evidence_phrase.

### Analysis Agent
- Concern: One JPM and one GS data point gives N=2, which is the minimum
  threshold. If only JPM is found (N=1), should NOT auto-trigger
  ALIGNED_BY_NAMED_GLOBAL_IB; fall back to existing INSUFFICIENT_PARTIAL.
- Required: enum value GLOBAL_NAMED_PARTIAL when N=1.

### Meta-Audit Agent
- Concern: Re-quotes of OLD reports inflate confidence. If 5 articles all
  cite the same JPM 2025-12-15 target, that's still N=1 unique event.
- Required: dedupe by (firm, target_price, report_date) before counting
  sources for confidence.

### Evaluator Agent
- Concern: Confidence labels ("high"/"medium"/"low"/"user_verified") need
  clear, testable thresholds — not subjective.
- Required: documented mapping table in module docstring.

### Decision Agent
- Concern: News-derived signals must NOT override direct broker data when
  they conflict. Manual input should be the tiebreaker.
- Required: precedence rule: manual_input > yfinance > news_extraction.

### Narrative Agent
- Concern: Report must explicitly tag the source of each global IB entry so
  reader knows what to trust.
- Required: each row in "Named Global IB Targets" table has a `[source]`
  column showing `manual/news/yfinance_aggregate`.

### UI Agent
- Concern: Multiple firms with different report_dates need sorting and
  freshness indicator (e.g., bold latest).
- Required: sort by report_date desc; mark entries older than 60 days as
  STALE.

### Sector Agent
- Concern: 반도체 specific — global IBs cover SK hynix heavily but other
  KOSPI sectors will have near-zero coverage. Don't promise generalization.
- Required: docstring warning: this phase is validated only on
  semiconductor sector tickers.

### Report Agent
- Concern: New section must not break existing report consumers. Phase 14-3
  "글로벌 IB 집계" section should stay; new "Named Global IB Targets" section
  is additive.
- Required: render only when per_firm_named is non-empty.

### PM Agent (self)
- Concern: After Phase 14-3 RCA (target price mis-extraction), trust in
  cross-validation must be rebuilt with arithmetic anchors. New X-tests
  X15-X18 must include at least one external anchor (X15: target in yfinance
  range).

---

## PM Resolution

| Concern | Resolution |
|---|---|
| Robots mid-flight changes | Inline re-check in search_news + fetch_and_extract_targets |
| Search vs article robots | Probe both URL types per source |
| Korean encoding | Reuse `_detect_encoding` from smoke_fetch; EUC-KR fixture |
| Regex over-capture | proximity_chars field + 200-char cap |
| Subsidiary ambiguity | Paragraph-level scoping |
| N=1 case | GLOBAL_NAMED_PARTIAL enum |
| Re-quote dedupe | (firm, target_price, report_date) triple |
| Confidence threshold | Documented table in module docstring |
| Source precedence | manual > yfinance > news |
| Source tagging in report | [source] column |
| Freshness | sort desc, STALE flag for >60d |
| Sector scope | Docstring warning |
| Additive section | Render only when non-empty |
| External anchor | X15 enforces target ∈ yfinance range |

Implementation may proceed.
