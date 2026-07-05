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
6. Phase 13+ 설계 파악 필요 시: `grep "^## Phase 1[2-9]\|^### Phase 13" ROADMAP.md` 로 시작 라인 찾아 해당 섹션부터 EOF까지 읽기. (매 세션 자동 전체 로드 아님 — 필요 시만)
Read other files just-in-time, only when the task requires them.

## Tech Stack
- Python 3.x, GitHub Actions (14-stage pipeline), Telegram Bot API
- Test: pytest — run with `python -m pytest agents/tests/ -v`
- Regression baseline: 107+ PASS, ≤1 SKIP, 0 FAIL minimum. (현재 관측: 108 PASS, 0 SKIP, ~47초 — T23 환경 영향) Never merge below this. Push 전 반드시 로컬에서 `pytest agents/tests/ -v --tb=short -q -x` 실행 확인. (Phase 13-B-5에서 `regression_baseline.json` 신설 후 single source of truth 전환 예정)

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
2. `gh secret set KEY_NAME < key_file.txt` (GitHub Actions Secret — 값 직접 노출 금지)
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

## 보안 키 처리 규칙 (Do Not)

- API 키, 토큰, 패스워드 등 민감한 값을 bash 명령 인자, echo, print로 출력 금지
- 키값은 반드시 `.env` 파일에서만 읽어서 사용
- `gh secret set` 실행 시 키값을 터미널에 직접 입력 금지.
  반드시 파일 리다이렉션 사용:
  ```
  gh secret set KEY_NAME < key_file.txt
  # 또는
  cat .env | gh secret set KEY_NAME --env-file
  ```
- 검증 시 키 존재 여부만 확인 (값 출력 금지):
  ```
  gh secret list                                              # 이름만 표시
  python -c "import os; print('OK' if os.getenv('KEY') else 'MISSING')"
  ```

## Things to Avoid

**OL-8 (2026-07-04): Parser (HTML scrape) 와 Price Fetcher (API) 는 반드시 분리**

Root cause: `tools/consensus/naver_parser.py:619` 가 WiseReport `chartData2.close_price_series`
(**월별** 시계열) 에서 close_price_latest 를 뽑아 스냅샷에 저장. 최대 30일 lag → 7.7% stale
(2,628,000원 vs 실제 KRX close 2,425,000원). validation-agent 는 `data_freshness_report`
딕셔너리만 감사, 컨센서스 스냅샷은 커버리지 밖이라 감지 못함.

Mandatory rules:
1. **파서는 HTML 원본 데이터만** 반환. 파서 출력 필드명에 소스를 명시
   (예: `close_price_from_wisereport_chart`). 파서 안에서 "authoritative current"
   값을 결정하지 말 것.
2. **Authoritative current value 는 별도 fetcher 모듈이 API 로 획득**.
   KR: FinanceDataReader (KRX 공식), US: yfinance. Fetcher 는 파서와 다른 파일.
   레퍼런스: `tools/consensus/live_price_fetcher.py`.
3. **Snapshot writer 는 파서 → fetcher override 순으로 조립**. 파서 값은
   `<field>_from_<source>` 로 보존 (자기일관성 감사용), 최종 `<field>` 는
   fetcher 값 사용. 레퍼런스: `tools/consensus/consensus_pipeline.py` Step 2e.
4. **validation-agent 는 `output/consensus_snapshot/*_analysis.json` 을
   반드시 감사 스코프에 포함** — snapshot close vs live_prices.json diff > 5% WARN,
   > 10% CRITICAL. 신규 D-7 check (`_validate_consensus_close_freshness`).
5. **재발 방지 gate**: 새 컨센서스 필드 추가 시 "파서에서 계산 vs fetcher 에서 획득"
   결정을 문서화. 파서에 API 호출 코드 금지, fetcher 에 HTML 파싱 코드 금지.

See: `tools/consensus/live_price_fetcher.py`,
     `agents/run_validation_agent.py::_validate_consensus_close_freshness`,
     `tests/consensus/test_live_price_fetcher.py`.

**OL-7 (2026-06-30): Anti-confirmation-bias on extracted data + multi-source corroboration required**

