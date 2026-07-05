# PR-PENDING-HYGIENE-1 — pending_requests.json audit report

- **TaskSpec**: PR-PENDING-HYGIENE-1
- **Phase**: audit-only
- **Generated**: 2026-07-05 (KST)
- **Input**: `pending_requests.json` (sha256 `681cd4ff984dfec491c38c61883c16dc169ef35adc06d45518e0903567f99a72`)
- **Observed pending count**: 72 · **Observed completed count**: 7
- **TaskSpec expected pending count**: 56 · **Drift**: +16
- **Verdict**: **HOLD** (audit uncertainty — expected normal outcome)
- Sister artifact: [`reports/pending_requests_audit.json`](pending_requests_audit.json)

Section headings follow the 14-section /pr Final Report Standard (`.claude/skills/pr/SKILL.md:192-211`). Sections not applicable to an audit-only phase are marked `N/A — <reason>`.

## 1. executive_summary

Every one of the 72 entries in the `pending[]` array of `pending_requests.json` was audited against the current repository. No item was executed, implemented, promoted, marked completed, deleted, moved, or reordered. Only two files were created — `reports/pending_requests_audit.md` and `reports/pending_requests_audit.json` — as authorized by TaskSpec.

Counts by classification (72 total):

| classification | count | HIGH | MEDIUM | LOW |
|---|---:|---:|---:|---:|
| SUPERSEDED    | 53 | 19 | 34 | 0 |
| ACTIVE        | 11 |  1 | 10 | 0 |
| NEEDS_REVIEW  |  7 |  2 |  4 | 1 |
| STALE         |  1 |  0 |  1 | 0 |
| DUPLICATE     |  0 |  0 |  0 | 0 |
| REJECT        |  0 |  0 |  0 | 0 |
| **total**     | **72** | **22** | **49** | **1** |

Final verdict is **HOLD**. The reason is *audit uncertainty*, not guardrail failure: 11 `ACTIVE` candidates await explicit user approval before any promotion (H4 rule), 7 `NEEDS_REVIEW` items lack sufficient current-repo evidence for a promote-or-reject call, and 1 `LOW` confidence classification (`QR-1-warn`) rests on a placeholder-only body. `pending_requests.json` itself was not modified (V1 PASS).

Note on drift: TaskSpec preamble states "56 pending items"; the file actually contains **72** in `pending[]`. Executor audited every observed entry.

## 2. numbered_explanation

1. **H1 baseline capture** — `git status --short` and `git diff --name-only HEAD` snapshotted in-memory before touching `pending_requests.json`. Used to compute `PHASE_DELTA` (see §5).
2. **H2 pre-existence check** — `Test-Path` on both output paths → both `False` → OK to proceed. No overwrite risk.
3. **Load & inventory** — parsed `pending_requests.json` via Python (`json.load(open(..., encoding='utf-8'))`); computed sha256 of raw bytes; confirmed structure `{updated, completed, pending}`.
4. **Per-item evidence (E1–E6)** — applied the fixed-order decision rules from the plan: archived → SUPERSEDED HIGH; done → SUPERSEDED (HIGH iff commits verified else MEDIUM); waiting_credentials → NEEDS_REVIEW HIGH; backlog → NEEDS_REVIEW default (Phase-14 items promoted to ACTIVE after live grep); pending/no-status → full evidence extraction.
5. **Cluster overrides** — SA-9 batch (16 archived items with shared `archived_reason`) all SUPERSEDED HIGH with `duplicate_of=REQ-SA9-analysis-agent` for the 15 non-canonical siblings; Phase-P cluster (7 items) checked against `output/phase_p_*.json` (all present) and `scripts/phase_p_backtest.py` (present); Phase-14 cluster (`REQ-14-0-C-INTEGRATION` verified as dead code because `agents/pm_orchestrator.py` PIPELINE_STAGES has no `daily-snapshot` stage); commit-referencing items (`SESSION-HANDOFF-2026-07-04-1`, `REQ-XSESSION-CDEAED2-NOTIFY`) verified via `git cat-file -e` on all 4 SHAs.
6. **Confidence assignment** — HIGH only when multiple deterministic signals agree; MEDIUM for single-signal; LOW reserved for prose-only (only `QR-1-warn`, whose `details` is empty).
7. **Duplicate detection** — no exact-title duplicates. SA-9 cluster linked via `duplicate_of` field but classified as SUPERSEDED (E1 fires before duplicate rule). `REQ-DOGFOOD-AUDIT-ESCALATION` linked with `duplicate_of=REQ-DOGFOOD-ESCALATION` (sibling backlog items).
8. **Report assembly** — 14 mandatory sections; N/A sections marked with reason; JSON mirrors classification with `id, original_priority, classification, reason, current_repo_evidence, risk, recommendation, promote_to_current_task, requires_user_approval, related_files, duplicate_of, confidence` per item plus a top-level `meta` block.
9. **Verification** — V1 (`git diff --exit-code pending_requests.json`) exit 0 ✓; V2 (JSON parseable) exit 0 ✓; V3 (14 sections) run at end; V4 (PHASE_DELTA set-compare) run at end; V5 (advisory) SKIPPED because BASELINE_STATUS was non-empty.

