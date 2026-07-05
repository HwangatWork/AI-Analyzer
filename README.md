# AI Analyzer

Market-indicator analysis pipeline. Analyzes relationships between 29 market
indicators and S&P500 / KOSPI over a 1-year window, and produces three
deliverables: indicator weight ranking, index contribution Top5, and
beneficiary-stock Top5. The system is designed to support an agent-team
pipeline across data collection, analysis, validation, visualization, and
deployment.

## Documentation map

| Document | Role |
|----------|------|
| [ROADMAP.md](ROADMAP.md) | Strategy and current phase. Owns direction, **not** the detailed executable backlog. |
| [pending_requests.json](pending_requests.json) | **Canonical** candidate registry of requests (see policy below). |
| [docs/policies/pending_requests_policy.md](docs/policies/pending_requests_policy.md) | Registry semantics, mutation gates, archive boundaries, approved exceptions. |
| [reports/pending_requests_audit.md](reports/pending_requests_audit.md) | Frozen audit of the registry (human-readable). |
| [reports/pending_requests_audit.json](reports/pending_requests_audit.json) | Frozen audit of the registry (machine-readable). |

## Registry vs roadmap

- **`pending_requests.json` (root) is canonical.** It is a *candidate registry*,
  **not an execution queue** — an item existing there does not make it
  actionable. Nothing is implemented until it passes audit, receives explicit
  user approval, and is promoted within a scoped phase.
- **`ROADMAP.md` owns strategy and the current phase**, not the detailed
  executable backlog. Backlog detail lives in the registry; policy lives in the
  policy doc.
- **`output/pending_requests.json` is NOT canonical.** It is a legacy generated
  artifact and must not be moved, archived, or deleted except in a dedicated,
  explicitly approved archive-relocation phase.

## Operational guardrails

- One phase at a time.
- No registry mutation without an explicit, scoped phase.
- No archive / move / delete during documentation-only phases.
- No agent invocation or dogfood loop unless explicitly requested.
- Commit only after human review.

## Testing

```
python -m pytest agents/tests/ -v
```