Root cause incident: Phase 14-0-B2 parser extracted target_price = 2,470,417원 from
WiseReport's `chartData2` (historical monthly series, latest non-null = May 2026).
The static current-snapshot table held 3,177,083원 (June 2026 consensus). PM Agent
dismissed the static value as "비현실적" based on outdated price assumptions and
never reconciled the two sources. Cross-validation X1-X7 all PASSED because they
verified self-consistency (same source -> same value) rather than correctness
against an external anchor. User-provided ground truth (close = 2,628,000원)
revealed the error: PER * EPS = 8.54 × 307,655 = 2,627,374 ~= close (within
-0.02%), proving static-table values were correct and chart-based extraction was
the wrong source.

Mandatory rules going forward:
1. When multiple sources of the same field exist in one HTML / API response,
   parse all of them and explicitly choose the "authoritative current" source.
   Document the choice and flag any disagreement > 1% (numeric) or > 50%
   (semantic-gap signaling source mismatch).
2. Whenever PER, EPS, close are simultaneously extractable, enforce the
   invariant PER * EPS ~= close (within 1%) as an arithmetic-anchor check.
   Fail loudly when violated.
3. Never dismiss extracted numeric data as "wrong" based on prior assumptions.
   Required action before rejection: (a) check arithmetic invariants, (b)
   query an external anchor (user, FinanceDataReader for KOSPI/KOSDAQ, FRED,
   etc.), (c) compare against a second extraction path. Only after all three
   may a value be rejected, and the rejection must be logged with the reason.
4. Cross-validation matrices must include at least one EXTERNAL ANCHOR test
   (independent data source or human-provided ground truth) - pure
   self-consistency tests inflate confidence without proving correctness.

See: reports/phase_14_0_B2_14_1/rca_2026_06_30.md for full incident report.

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

**FIX-G (2026-06-23): pm_quality reader vs. real agent output 계약 불일치**
QN-1 (`agents/pm_quality.py:610-635`) 가 `narrative_context.json` 의 `narrative`/`report` 키를 읽지만,
`run_narrative_agent.py` 는 data-prep only 단계라 그 키들을 쓰지 않음 (헤더 L3-L8 명시).
QR-1 (`agents/pm_quality.py:121-145`) 도 `decision.json` 의 `reason`/`signal_score` 를 읽지만,
실제 필드는 `position_note`/`composite_score`. 둘 다 매 실행마다 advisory WARN → `pending_requests.json` 자동 누적.
Fix 패턴: 새 reader/QC 추가 전 `python -c "import json; print(list(json.load(open('output/<file>.json')).keys()))"` 로
실제 키 검증 + writer agent 헤더 docstring 확인. 회귀 테스트는 합성 fixture가 아니라 실제 파이프라인 출력 사용.
(메모리: [[operational-lessons]] OL-6)

**FIX-F (2026-06-13): stop_hook hook_input has no "transcript" array**
DO NOT call `hook_input.get("transcript", [])`.
Claude Code Stop hook sends `transcript_path` + `last_assistant_message`, NOT a transcript array.
`hook_input.get("transcript", [])` always returns `[]` → `_last_messages([])` → all checks SKIP.
Fix: Read `hook_input["last_assistant_message"]` for Check1 (Evidence).
     Open and parse the JSONL file at `hook_input["transcript_path"]` for Check2 (level scan).
(confirmed production 2026-06-12, stdin_debug.txt verified)

## AgentMemory Recall 규칙
세션 시작 시 실행:
  memory_smart_search("AI Analyzer pipeline ROADMAP")
  memory_smart_search("tf-design-process")
  memory_smart_search("aprf-design-process")  # legacy tag (2026-06-27 저장된 4 lesson)
(project 필드는 전체 경로라 facet_query 미지원 — smart_search 방식 사용)

## Post-Push Deployment Verification (2026-07-04 사용자 명시 — 영구)

**매 `git push` 후 필수 실행**:
```powershell
$SHA = git rev-parse HEAD
# 로컬 파일이 이미 pull 된 상태면 기본
python scripts/verify_push_deployment.py --sha $SHA --wait-min 20
# 사용자 로컬이 아직 pull 안 됐거나 원격 파일만 검증 원할 때
python scripts/verify_push_deployment.py --sha $SHA --wait-min 20 --remote
```

**exit 0 확인 후에만 사용자에게 "배포 완료" 보고 가능**.
exit non-zero 면 즉시 실패 workflow / endpoint / freshness 원인과
사용자 조치 필요 항목을 알림.

### 검증 6 항목 (모두 통과해야 완료)
1. GitHub Actions API: SHA 로 트리거된 **ALL workflows** conclusion == success
   (primary deploy 만 확인 = PASS 위장 패턴)
