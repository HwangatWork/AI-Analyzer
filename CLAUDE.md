# AI Analyzer — Market Indicator Analysis Pipeline

## Project Overview
Analyzes relationships between 29 market indicators and S&P500/KOSPI over 1 year.
Agent Teams autonomously complete: data collection → analysis → validation → visualization.
Three deliverables: indicator weight ranking / index contribution Top5 / beneficiary stocks Top5.

## Session Start Routine (run before any work)
1. `pwd`
2. `git log --oneline -5`
3. Read `claude-progress.txt` — previous session history
4. Read `pending_requests.json` — select highest-priority incomplete item
5. State current broken/working status in one sentence
Read other files just-in-time, only when the task requires them.

## Tech Stack
- Python 3.x, GitHub Actions (14-stage pipeline), Telegram Bot API
- Test: pytest — run with `python -m pytest agents/tests/ -v`
- Regression baseline: 47/47 PASS minimum (T23=SKIP 허용). Never merge below this.

## Testing Commands
- Full regression: `python -m pytest agents/tests/ -v`
- Stop hook selftest: `python stop_hook.py --selftest`
- Quality checks: run pm_quality_checks (24 checks; Google Sheets = optional SKIP)

## Implementation Levels & Evidence
| Level | Requirement |
|-------|-------------|
| 5–6   | File/code path + line numbers |
| 7     | Code-level verification + expected behavior |
| 8     | Dynamic test required — actual exit code / numbers / logs |
| 9–10  | Level 8 + edge cases / simulation + regression test + docs |

Gate rule (immutable): a gate passes only when every condition has
numeric/log Evidence sent to Telegram. No exceptions.

## Agent Done Criteria
- File creation ≠ done. Every agent must contain a self-verification block.
- Self-verification failure → exit(1) → pipeline blocked.
- New agent without a Done Criteria block → reject in code review.
- Standard pattern (ref: `agents/refresh_data.py:_verify_done_criteria`):
  - DC-1: output file exists; DC-2: not empty; DC-3: row count ≥ min;
  - DC-4: newest row ≤ 7 days old; DC-5: no partial failure flag.
  - Print `DONE_CRITERIA: PASS` or `DONE_CRITERIA: FAIL — …` then `sys.exit(1)`.

## Filter Rules
```python
_CONTEMPORANEOUS = {"NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"}
# Excluded from Evaluator: high correlation without lead = not causal
_SELF_REFERENTIAL = {"RSI14", "MA50", "RSI_SIGNAL", "BETA", "MA_SIGNAL"}
```

## API Key Registration Protocol (OL-1)

When the user provides ANY API key or credential string — immediately do ALL three before anything else:
1. Add to `.env`
2. `gh secret set KEY_NAME --body "value"` (GitHub Actions Secret)
3. Add to `env:` block in `.github/workflows/deploy-dashboard.yml`
4. Run `python scripts/audit_env_secrets.py` to verify all three environments match

**Never stop at step 1.** Root cause: ECOS_API_KEY was `.env`-only → CI used mock data for 11+ hours.

## New Data Source Checklist (OL-3)

When integrating any external API (ECOS, KITA, FRED, KRX, etc.):
- [ ] API key added to `.env`
- [ ] API key added to GitHub Secrets (`gh secret set`)
- [ ] Env var added to workflow `env:` block
- [ ] Mock fallback implemented (no key → `is_mock=True`, graceful degradation)
- [ ] Config entry in `config.yaml` (stat code, endpoint, parameters)
- [ ] `python scripts/audit_env_secrets.py` passes

## RCA Completion Requirements (OL-2)

An RCA is not done until:
1. Root cause stated (one sentence, specific)
2. CLAUDE.md rule added or updated (code change, not verbal promise)
3. Memory saved to `~/.claude/projects/.../memory/operational_lessons.md`
4. Verification script run (audit_env_secrets.py or equivalent)

Verbal-only RCA = Level 1. All four steps = Level 6+.

## Things to Avoid

**FIX-E (2026-06-12): stop_hook stdin JSONL silent failure**
Claude Code passes session transcript as raw JSONL (one JSON object per line), NOT a wrapped
`{"session_id":..., "transcript":[...]}` object. `json.loads(raw)` throws JSONDecodeError,
caught by `except Exception: hook_input = {}` → `transcript = []` → Check1/Check2 = SKIP,
`task_hint = "(작업 내용 없음)"`.
Fix: `_parse_stdin()` — try `json.loads` first, fall back to line-by-line JSONL parsing.
New field in Telegram: `stdin:jsonl|json_object|empty` confirms which path fired.
Never silence a `json.loads` failure in hook code without a JSONL fallback.

**failure_memory.json pattern (Phase 6-4):**
Location: project root. Schema: `{"patterns": [{"agent", "failure_type", "count", "first_seen", "last_seen", "last_error", "resolved"}]}`.
failure_type values: `timeout` / `dc_fail` / `crash`. count >= 3 + resolved=false → SA-FM HIGH + Telegram alert.
Functions: `_load_failure_memory()`, `_record_failure()`, `_record_success()`, `_check_repeat_failures()` in pm_orchestrator.py.
Never block the pipeline on failure_memory I/O errors — all writes are try/except guarded.

**FIX-F (2026-06-13): stop_hook hook_input has no "transcript" array**
DO NOT call `hook_input.get("transcript", [])`.
Claude Code Stop hook sends `transcript_path` + `last_assistant_message`, NOT a transcript array.
`hook_input.get("transcript", [])` always returns `[]` → `_last_messages([])` → all checks SKIP.
Fix: Read `hook_input["last_assistant_message"]` for Check1 (Evidence).
     Open and parse the JSONL file at `hook_input["transcript_path"]` for Check2 (level scan).
(confirmed production 2026-06-12, stdin_debug.txt verified)
