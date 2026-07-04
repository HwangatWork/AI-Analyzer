---
name: pr
description: Peer Review orchestration — evaluates the full project-agent roster for task fit, runs up to 5 peer review rounds with mandatory critic-agent participation, and pm-agent issues a 1-10 score gate plus final verdict. Only fires when the user explicitly invokes /pr.
argument-hint: [review target content or file path]
disable-model-invocation: true
allowed-tools: Agent, Bash, Read, Write, Glob, Grep
---

# /pr — Multi-Agent Peer Review (PM Score Gate)

Orchestrate a project-agent peer review of the task in `$ARGUMENTS`.
Execute Phases 0-5 below strictly in order.

## Invariant Rules (violation = execution failure)

1. **NEVER assign personas to general-purpose / Explore agents.** Only spawn named
   agents defined in `.claude/agents/` (past failure: general-purpose persona was used
   instead of ui-agent).
2. **critic-agent participates in every round** (dedicated critical thinking).
3. **pm-agent is called on every execution** (score gate + final verdict — past
   failure: pm agent was never called).
4. Round cap: base 3 + up to 2 extra when PM score <= 8 = **5 rounds total**.
   If score is still <= 8 after round 5, end with a conditional conclusion that lists
   unresolved items (no infinite loops).
5. Every review response is a single JSON object conforming to
   `schemas/pr_round_response.schema.json` (SubagentStop hook `pr_schema_check.py`
   validates and forces resubmission on violation).
6. All user-facing output (progress updates, final report shown to the user) MUST be
   in Korean. File paths, code elements, and JSON keys stay as-is.

## Phase 0 — Session Setup

```bash
python -c "
from pathlib import Path
import time
base = Path('output/peer_review_pr')
sid = time.strftime('%Y%m%d_%H%M%S')
(base / sid).mkdir(parents=True, exist_ok=True)
(base / '.active').write_text(sid, encoding='utf-8')
print('PR session: ' + sid)
"
```

