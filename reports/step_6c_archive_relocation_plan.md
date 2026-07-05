# STEP 6C-A — Archive Relocation Design / Dry-Run Plan

**STEP 6C-A result: PASS**

## Purpose
Design and dry-run the archive relocation of the non-canonical, legacy generated
artifact `output/pending_requests.json` into the approved `output/archive/` area.
This phase is design/dry-run only — nothing is moved, deleted, renamed, or
modified. It produces the exact execution, verification, and rollback plan for
the separately-approved STEP 6C-B.

## Baseline working tree state (pre-existing, NOT this phase)
```
 M data/agent_activity.jsonl                    <- runtime write-target (no-touch)
?? reports/ux_audit_2026-07-05.md               <- separate UX phase
?? reports/ux_audit_peer_review_2026-07-05.md   <- separate UX phase
?? test_hooks_full.py                           <- separate TEST-HYGIENE phase
```
These are unrelated to STEP 6C-A and must never be staged by the archive phase.

## Files changed by this phase
- `reports/step_6c_archive_relocation_plan.md` (this file) — the only allowed phase-owned change. Not staged, not committed.

## Artifact inspection (source)
| Property | Value |
|----------|-------|
| Path | `output/pending_requests.json` |
| Exists | **Yes** |
| Size | **1427 bytes** |
| SHA-256 | `8669d070d73ac53c6a8aecf5c2e974eb7bb80151a8e86c69e4bd129beb31ef77` |
| Git tracking | **TRACKED** (`git ls-files` returns it) |
| Working-tree state | **clean** (`git diff --exit-code` exit 0 — no uncommitted change) |

## Destination inspection
| Property | Value |
|----------|-------|
| `output/archive/` exists | **No (ABSENT)** — must be created by STEP 6C-B |
| Proposed destination | `output/archive/pending_requests_legacy_2026-07-05.json` |
| Destination currently exists | **No (free)** — no overwrite risk |
| Destination gitignored | **No** — a moved file there will be tracked normally |

## Proposed destination path & policy justification
`output/archive/pending_requests_legacy_2026-07-05.json`

- `output/archive/` is the policy-approved archive area for **obsolete generated /
  runtime artifacts** (per `docs/policies/pending_requests_policy.md`).
  `output/pending_requests.json` is exactly that: a legacy generated artifact,
  non-canonical, 0 code consumers.