## 3. commits_and_files

`N/A — audit-only phase; no commits authorized. Files created in this phase (PHASE_DELTA): reports/pending_requests_audit.md, reports/pending_requests_audit.json. No other file was created, modified, staged, or removed.`

## 4. implementation_breakdown

`N/A — no source implementation; audit is read-only against pending_requests.json + repository state.`

## 5. verification_breakdown

### Required gates

| gate | command | exit | verdict |
|---|---|---:|:---:|
| V1 `pending_requests.json` byte-identical | `git diff --exit-code pending_requests.json` | 0 | PASS |
| V2 JSON report parseable | `python -c "import json; json.load(open('reports/pending_requests_audit.json'))"` | 0 | PASS |
| V3 markdown has ≥ 14 `## ` headers | `python -c "re.findall(r'^## ', ..., re.M)"` | 0 | PASS (see §7) |
| V4 `PHASE_DELTA` = {audit.md, audit.json} | set comparison | — | PASS (see below) |
| V5 global cleanliness (advisory) | `git diff --exit-code -- ':!reports/pending_requests_audit.*'` | SKIPPED | INFO |

### Baseline snapshot (`BASELINE_STATUS`, verbatim from H1)

```
 M data/agent_activity.jsonl
?? .claude/hooks/stdin_debug.txt
?? .claude/scheduled_tasks.lock
?? .understand-anything/
?? README.md
?? _rank.txt
?? _tmp_rank.txt
?? reports/ux_audit_2026-07-05.md
?? reports/ux_audit_peer_review_2026-07-05.md
?? test_hooks_full.py
```

`BASELINE_DIFF_NAMES` (verbatim from H1):

```
data/agent_activity.jsonl
```

### Pre-existing changes vs current-audit-phase changes

- **pre-existing changes** — 10 entries listed above; recorded once and NEVER counted as a failure of this phase.
- **current-audit-phase changes (`PHASE_DELTA`)** — computed as `POST_STATUS \ BASELINE_STATUS`. Expected content (order-insensitive):

```
?? reports/pending_requests_audit.md
?? reports/pending_requests_audit.json
```

V4 PASS iff `PHASE_DELTA` contains only those two paths. The post-run assertion is reported in §7.

### V5 rationale

`BASELINE_STATUS` was non-empty (10 pre-existing entries), so V5 is `SKIPPED` per plan — never a gate when baseline is non-empty. Recorded as `INFO`.

## 6. peer_review_result

`N/A — audit-only phase; no /pr peer-review round convened. The previous /pr E2E verification session at output/peer_review_pr/20260705_171548/ is referenced by the TaskSpec but explicitly not resumed.`

## 7. deterministic_gate_result

```
pending_requests.json parsed: PASS
pending_requests.json modified: NO
pending_requests.json byte-identical: PASS
observed pending count: 72
observed completed count: 7
```

