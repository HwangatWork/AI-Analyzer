# Phase 14-0-C Pre-implementation Peer Review

**Goal**: Activate the point-in-time invariant. Every successful pipeline run
appends an immutable dated snapshot to `output/consensus_snapshot/history/`.
Historical entries MUST never be overwritten silently.

**Motivation**: Ljungqvist, Malloy, Marston 2009 documented I/B/E/S retroactively
modifying 1.6-21.7% of historical analyst recommendation records. WiseReport's
chartData2 monthly series is a moving target too. Only self-captured snapshots
can serve as look-ahead-safe historical truth.

Each agent registers a concern BEFORE code.

---

### Audit Agent
- Concern: If snapshot files are writable after creation, any subsequent bug
  or malicious process could rewrite them. Immutability must be enforceable
  at the file-system level, not just by convention.
- Required: post-write sha256 manifest; verification function that any
  reader can call to detect tampering.

### Data Agent
- Concern: Multiple pipeline runs on the same day should not create
  duplicate snapshots. Second run on 2026-07-03 should not silently
  overwrite the first.
- Required: `write_snapshot(force=False)` defaults to refuse if
  `{date}.json` already exists; `force=True` is CLI-explicit only.

### Stock Agent
- Concern: Snapshot key must include ticker to avoid cross-contamination
  when the pipeline runs on multiple tickers.
- Required: layout `output/consensus_snapshot/history/{ticker}/{YYYY-MM-DD}/`

### Validation Agent
- Concern: The manifest sha256 must cover ALL files in the snapshot
  directory, not just one. If report.md is regenerated but analysis.json
  is untouched, we lose the ability to detect the drift.
- Required: manifest lists every file with its sha256; a single top-level
  sha256 covers the ordered concatenation.

### Analysis Agent
- Concern: Point-in-time Q1 recomputation requires ≥2 snapshots. The
  transition between "chart-based Q1" (Phase 14-1 RCA fix) and
  "snapshot-based Q1" (Phase 14-0-C) must be labeled in output so a
  reader knows which source drove the number.
- Required: `Q1_source` field: `"chart_internal_trend"` /
  `"snapshot_pit_prior_day"` / etc.

### Meta-Audit Agent
- Concern: Any code that reads history must be READ-ONLY. Introducing a
  `delete_snapshot()` or `edit_snapshot()` function anywhere in the code
  base creates a hazard.
- Required: module docstring explicitly forbids destructive operations;
  no such function shall exist.

### News Agent
- Concern: news_search results are timestamped-at-fetch. If today's snapshot
  is compared against yesterday's, the news search results themselves have
  moved. Q5 comparisons across days must NOT mix news-based signals from
  different days.
- Required: news entries in a snapshot are tagged with `fetched_at` and
  never re-interpreted after the snapshot is closed.

### Evaluator Agent
- Concern: Data quality score depends on all fields being present. Snapshot
  writer must FAIL if quality drops below a threshold, not silently write
  a low-quality baseline.
- Required: `write_snapshot` refuses if `data_quality.score < 0.5`.

### Decision Agent
- Concern: A decision made on 2026-07-03 must be traceable to the snapshot
  used. Downstream systems must be able to answer "what data did we see
  when we decided?".
- Required: snapshot manifest includes `decided_at` and
  `pipeline_git_head_sha` (best-effort).

### Narrative Agent
- Concern: Reports for past dates should still be renderable from the
  archived snapshot without touching current data.
- Required: `render_report(analysis_from_snapshot)` works purely from
  snapshot inputs.

### UI Agent
- Concern: History listings need chronological ordering and gap detection
  (missing days).
- Required: `list_snapshots(ticker)` returns dates ordered; gap detection
  logs INFO warnings for missing weekdays >2 days apart.

### Sector Agent
- Concern: For sector rollup, we may need to query multiple tickers'
  snapshots on the same date. The store must be efficient for that.
- Required: `get_snapshot_batch(tickers, date)` supports batch lookup.

### Report Agent
- Concern: Existing consumers read `output/consensus_snapshot/{ticker}_{date}_*.md`.
  Phase 14-0-C must maintain backward compatibility.
- Required: current flat-file outputs continue; history directory is
  ADDITIVE.

### PM Agent (self)
- Concern: Retention policy. Unbounded growth is a risk. But early
  deletion breaks point-in-time.
- Resolution: 60-day rolling window keeps current phase actionable; older
  snapshots move to `history/{ticker}/_archive/` with lower access
  frequency. No deletion in this phase.

---

## PM Resolution table

| Concern | Resolution |
|---|---|
| File-system immutability | sha256 manifest + `verify_snapshot_integrity` public API |
| Same-day duplicate | default deny, `--force` CLI-explicit |
| Ticker separation | `history/{ticker}/{date}/` directory layout |
| Full-directory manifest | manifest lists every file + top-level sha256 |
| Q1 source labeling | `Q1_source` enum in analysis output |
| No destructive operations | docstring forbids; no `delete_*`/`edit_*` functions |
| Cross-day news mixing | news entries have `fetched_at`; frozen at snapshot time |
| Quality gate | refuse if data_quality.score < 0.5 |
| Decision traceability | manifest includes `pipeline_git_head_sha` |
| Past-date rendering | pure function from snapshot inputs |
| Chronological listing + gap detection | ordered list + INFO on gap |
| Sector batch query | `get_snapshot_batch` supported |
| Backward compatibility | flat-file outputs preserved; history is additive |
| Retention | no deletion in this phase; archive policy deferred |

Code may proceed.
