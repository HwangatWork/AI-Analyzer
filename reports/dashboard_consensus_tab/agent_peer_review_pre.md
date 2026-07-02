# Dashboard "컨센서스 트래커" 탭 추가 — Pre-implementation Peer Review

**Date**: 2026-07-03
**Scope**: Add "🎯 컨센서스 트래커" tab to `output/dashboard.html` displaying
Phase 14-0-A1~14-0-C consensus data for 000660 (SK hynix).

Each of 13 agents registers concerns BEFORE code.

---

### Audit Agent (Push safety gatekeeper)
- Concern A1: `.env`, API keys, tokens must not leak into diff.
- Concern A2: `.gitignore` violations (e.g., committing large log files by accident).
- Concern A3: JSON files being fetched by dashboard must be inspected for
  fields that shouldn't be public (user_note in manual entries etc.).
- **Required**: Gate 2 grep for secrets; verify configs/manual_global_ib_targets.json
  is empty or contains no personal notes.

### Data Agent
- Concern D1: Dashboard fetch paths must exist as static files on Pages.
- Concern D2: 404 fetch must not blank the page — needs graceful fallback.
- **Required**: (a) verify JSON files exist, (b) fetch wrapped in try/catch with
  fallback UI.

### Stock Agent
- Concern S1: Ticker dropdown should not be hardcoded to invalid tickers.
- Concern S2: Ticker→ko_name mapping must match backend (000660=SK하이닉스).
- **Required**: Only list tickers with available JSON files.

### Validation Agent
- Concern V1: JSON schema shifts across Phase 14-X versions — dashboard must
  tolerate missing fields.
- Concern V2: Numeric fields may be null; formatters must not throw.
- **Required**: All field access via optional chaining or default values;
  `formatKRW(null)` returns "N/A" not NaN.

### Analysis Agent
- Concern An1: Q4 quadrant has 11 possible enum values; all need color mapping.
- Concern An2: Q5 has 8 possible enum values (Phase 14-3 + 14-4 combined).
- **Required**: Full enum→color map; missing enum → gray + console.warn.

### Meta-Audit Agent
- Concern M1: Snapshot immutability evidence (top_sha256) must be user-visible.
- Concern M2: PIT source (Q1_source field) should be labeled in UI so users
  understand WHERE 1M change came from (chart vs snapshot).
- **Required**: sha256 first 8 chars badge; Q1_source label in Q1 card.

### News Agent
- Concern N1: Named Global IB attribution accuracy ~60-70% — must be
  UNMISSABLE warning banner. Users should not treat as authoritative.
- Concern N2: evidence_phrase display should be truncated to ≤80 chars
  (already enforced backend) — but re-check in UI.
- **Required**: Yellow warning banner above Named Global IB section.

### Evaluator Agent
- Concern E1: data_quality.score should influence overall confidence UI.
- Concern E2: Warning if score < 0.7.
- **Required**: Header badge with score; red when <0.5.

### Decision Agent
- Concern D1: **UI must not auto-generate BUY/SELL decisions**. Q5 label
  is informational only.
- Concern D2: "투자 조언 아님" disclaimer at footer of consensus page.
- **Required**: Explicit disclaimer card at bottom.

### Narrative Agent
- Concern N1: All labels in Korean (firm names in English OK).
- Concern N2: Numeric formatting consistent (원 for KRW, % for percentages).
- **Required**: Central `formatKRW`, `formatPct`, `formatDir` helpers.

### UI Agent
- Concern UI1: Mobile 320px width — must not overflow horizontally.
- Concern UI2: Dark theme contrast (WCAG AA) — most text on --surface should
  be --text (#e2e8f0) or lighter.
- Concern UI3: Tab activation must use existing showPage() pattern (no
  breaking JS additions).
- **Required**: Media query for <640px; use existing CSS variables only.

### Sector Agent
- Concern Se1: Structure should tolerate future non-반도체 tickers.
- Concern Se2: Do NOT promise generalization in this phase; SK hynix only.
- **Required**: TICKER_CONFIG array pattern; docstring warning.

### Report Agent
- Concern R1: Existing 7 tabs must remain 100% functional after change.
- Concern R2: showPage() JS function must NOT be modified — only new markup added.
- Concern R3: Existing `.page` and `.nav-tab` CSS classes must not be redefined.
- **Required**: Regression check: open all 7 existing tabs after change.

### PM Agent (self)
- Concern P1: Path-scoped `git add` only — dozens of unrelated files are in M state.
- Concern P2: Never `git add -A` or `git add .`.
- Concern P3: Force push, `--no-verify`, hook skipping absolutely forbidden.
- Concern P4: Push authorization is granted by user's "계획 수립 후 실행" directive;
  proceed only if ALL 6 gates pass.
- **Required**: Exact commit candidate file list before staging; git status
  cross-check after staging.

---

## PM Resolution table

| Concern | Resolution |
|---|---|
| A1-A3 secrets | Gate 2 grep; inspect JSON contents pre-commit |
| D1-D2 fetch paths | Verify JSON existence; try/catch with fallback |
| S1-S2 ticker | Whitelist to (000660, 005930 if present) |
| V1-V2 schema drift | Optional chaining everywhere; safe formatters |
| An1-An2 enums | Complete Q4/Q5 color maps + fallback |
| M1-M2 immutability | top_sha256 badge; Q1_source shown |
| N1-N2 news accuracy | Yellow warning banner; text truncation re-verified |
| E1-E2 quality | Score badge in header |
| Dec1-Dec2 no auto-BUY | Disclaimer card |
| Nar1-Nar2 Korean+format | Central helpers |
| UI1-UI3 responsive | Media query; reuse CSS vars; no showPage() change |
| Se1-Se2 sector scope | TICKER_CONFIG; docstring |
| R1-R3 regression | No modification to existing HTML/CSS/JS |
| P1-P4 push safety | Path-scoped add; Gate 1-6 gating |

Implementation proceeds.