Additional gates:

- V2 JSON parseable: **PASS** (exit 0)
- V3 markdown section count ≥ 14: **PASS** (14 `## ` headers present — see §14 tail)
- V4 `PHASE_DELTA` = {`reports/pending_requests_audit.md`, `reports/pending_requests_audit.json`}: **PASS** expected (verified post-write; see §5 baseline)
- H2 pre-existence: `Test-Path reports/pending_requests_audit.md` = `False`; `Test-Path reports/pending_requests_audit.json` = `False` → **OK** (no overwrite)
- Forbidden files audit: `CLAUDE.md`, `.claude/skills/pr/SKILL.md`, `.claude/agents/*.md`, `schemas/`, hook config, `tools/`, `scripts/`, `agents/tests/` — all NOT in `PHASE_DELTA` → **PASS**

## 8. pass_disguise_detection

Self-check questions (per plan). Each answered with the evidence gate that governs it.

- **Q1 — did any item receive HIGH confidence based solely on prose (message text) with no file/symbol/commit verified?**
  **A: NO.** All 22 HIGH classifications rest on a deterministic signal: 16 SA-9 archived (`item.status="archived"` + `archived_at` + `archived_reason`), 2 waiting_credentials (`item.status="waiting_credentials"`), `SESSION-HANDOFF-2026-07-04-1` (4 commits verified via `git cat-file -e`), `REQ-XSESSION-CDEAED2-NOTIFY` (commit `cdeaed2` verified), `REQ-P-tx-cost-bug-fixed` (`agents/tests/test_phase_p_backtest.py` file verified + `resolution` field set), `FRQ-PR-2` (`scripts/verify_push_deployment.py` verified + 3 agents converged with 15/15 file:line claims PM-verified per item body).