2. Pages URL HTTP 200
3. Pages 콘텐츠에 예상 sentinel 존재 (end-user 관점)
4. `output/*.json` freshness (generated_at ≤ 24h)
5. 실패 시 workflow name + conclusion + URL 명시 (actionable)
6. 정직 보고 — 성공 요약이 아니라 "모든 workflow / 모든 endpoint / 모든 데이터" 상세

### 스크립트 exit codes
- 0 = 모든 workflow 성공 + content OK + freshness OK
- 2 = workflow failure (사용자 조치 필요)
- 3 = poll timeout (완료 안 됨)
- 4 = content 검증 실패 (Pages HTTP 오류 or sentinel 부재)
- 5 = freshness 실패 (데이터 stale)

### 절대 금지 (라운드 16 directive)
- 스크립트 미실행 후 "완료" 보고 = PASS 위장
- primary deploy 만 확인 후 "성공" = 편향 감시
- Content endpoint 확인 없이 "정상" = end-user 관점 무시
- 여러 workflow 중 하나만 성공이어도 "배포 완료" = 부분 진실 위장

## Agent Team Cross-Validation 룰 (2026-06-29 사용자 명시 — 영구)

**어떤 작업도 'PASS / 완료' 표기 전 별도 agent 독립 검증 필수.**

표준 흐름:
1. **Claude Code main session 구현** (코드/문서 작성)
2. **audit-agent spawn** — 명세-구현 일치 + evidence 적합성 + 의미 정확성 독립 검증 (grep/Bash/Read 사용)
3. **pm-agent spawn** — audit 결과 평가 + priority/architecture 비판 + action plan 수립
4. **main session action plan 실행** (PM 자율 룰 commits ≤ 3 적용)
5. **audit-agent 재spawn** — 최종 재검증
6. **사용자에게 결과 보고**

**원칙**:
- 사용자 micro-orchestration 불요 — agent team 이 cross-check + 최적안 제시 후 실행
- 크로스체크 프롬프트도 agent 가 생성 (main session 이 pre-script 안 함)
- 'PASS without independent verification = 자기보고 위장' = FP-001/FP-002 패턴 재발
- 매 DC PASS 표기 / 매 commit 전 이 패턴 적용

근거: lesson `lsn_e7bd79d1` (AI 자기 라벨 금지) + 라운드 14 'Level 6-7 수준 검증' 회피.

## Peer Review Skill (/pr)
- 호출: `/pr <리뷰할 내용>` — worker 선별(전수 평가) + critic-agent(비판 전담) + pm-agent(점수·최종 판단) 필수.
- 왕복: 기본 3회 + PM 점수 8점 이하 시 추가 최대 2회 (총 5회 상한, 이후 조건부 결론).
- general-purpose/Explore 페르소나 사용 절대 금지 — `.claude/agents/` named agent 만.
- 산출물: `output/peer_review_pr/<sid>/` (최근 10 세션 회전), 영구 이력 `history.jsonl`.
- 스펙: `.claude/skills/pr/SKILL.md`, 스키마 `schemas/pr_round_response.schema.json`.
- **모든 작업 완료 최종 보고는 /pr Final Report Standard 를 따른다** — SKILL.md 의
  "Final Report Standard & Self-Improving Review Loop" 섹션이 single source of truth (템플릿 중복 금지).
- /pr 미실행 시에도 동일 형식으로 보고하고 "/pr 실행 불가"를 명시. 관련 agents/hooks 가
  실제 실행되지 않았으면 peer review 완료 주장 금지 — 필수 구성요소 부재 시 HOLD.
- 미검증 항목 PASS 표기 금지 — 결정론적 evidence 없으면 HOLD/RISK 로 표기.

## AgentMemory 운영 원칙
- TF 관련 신규 lesson 태그: `tf-design-process`
- 기존 4 lesson 태그: `aprf-design-process` (legacy, 현재 알려진 호출로는 갱신 불가)
  이유: `memory_lesson_save`는 same-content 시 tag 갱신 없이
  confidence만 strengthen — 시스템 한계 (2026-06-28 1회 실측, N=1, 추가 워크어라운드 미검증)
- 한계 우회: content 미세 변경 + 신규 tag → 신규 lesson 생성 (검증 필요)
- lesson 저장 시 tag 필드에 `tf-design-process` 명시 필수
