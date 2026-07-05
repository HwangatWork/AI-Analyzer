# Pending Requests Policy

Scope: this document defines the semantics, mutation gates, and archive
boundaries of `pending_requests.json`. It does **not** restate the global agent
operating rules — those live in `CLAUDE.md`. Keep the two separate: this file
covers registry behavior only.

## Canonical source

- The **root `pending_requests.json` is canonical.**
- `output/pending_requests.json` is a legacy generated artifact and is **not**
  canonical. It has no code consumers and must not be moved, archived, or
  deleted except in a dedicated, explicitly approved archive-relocation phase.

## Registry semantics

- `pending_requests.json` is a **candidate registry, not an execution queue.**
- An item is **not automatically actionable merely because it exists** in the
  registry. Presence records a candidate; it does not authorize execution.
- Execution requires: audit → explicit user approval → promotion within a
  scoped phase.

## Status and actionability

- `backlog` — a candidate; not scheduled for execution.
- `pending` — does **not** automatically mean "execute now".
- `waiting_credentials` — blocked on a credential/secret; not actionable until
  provided.
- `done` / `completed` (including `status=archived` inside `completed[]`) —
  terminal. Must **not** be reactivated without explicit approval.
- **`REQ-DOGFOOD-AUDIT` is the only approved actionability exception** as of
  this phase. It is intentionally left `status=pending` in `pending[]` because a
  dogfood state-machine flips `pending→completed`; changing its status desyncs
  that loop. Its state is owned by a separate DOGFOOD-STATE decision phase.
- `REQ-015` remains `backlog` and must not be mutated.

## Archive policy

- `docs/archive/` — obsolete **documentation** only.
- `output/archive/` — obsolete **generated / runtime artifacts** only.
- **Runtime write targets must not be archived** (e.g. `data/agent_activity.jsonl`).
- `output/pending_requests.json` requires a dedicated, explicitly approved
  archive-relocation phase and must **not** be handled as part of a
  documentation-only phase.

## Mutation policy

- Registry mutation requires an **explicit, scoped phase**.
- **Documentation-only phases must not modify `pending_requests.json`.**
- No silent ID deletion, recreation, renaming, or status conversion. Every
  change must be attributable to an approved phase.

## Roadmap boundary

- `ROADMAP.md` describes strategy and the current phase. It should **point to**
  the registry and this policy rather than duplicate a detailed executable
  backlog. The registry is the single source of backlog detail.

## Verification policy

- Use **phase-delta validation**, not clean-tree validation. The working tree
  may carry pre-existing dirty/untracked files that are unrelated to a phase.
- Validate with a path-scoped diff limited to the phase's allowed changed paths.
- Confirm forbidden files (registry, audit reports, runtime write targets,
  source, tests, hooks, configs) were not modified by the phase.

## Human approval triggers

The following always require explicit human approval before proceeding:

- registry mutation
- archive / move / delete
- dogfood loop
- `/pr` execution
- agent invocation
- AI-initiated commit / push / deploy