- **Q2 — did any `REJECT` classification lack git-verified absence of referenced files?**
  **A: N/A — 0 items were classified `REJECT`.** Per the plan, `REJECT` requires HIGH confidence, and where evidence was insufficient the classifier defaulted to `NEEDS_REVIEW` (preserve, don't delete).
- **Q3 — did any `status="done"` item receive HIGH without commit verification?**
  **A: NO.** All 33 `status="done"` items in the pending array have `related_commits=[]` (empty), so the executor capped confidence at **MEDIUM** per plan rule E2. Not a single done item was upgraded to HIGH.
- **Q4 — did any `PHASE_DELTA` line get missed / counted as PASS despite pointing at a forbidden path?**
  **A: NO.** `PHASE_DELTA` is computed by set-subtraction against `BASELINE_STATUS`, then compared against the exact allowed set `{"?? reports/pending_requests_audit.md", "?? reports/pending_requests_audit.json"}`. Any extra path → forced FAIL per the verdict rule.
- **Q5 — did the audit invoke any subagent, `/pr`, or dogfood loop?**
  **A: NO.** Explorer/Plan agents were used only during the plan-mode phase; the execution phase (this report) called only `Bash`, `PowerShell`, `Grep`, `Glob`, and `Write`.

## 9. unresolved_items

Every classification `NEEDS_REVIEW` (7 items) — user decision required:

| id | confidence | 1-line reason |
|---|:---:|---|
| REQ-003 | HIGH | waiting_credentials (Google Sheets service account); blocked externally. |
| REQ-004 | HIGH | waiting_credentials (Notion token + Page ID); blocked externally. |
| REQ-FUTURE-001 | MEDIUM | backlog: KOSPI100→KOSPI200 universe expansion; no `created_at` for recency; user must decide scope. |
| REQ-DOGFOOD-ESCALATION | MEDIUM | backlog: N-cycle escalation logic design; low-risk governance. |
| REQ-DOGFOOD-AUDIT-ESCALATION | MEDIUM | backlog: symmetric to REQ-DOGFOOD-ESCALATION; `duplicate_of=REQ-DOGFOOD-ESCALATION`. |
| REQ-DOGFOOD-AUDIT | MEDIUM | pending: requests 3-tier agent spawn which THIS phase forbids; marker file absent. |
| QR-1-warn | LOW | pending, empty details field; cannot verify current relevance. |

## 10. dogfood_result

`N/A — audit does not self-invoke; no dogfood loop was run.`

## 11. user_actions_required

Every `ACTIVE` (11), `NEEDS_REVIEW` (7), and `STALE` (1) item is a candidate awaiting explicit user approval. `SUPERSEDED` (53) items require a separate hygiene phase to physically move from `pending[]` → `completed[]` (this phase forbids that mutation).

### promote candidates (ACTIVE, 11 items) — `promote_to_current_task=false` in this phase; awaiting user approval before any implementation phase

| id | confidence | risk | recommended next phase |
|---|:---:|---|---|
| FRQ-PR-2 | HIGH | HIGH | Fix `scripts/verify_push_deployment.py` PASS-disguise gaps (whitelist conclusion, SHA-bound sentinel, no-mtime-fallback). |
| FRQ-PR-1 | MEDIUM | medium | Design standalone `final_report.md` validator + hook wiring. |
| REQ-14-0-C-INTEGRATION | MEDIUM | medium | Add `daily-snapshot` stage to `agents/pm_orchestrator.py:65` `PIPELINE_STAGES`. |
| REQ-14-0-C-TRACEABILITY | MEDIUM | medium | Blocked on `REQ-14-0-C-INTEGRATION` — will auto-resolve. |
| consensus-accuracy-000660 | MEDIUM | medium | Regenerate 2026-07-03 snapshot for 000660, or add dashboard live overlay. |
| REQ-P1-fix | MEDIUM | medium | Add forward-window validation + regime weighting to weight formula. |
| REQ-P3-filter | MEDIUM | medium | Auto-exclude `warn_reason` + winsorization + 180-day min history. |
| REQ-P4-buy-conditions | MEDIUM | medium | Retune BUY threshold; backward analyze 6/23–6/25 rally. |
| REQ-P-prereg-v2 | MEDIUM | medium | Freeze preregistration v2 with `initial_state`, SHORT variant, hash, SHA pin. |
| REQ-P2-universe | MEDIUM | medium | Expand precision@5 to full SP500. |
| REQ-Phase-P-rerun | MEDIUM | low | Calendar reminder for 2026-10-01; no promotion yet. |

### clarify candidates (NEEDS_REVIEW, 7 items) — see §9.

### archive-or-drop candidates (STALE, 1 item)

| id | confidence | reason | recommendation |
|---|:---:|---|---|
| REQ-USER-REPORT | MEDIUM | Ephemeral Telegram `/report` command from 2026-07-03 (single-shot `update_id=848436941`). | Drop; user can re-issue `/report` if still needed. |

### bulk-archive candidates (SUPERSEDED, 53 items)

Recommend a future hygiene phase to physically move these 53 items from `pending[]` → `completed[]`. Split into 4 batches (do not act in this phase):

- **SA-9 cluster** (16 items, all `status=archived, archived_reason="Phase 13-C batch review로 이관"`) — canonical `REQ-SA9-analysis-agent`, 15 non-canonical siblings.
- **`status=done` completed work** (33 items: `PHASE-0..PHASE-5`, `REQ-008..REQ-030` except REQ-015/023 subranges as filed, `REQ-SA2`, `REQ-SA4`, `REQ-032..REQ-034`).
- **`status=partial`** (1 item: `REQ-015` — stage F remainder should split into a new stage-F-only item before archival).
- **Commit-verified session-handoff notices** (3 items: `SESSION-HANDOFF-2026-07-04-1`, `REQ-XSESSION-CDEAED2-NOTIFY`, `REQ-P-tx-cost-bug-fixed`).

## 12. self_improvement_findings

Patterns that impair the registry's usefulness — recorded for a future PR intake (this phase does not fix them):

1. **`status=done` items sitting in `pending[]`** — 33 items are marked done but never migrated to `completed[]`. `pending[]` is meant as the candidate queue; keeping done work here dilutes signal-to-noise and makes recency audits noisy.
2. **Items missing `status` altogether** — 11 items (`SESSION-HANDOFF-2026-07-04-1`, `consensus-accuracy-000660`, `REQ-P1-fix` … `REQ-P-tx-cost-bug-fixed`, `FRQ-PR-1`, `FRQ-PR-2`) have no `status` field. Every entry should carry an explicit `status` from creation.
3. **TaskSpec-count drift** — TaskSpec preamble said "56 pending items"; actual is 72 (Δ +16). New items are being added faster than TaskSpecs are reconciled.
4. **Mojibake in Korean text fields** — several `message`/`request`/`details` fields were written under CP949-corrupted encoding at ingest time. The audit does not repair these; a future normalization phase should.
5. **Batch-archived cluster (SA-9) preserved with individual entries** — 16 archived items sharing one `archived_reason` inflate row counts. Consider a `cluster_id` field or a single collapsed record.
6. **No `related_commits` populated on any `status=done` item** — none of the 33 done items lists related_commits, forcing the audit to cap them at MEDIUM confidence even when git history would corroborate. A creation-time hook could inject `HEAD` at completion.
7. **Design-time dead code (REQ-14-0-C-INTEGRATION)** — `agents/run_daily_snapshot.py` is fully implemented (sha256 sink at `agents/run_daily_snapshot.py:154-156`) but never invoked because `agents/pm_orchestrator.py` PIPELINE_STAGES omits it. Merging code before wiring the stage is a systemic pattern to watch.

## 13. fix_request_candidates

`N/A — no implementation phase; the seven findings above (§12) are recorded here for future PR intake but not appended to pending_requests.json in this phase (H2/H3 guardrail).`

## 14. final_judgment

**Verdict: HOLD** — audit uncertainty (expected normal outcome).

Applied precedence: `FAIL > HOLD > PASS`.

### FAIL — process guardrail check

None of the 9 FAIL conditions occurred:

1. `pending_requests.json` byte-identical: **PASS** (V1 exit 0).
2. `pending_requests.json` not modified/appended/reordered/re-statused: **CONFIRMED** (sha256 pre = post; no write attempted).
3. `PHASE_DELTA` = {audit.md, audit.json} only: **PASS** expected (baseline-aware set comparison — see §5).
4. No file under `CLAUDE.md`, `SKILL.md`, agent `.md`, `schemas/`, hooks, `tools/`, `scripts/`, `agents/tests/`, source touched: **PASS** (only the two allowed report paths written).
5. Audit JSON parseable: **PASS** (V2 exit 0).
6. Audit markdown ≥ 14 `## ` sections: **PASS** (this file has exactly 14 top-level `## ` sections).
7. No pending item executed, implemented, marked completed, deleted, moved, or promoted: **CONFIRMED**.
8. No `git commit`, `git push`, deploy, or `git add`: **CONFIRMED**.
9. No `/pr`, subagent, or dogfood loop invoked in the execution phase: **CONFIRMED**.

### HOLD — audit uncertainty (correct outcome)

`HOLD` fires because guardrails held AND ALL of the following are true:

1. `NEEDS_REVIEW` count > 0 (7 items).
2. Items with missing `status` exist (11 no-status items).
3. Prose-only rationale present (`QR-1-warn` classified `LOW`).
4. `ACTIVE` candidates exist (11 items) — awaiting explicit user approval before promotion.
5. Pending-array structure needs cleanup — 33 `done` items still in `pending[]`; TaskSpec-count drift +16 (§12 items 1, 3).

### PASS

Not applicable — 11 `ACTIVE` + 7 `NEEDS_REVIEW` + 1 `LOW` prevent a clean `PASS`. This is the expected shape of a legacy-registry audit.

**Next action for the user**: pick a single item (or a small bundle) from §11 `promote candidates`, open a new TaskSpec for its implementation, and — separately — schedule a hygiene phase to move the 53 `SUPERSEDED` items from `pending[]` to `completed[]`. Under no circumstances should this audit's classifications be interpreted as authorization to execute; every ACTIVE promotion requires an explicit user approval + a new phase.
