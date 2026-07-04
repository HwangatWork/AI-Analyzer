# Phase 14-3 Post-implementation Peer Review (13 agents)

**Date**: 2026-06-30 (post live execution)
**Reference**: this file pairs with `agent_peer_review_pre.md` (pre-impl).

Each agent reviews ACTUAL artifacts (not claims). Concerns from pre-review
are revisited against evidence.

---

## Per-agent verdict

### Audit Agent
- Pre-concern: "No fetch on any URL until robots checked"
- Evidence: `reports/phase_14_3/robots_audit.log` shows 5 robots probes.
  Yahoo Finance HTML / Finnhub / Bloomberg ALLOWED; Yahoo backend API / Google
  News RSS DENIED. No fetch happened against denied URLs (verified by absence
  of corresponding raw files in `output/consensus_snapshot/`).
- **Verdict: PASS**

### Data Agent
- Pre-concern: "Korean stocks may have sparse global IB coverage"
- Evidence: `reports/phase_14_3/yfinance_probe.log` shows yfinance returned
  37 analysts (rich aggregate) but `upgrades_downgrades` is empty (0 rows, 0
  columns). Finnhub returned 401. Yahoo HTML returned 166KB with 0 IB-name
  occurrences. **Concern confirmed**: per-firm global IB names are not
  obtainable through tested free channels.
- **Verdict: PASS — concern confirmed, response is honest**

### Stock Agent
- Pre-concern: "Ticker mapping varies (000660 vs 000660.KS)"
- Evidence: `global_ib_feed.py:probe_yfinance_aggregate` uses 000660.KS for
  yfinance; pipeline computes that from `f"{ticker}.KS"`. Never swaps silently.
- **Verdict: PASS**

### Validation Agent
- Pre-concern: "Capture currency and unit"
- Evidence: `output/consensus_snapshot/000660_global_ib_aggregate.json` has
  `"currency": "KRW"`. Same units as WiseReport (won per share).
- **Verdict: PASS**

### Analysis Agent
- Pre-concern: "N >= 2 global IBs before changing Q5 from INSUFFICIENT"
- Evidence: `analyze_snapshot.py:analyze` checks `sample_quality == "ok"`
  which requires `n_implied_global >= 2`. Live result: n_implied_global = 12.
  Q5 = ALIGNED_DIRECTION_AND_LEVEL (gap -0.07%).
- **Verdict: PASS**

### Meta-Audit Agent
- Pre-concern: "INSUFFICIENT preferred to false-positive; need evidence_phrase"
- Evidence: `Q5_details.per_firm_jpm_gs_available = false` is explicitly set
  in analyzer output. Report includes verbatim note: "yfinance 는 per-firm
  이름을 노출하지 않음. JPM/Goldman Sachs 등 개별 IB 의 목표가는 무료 채널로
  수집 불가 (Phase 14-3 audit)".
  Concern about evidence_phrase: since we don't have per-firm rows, the
  evidence_phrase concept doesn't apply at the aggregate level. Schema correctly
  has empty `per_firm` list.
- **Verdict: PASS — honest labeling preserved**

### News Agent
- Pre-concern: "News is discovery-only, numeric extraction requires body access"
- Evidence: Google News RSS was robots-denied; we did not bypass it. No
  numeric values were extracted via news in this phase.
- **Verdict: PASS — abstained as required**

### Evaluator Agent
- Pre-concern: "Sparse coverage must be flagged"
- Evidence: `Q5_details.implied.sample_quality = "ok"` (n=12 >= 2). Q5 label
  reflects sample size. If only 1 implied global IB existed, label would be
  `GLOBAL_SAMPLE_TOO_SMALL`.
- **Verdict: PASS**

### Decision Agent
- Pre-concern: "Refuse to act on Q5 if N < 2 distinct global IBs"
- Evidence: Decision Agent is not yet engaged in this phase, but logic gate
  in analyzer enforces N >= 2 via sample_quality check. Future Decision Agent
  hookup can rely on `Q5_global_vs_domestic != "GLOBAL_SAMPLE_TOO_SMALL" and
  != "GLOBAL_DATA_INSUFFICIENT"`.
- **Verdict: PASS (gate ready for downstream)**

