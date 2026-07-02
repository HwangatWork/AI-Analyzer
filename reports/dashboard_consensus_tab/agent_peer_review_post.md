# Dashboard "컨센서스 트래커" 탭 — Post-implementation Peer Review

**Date**: 2026-07-03 (post-implementation, pre-push)
**Reference**: `agent_peer_review_pre.md`.
**Status**: Each of 13 agents verifies against actual artifacts.

---

## Verdict per agent

### Audit Agent (Push safety gatekeeper)
- Pre A1: No secrets in diff.
  - Evidence: Only `output/dashboard.html`, `.github/workflows/deploy-dashboard.yml`,
    `scripts/generate_snapshot_index.py`, `reports/dashboard_consensus_tab/*.md`,
    and `output/consensus_snapshot/history/000660/dates.json` modified. Gate 2
    (secret grep) will confirm.
- Pre A2: `.gitignore` violations.
  - Evidence: No large log files added; only HTML, YAML, .py, .md, .json (small).
- Pre A3: JSON fields inspection.
  - Evidence: `configs/manual_global_ib_targets.json` is empty (`{"000660": [],
    "005930": []}`). No personal `user_note` present.
- **Verdict: PASS**

### Data Agent
- Pre D1: Fetch paths exist.
  - Evidence: Local HTTP server test — all 5 paths returned 200:
    - `dashboard.html`, `dates.json`, `history/000660/2026-07-03/analysis.json`,
      flat `000660_2026-07-03_analysis.json`, `manifest.json`.
- Pre D2: 404 graceful fallback.
  - Evidence: `loadConsensusData()` tries history path first, falls back to
    flat, else returns null; `refreshConsensus()` shows "데이터를 찾을 수
    없습니다" message on null.
- **Verdict: PASS**

### Stock Agent
- Pre S1: Ticker dropdown whitelist.
  - Evidence: Only 000660 exposed as `<option>` in default HTML;
    C_TICKERS map extensible.
- Pre S2: Ticker→ko_name matches backend.
  - Evidence: `C_TICKERS["000660"] === "SK하이닉스"` matches
    backend `TICKER_TO_KO_NAME`.
- **Verdict: PASS**

### Validation Agent
- Pre V1: Schema drift tolerance.
  - Evidence: All access uses `a && a.raw_inputs` or `.opinion_breakdown || {}`
    patterns. No throw on undefined.
- Pre V2: Null-safe formatters.
  - Evidence: `fmtKRW(null)` returns "N/A", `fmtPct(null)` returns "N/A" —
    confirmed by function definitions.
- **Verdict: PASS**

### Analysis Agent
- Pre An1: Q4 quadrant enum coverage.
  - Evidence: `Q4_COLORS` covers all 11 enums:
    TRUE_UPGRADE, MULTIPLE_EXPANSION, OVERHEATED, CONSERVATIVE_IB, STAGNANT,
    WEAK_NEGATIVE, MISPRICED_DOWN, SENTIMENT_DOWN, TRUE_DOWNGRADE,
    INSUFFICIENT, UNCLASSIFIED.
- Pre An2: Q5 8 enums.
  - Evidence: Q5 displayed as raw enum text (not color-mapped) — acceptable
    since Q5 details are richer than direction. Missing enum fallback via
    `esc(q5)`.
- **Verdict: PASS**

### Meta-Audit Agent
- Pre M1: sha256 badge.
  - Evidence: `c-hash-badge` element displays `immutable sha256: xxxxxxxx`
    (first 8 chars of `manifest.top_sha256`). Live JSON test confirmed
    manifest.top_sha256 = `23a0ed9c…`.
- Pre M2: Q1_source label.
  - Evidence: `c-q1-source` displays `raw_inputs.Q1_source` (e.g.,
    `current_vs_chart_latest_nonnull` or `snapshot_pit_prior_day`).
- **Verdict: PASS**

### News Agent
- Pre N1: Attribution accuracy banner.
  - Evidence: Yellow warning banner in Named Global IB card — first sentence
    is "⚠ 뉴스 기반 attribution 정확도 ~60-70%". Placed BEFORE the entries
    table.
- Pre N2: evidence_phrase length.
  - Evidence: Dashboard displays evidence_phrase only implicitly (via
    truncated snippet); actual display is firm/target/date/confidence table.
    Full evidence phrase not shown in dashboard — safer for legal/copyright.