- Filename `pending_requests_legacy_2026-07-05.json` preserves the source
  identity, marks it `legacy`, and date-stamps it (`2026-07-05`, consistent with
  the existing `reports/ux_audit_2026-07-05.md` convention and today's date).
- Distinct enough from the root canonical `pending_requests.json` to remove
  confusion.
- The root `pending_requests.json` (canonical registry) is **out of scope** and
  must remain byte-identical.

## STEP 6C-B execution plan (exact commands — DO NOT run in 6C-A)
Source is **TRACKED and clean**, so `git mv` is the correct path (preserves
history, stages the rename atomically). Because `output/archive/` is **ABSENT**,
create it explicitly first so the move cannot fail on a missing parent:

```
New-Item -ItemType Directory -Force output/archive
git mv output/pending_requests.json output/archive/pending_requests_legacy_2026-07-05.json
```

Notes:
- The `New-Item ... -Force` step is idempotent — it creates `output/archive/`
  only if absent and is safe to run either way. It is allowed **only** in
  STEP 6C-B (not 6C-A).
- `git mv` stages both the deletion of the old path and the addition of the new
  path as a rename.
- Do **not** use a plain `Move-Item` for the file here — that is only the
  fallback for an *untracked* source, which is not the case (source is tracked).

## STEP 6C-B verification plan (after the move)
```
test -e output/pending_requests.json                                   # expect: ABSENT
test -e output/archive/pending_requests_legacy_2026-07-05.json          # expect: EXISTS
python -c "import hashlib;print(hashlib.sha256(open('output/archive/pending_requests_legacy_2026-07-05.json','rb').read()).hexdigest())"
#   expect EXACTLY: 8669d070d73ac53c6a8aecf5c2e974eb7bb80151a8e86c69e4bd129beb31ef77  (byte-identical move)
git status --short --untracked-files=all         # expect: only the rename (R) staged + pre-existing dirty
git diff --exit-code -- pending_requests.json    # expect exit 0 (canonical untouched)
git diff --cached --name-only                    # expect exactly the 2 rename paths (old + new) or 1 R-line
```
Pass condition: destination hash == source hash `8669d070…ef77` (content
preserved), old path gone, canonical registry exit 0, nothing else staged.

## STEP 6C-B staging rule
- Stage **only** the rename (both source-deletion and archive-destination paths).
- `git mv` already stages exactly those — **do not** run `git add .`.
- Before commit, confirm `git diff --cached --name-only` lists only the two
  rename paths and nothing from the pre-existing dirty set
  (`data/agent_activity.jsonl`, `reports/ux_audit_*.md`, `test_hooks_full.py`).

## Recommended STEP 6C-B commit message
```
chore: archive legacy generated pending requests artifact
```

## Rollback plan for STEP 6C-B
Priority order if **not yet committed**:

1. **Preferred — reverse the rename with `git mv`** (cleanest; keeps history):
   ```
   git mv output/archive/pending_requests_legacy_2026-07-05.json output/pending_requests.json
   ```
2. **Fallback — if the rename is only staged and (1) is not usable**:
   ```
   git restore --staged output/pending_requests.json output/archive/pending_requests_legacy_2026-07-05.json
   git restore output/pending_requests.json
   Remove-Item output/archive/pending_requests_legacy_2026-07-05.json -ErrorAction SilentlyContinue
   ```
3. **Then**: if `output/archive/` was newly created and is now empty, remove it
   manually after visual confirmation (do not force-remove a non-empty dir):
   ```
   Remove-Item output/archive -ErrorAction SilentlyContinue   # only if empty
   ```

After any rollback, confirm byte-identity restored:
```
python -c "import hashlib;print(hashlib.sha256(open('output/pending_requests.json','rb').read()).hexdigest())"
#   expect: 8669d070d73ac53c6a8aecf5c2e974eb7bb80151a8e86c69e4bd129beb31ef77
```

If **already committed**:
```
git revert <commit-sha>   # after human approval
```

## Forbidden files unchanged confirmation (STEP 6C-A)
- `output/pending_requests.json` — **not moved / not modified** (still at original path, tracked, clean).
- `pending_requests.json` (root canonical) — `git diff --exit-code` exit 0.
- `README.md`, `ROADMAP.md`, `docs/policies/pending_requests_policy.md` — untouched.
- `data/agent_activity.jsonl` — pre-existing dirty; not touched by this phase.
- `reports/ux_audit_*.md`, `test_hooks_full.py` — untouched.
- `output/archive/` — **not created**.
- No source/test/config/hook files changed. Nothing staged. No commit/push/deploy.

## Human approval required before STEP 6C-B
STEP 6C-B (the actual `git mv`) is an **archive/move action** = a human-approval
trigger per `docs/policies/pending_requests_policy.md`. STEP 6C-A does **not**
authorize execution. Explicit user approval of this plan is required before any
move.

## Risks / uncertainties
- Low risk overall: source is tracked+clean, destination is free and un-ignored,
  hash captured for byte-identity verification.
- Only residual consideration: STEP 6C-B must use path-scoped staging so the
  pre-existing dirty files are never swept in.

## Recommended next action
1. Human 10-level review of this plan.
2. On approval, issue the STEP 6C-B execution TaskSpec.
3. Execute `git mv`, verify destination hash == `8669d070…ef77`, path-scoped
   stage, commit with the recommended message.

## STEP 6C-B not started
Confirmed: no move/rename/delete/create-of-archive occurred in STEP 6C-A. Only
this plan file was written.