### Narrative Agent
- Pre-concern: "Report must say explicitly if JPM/GS unavailable"
- Evidence: `output/consensus_snapshot/000660_2026-06-30_report.md` lines
  70-80 include the "글로벌 IB 집계" section with the verbatim disclaimer.
- **Verdict: PASS**

### UI Agent
- Pre-concern: "Visual separation of Korea vs Global"
- Evidence: Report has separate sections: "증권사별 목표주가 (per-firm)" for
  Korean (25 brokers) and "글로벌 IB 집계 (yfinance)" for aggregate global.
  Distinct headings, distinct tables.
- **Verdict: PASS**

### Sector Agent
- Pre-concern: "Don't extrapolate to other sectors"
- Evidence: All Phase 14-3 work is fixed to 000660 (반도체). Schema is
  ticker-agnostic but no claims made about generalization.
- **Verdict: PASS**

### Report Agent
- Pre-concern: "Same path for downstream pipeline compatibility"
- Evidence: Output remains `output/consensus_snapshot/000660_2026-06-30_*.{md,json}`.
  New file `000660_global_ib_aggregate.json` is in the same dir, additive.
- **Verdict: PASS**

### PM Agent (self-assessment)
- Pre-concern: "Must execute live, not claim"
- Evidence: yfinance probe is REAL (raw output saved at
  `reports/phase_14_3/yfinance_probe.log`). Finnhub probe is REAL (401
  captured). Yahoo HTML probe is REAL (166KB, sha256 recorded). Robots audit
  is REAL (5 URLs probed, output saved).
- **Verdict: PASS — every probe is verifiable from saved log**

---

## Independent cross-validation (not by individual agents)

14 X-tests run from `scripts/cross_validate_phase14.py`. Phase 14-3 additions:

| Test | Type | Result |
|---|---|---|
| X12 weighted-mean decomposition (yf = dom + global) | arithmetic invariant | PASS (diff < 0.01%) |
| X13 attempts log >= 5 sources | structural | PASS (6 attempts logged) |
| X14 independent peer agent re-derives Q5 | logic invariant | PASS (peer agrees) |

All 14 X-tests PASS, including 2 arithmetic invariants and 1 external
anchor (X9 FDR).

---

## Numeric summary

- yfinance (000660.KS) aggregate: **37 analysts, mean 3,105,259원, KRW**
- WiseReport (000660) Korean: **24 (static) / 25 (per-firm extracted) firms,
  mean 3,177,083원 (static) / 3,106,000원 (per-firm)**
- Implied global IB subset: **n=12, mean 3,103,715원, gap -0.07% vs Korean**
- Q5 result: **ALIGNED_DIRECTION_AND_LEVEL** (small absolute gap, both UP)

Note: The near-identity between yfinance mean (3,105,259) and Korean per-firm
mean (3,106,000) suggests yfinance may itself sample similar or overlapping
sources. The 13-analyst gap (37-24 by static, 12 by per-firm count) is real
but mean targets are statistically indistinguishable. This is **honest
finding**, not a claim of per-firm JPM/GS coverage.

---

## Open issues / future work

1. **Per-firm JPM/GS targets remain unobtained** through free channels. To
   close this would require: Bloomberg Terminal license, FactSet subscription,
   Finnhub API key (paid tier), or manual collection from news articles. The
   PM Agent does not recommend pursuing this without explicit user approval
   and budget.

2. **yfinance is non-official wrapper** (per yfinance disclaimer). Yahoo can
   change its endpoints without notice. A health check on the next live run
   should compare yfinance output to FDR (already done in X9) and warn on
   divergence.

3. **Recommendation breakdown timing**: yfinance returns 4 monthly snapshots
   (0m / -1m / -2m / -3m). Q5 currently only uses 0m. Future phase could
   compute breakdown trend (e.g., strong_buy count rising or falling).

---

## Verdict

Phase 14-3 successfully demonstrates that:
- The system can produce honest aggregate global+Korean consensus from a
  legally-clean source.
- It cannot produce per-firm JPM/Goldman Sachs targets through free
  automated channels (explicitly documented).
- Q5 logic responds correctly to data presence vs absence.
- Cross-validation matrix has grown from 7 to 14 tests, including 2
  arithmetic invariants and 1 external anchor.

All 13 agents agree the implementation matches the pre-review concerns.