Save `$ARGUMENTS` to `output/peer_review_pr/<sid>/task.md`
(if a file path was given, copy that file's content). All later context passing
references this file by path — never re-paste the task text into spawn prompts.

## Phase 1 — Agent Selection (full-roster evaluation, no count cap)

Read the frontmatter description of **every** `.claude/agents/*.md` file and judge
each agent individually as needed / not-needed for this task. Do NOT cap the
selection at any fixed number — the task's nature decides how many workers spawn.

- Mandatory participants regardless of judgment: critic-agent (every round),
  pm-agent (score + final verdict). These two are excluded from the worker verdict
  table (they are automatic).
- Record the verdict table in `output/peer_review_pr/<sid>/selection.md`:

| agent | verdict (needed / not-needed) | rationale (which part of the description matches or mismatches the task) |

Every agent file found in `.claude/agents/` must appear in the table — no omissions.
All agents judged "needed" spawn as workers.

## Phase 2 — Peer Review Rounds (base 1-3, each round is 2-stage)

**Each round is a 2-stage hybrid** (workers parallel → critic serial):

### Stage A — spawn workers in parallel (single message, multiple Agent calls)
- Round 1: each worker forms an **independent opinion** from task.md alone
  (parallel = prevents mutual anchoring).
- Round 2+: workers must respond to at least 2 points from other agents' prior-round
  JSONs via `feedback_addressed` — including at least 1 response to a critic-agent
  objection.

### Stage B — spawn critic-agent alone, serially
- Spawn critic-agent only AFTER all Stage A responses of the current round are saved,
  pointing it at the current round directory so it reads the just-produced worker
  responses.
- critic empirically verifies this round's worker claims and raises at least 2
  objections/risks.
- Round 2+: critic also uses `feedback_addressed` to evaluate worker responses to its
  own prior objections (accept or maintain; if rebutted, honestly record retraction).

### Round-common — file-reference context passing (constant prompt size)
Spawn prompts contain ONLY paths plus a <=3-line task summary. Never inline-paste the
task text or prior-round JSONs (token multiplication across agents x 5 rounds).
Every spawn prompt must include:
- path to `output/peer_review_pr/<sid>/task.md` (agent reads it with Read)
- current round number
- path to `schemas/pr_round_response.schema.json` + the required-field list:
  agent, round, stance(support|oppose|conditional), key_points(>=1), risks,
  consensus_ready(bool); round >= 2 additionally requires feedback_addressed
  (>=2 items of {to_agent, point, response})
- (round 2+) path to the previous round directory `output/peer_review_pr/<sid>/round_<N-1>/`
- instruction to end the reply with the single JSON object (hook-validated)

Save each response as `output/peer_review_pr/<sid>/round_<N>/<agent>.json`.
If an agent's JSON is missing, re-spawn that agent once in the same round
(if still missing, record it as absent).

**Early exit**: after Stage B, if all participants report `consensus_ready: true`,
proceed to Phase 3 even before round 3.

## Phase 3 — PM Score Gate

Spawn pm-agent (`subagent_type: "pm agent"`). The prompt includes:
path to task.md + paths to all round directories + the scoring rubric below.

**Scoring rubric (1-10)**:
- Consensus (0-3): all consensus_ready + degree of stance convergence
- Evidence quality (0-3): share of key_points backed by measured evidence (file:line)
- Objection handling completeness (0-2): response rate to critic objections +
  honesty of retract/maintain decisions
- Actionability (0-2): can the conclusion be translated into concrete actions

pm-agent output: `{"score": N, "gaps": [...], "verdict_draft": "..."}` — save with
score rationale to `output/peer_review_pr/<sid>/pm_score_round<N>.json`.

**Gate branch**:
- **score >= 9** → proceed to Phase 4.
- **score <= 8** → inject pm-agent's `gaps` list into the next round's prompts and run
  one more Phase 2 round (max 2 extra, 5 rounds total). At the cap, proceed to
  Phase 4 with a conditional conclusion.

## Phase 4 — Final Report (mandatory template — no section omissions)

Re-spawn pm-agent for the final verdict; the main session saves
`output/peer_review_pr/<sid>/final_report.md` and prints the full report to the user
**in Korean**.

```markdown
# /pr Final Report — <sid>
## 1. 참여 agents (선별 근거 + 호출 증빙)
| agent | 역할 | 선별 근거 | 호출 확인 (data/agent_activity.jsonl 대조) |
## 2. 비판적 사고 검증
- critic-agent 참여: YES (매 라운드) / 제기한 반론 총 N건 / 철회 M건
## 3. 상호 피드백 정량
- 왕복 라운드 수: N회 (기본 3 + 추가 K)
- feedback_addressed 총 건수: N건 (agent별 분해)
## 4. 합의 여부
- 최종 consensus_ready: X/Y agents / 미합의 항목: [...] / 소수 의견: [...]
## 5. PM 점수 이력 + 최종 판단
- 라운드별 점수: [...]
- 최종 판단: APPROVE | HOLD | REJECT + 근거
```

Invocation evidence must be built by cross-checking `data/agent_activity.jsonl`
entries from this session's time window (measured from logs, not claimed —
prevents PASS disguise).

## Phase 5 — Cleanup (try/finally semantics: runs even if Phases 2-4 fail)

History record first (main session runs this with actual values BEFORE deleting the flag):

```bash
python -c "
import json
from pathlib import Path
rec = {'sid': '<sid>', 'task_summary': '<40-char summary>', 'rounds': <N>, 'final_score': <score>, 'verdict': '<APPROVE|HOLD|REJECT>'}
with open('output/peer_review_pr/history.jsonl', 'a', encoding='utf-8') as f:
    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
"
```

Then flag removal + rotation:

```bash
python -c "
from pathlib import Path
import shutil
base = Path('output/peer_review_pr')
flag = base / '.active'
sid = flag.read_text(encoding='utf-8').strip() if flag.exists() else ''
# 1) delete .active flag (if left behind, other sessions' hooks misfire)
flag.unlink(missing_ok=True)
# 2) session directory rotation — keep latest 10 only (memory management);
#    history.jsonl keeps the permanent 1-line-per-session record
dirs = sorted([d for d in base.iterdir() if d.is_dir()])
for old in dirs[:-10]:
    shutil.rmtree(old, ignore_errors=True)
print('PR session closed: ' + sid)
"
```

---

Task to review: $ARGUMENTS