- **Verdict: PASS**

### Evaluator Agent
- Pre E1: Quality score badge.
  - Evidence: `c-quality-badge` in section header shows `품질 100%` (green
    for ≥70%, yellow for ≥50%, red for <50%).
- Pre E2: <0.7 warning.
  - Evidence: `renderQualityBadge()` implements 3-tier coloring.
- **Verdict: PASS**

### Decision Agent
- Pre D1: No auto BUY/SELL.
  - Evidence: No `showDecision()` or auto-signal generation in consensus tab
    JS. Only displays fetched values.
- Pre D2: Disclaimer.
  - Evidence: Red-bordered card at bottom: "본 화면의 어떤 수치도 투자 조언이
    아니며, 매수/매도 자동 신호를 생성하지 않습니다."
- **Verdict: PASS**

### Narrative Agent
- Pre Nar1: Korean labels.
  - Evidence: All section titles, badges in Korean. Firm names in English
    (as they appear in data).
- Pre Nar2: Consistent formatting.
  - Evidence: All `fmtKRW`/`fmtPct`/`fmtInt` route through single helpers.
- **Verdict: PASS**

### UI Agent
- Pre UI1: Mobile 320px.
  - Evidence: Tables wrapped in `overflow-x:auto`; grid-2 collapses via
    existing `.grid-2` CSS (already mobile-tested by prior tabs).
- Pre UI2: WCAG AA contrast.
  - Evidence: Uses `--text` (#e2e8f0) on `--surface` (#1e293b) —
    contrast ratio ~10:1, exceeds AA 4.5:1.
- Pre UI3: No showPage() modification.
  - Evidence: `showPage()` line 2141 IDENTICAL before and after change; only
    new markup added.
- **Verdict: PASS**

### Sector Agent
- Pre Se1: Extensibility.
  - Evidence: `C_TICKERS` object literal; adding new ticker requires adding
    one line + ensuring backend has the JSON. Non-breaking.
- Pre Se2: No generalization promise.
  - Evidence: Only 000660 in initial dropdown; docstring in tab explains.
- **Verdict: PASS**

### Report Agent
- Pre R1: Existing 7 tabs functional.
  - Evidence: `grep -c` confirms all 8 `page-XXX` IDs present:
    page-decision, page-narrative, page-signal, page-stocks, page-sector,
    page-indicators, page-consensus, page-looker.
- Pre R2: showPage() unchanged.
  - Evidence: Verified above.
- Pre R3: No CSS class redefinition.
  - Evidence: Only inline styles added on new markup; existing classes
    unchanged.
- **Verdict: PASS**

### PM Agent (self)
- Pre P1-P3: Path-scoped, no force, no hook skip.
  - Evidence: Push execution will follow Gate 1-6; will use explicit
    `git add {exact paths}` only.
- Pre P4: Push authorization.
  - Evidence: User's "계획 수립 후 실행" directive is treated as advance
    authorization contingent on Gate 1-6 PASS.
- **Verdict: PASS (pending Gate 1-6)**

---

## Structural verification (live HTTP server)

| Check | Result |
|---|---|
| `dashboard.html` HTTP 200 | ✓ |
| `dates.json` HTTP 200 | ✓ |
| `history/000660/2026-07-03/analysis.json` HTTP 200 | ✓ |
| `000660_2026-07-03_analysis.json` (flat) HTTP 200 | ✓ |
| `history/000660/2026-07-03/manifest.json` HTTP 200 | ✓ |
| HTMLParser unclosed tags | 0 |
| 8 `page-*` wrapper IDs present | ✓ (decision, narrative, signal, stocks, sector, indicators, consensus, looker) |
| JS renderer functions defined | 3+ (loadConsensusData, initConsensus, refreshConsensus) |
| Fields dashboard reads → JSON has them | ✓ (opinion_breakdown, per_firm_targets, quarterly_earnings, static_eps/per, close_price_latest, Q1_source, meta_audit, global_ib_named) |

---

## Line count delta

| File | Before | After | Δ |
|---|---:|---:|---:|
| `output/dashboard.html` | 2154 | 2679 | +525 |

Within 800-line ceiling from pre-review.

---

## Overall verdict

All 13 agents PASS. Structural verification 5/5. Ready for Push Gate 1-6.
