# AI Analyzer ROADMAP

## 현재 Active Phase
- 🚧 Phase 13-B: TF v3.4 구현 — 착수 대기 (설계 v3.4 확정 2026-06-27, 13-B-1부터 코딩 진입 가능)
- 🆕 Phase 14-0-A1: Consensus Revision Tracker — Static Source Access Audit (mock-only, zero-network). 다음 단계 Phase 14-0-A2 정적 robots/terms 분석, Phase 14-0-B1 live policy audit (opt-in).
- ⏸️ Phase 11-A: Narrative Spawn — 선행조건 ✅ (Phase 12-1 완료 2026-06-21, c40c7dc) / 우선순위: Phase 13-B 완료 후
- ⏸️ Phase 11-B: Audit Spawn — 선행조건 ✅ (Phase 12-1 완료 2026-06-21, c40c7dc) / 우선순위: Phase 13-B 완료 후 (11-A와 병렬 가능)
- 🗄️ Phase 10: CTD 브리지 — 별도 레포, 보류

> **완료된 Phase 기록**: [ROADMAP_HISTORY.md](./ROADMAP_HISTORY.md) — Phase 1-9, 11(main), 12 + Agent Teams 현황 + Orchestrator 실행 지침 + REQ-KITA-001

## 전체 비전 (5대 목표)
1. **AI 데이터 분석 대시보드 자동화** — 핵심 지표 AI 분석 → 직접 매수/매도 의사결정
2. **AI 반복 리포팅·분석 자동화** — 주 1회 자동 파이프라인, ntfy.sh 알림, AI 언어 리포트
3. **BI 대시보드로 의사결정 설득** — Looker Studio + GitHub Pages 시각화
4. **주식 산업·직무별 데이터 딥다이브** — 반도체/AI/에너지 섹터, 코스피/S&P500 동시 분석
5. **실무 AI 데이터 분석 도구 완성** — hook 기능으로 PM Agent가 승인할 때까지 LOOP 실행

## PM Agent 승인 조건 (A~H)
- [x] A) 코스피 종목 ±200% 초과 수익률 — FDR(KRX)+yfinance 교차검증 적용
- [x] B) 복합 시그널 점수(0~100) + 방향성 — Z-score 가중 합성, risk-on/neutral/risk-off
- [x] C) BI 시각화 접근 링크 — https://hwangatwork.github.io/AI-Analyzer/ (GitHub Pages 자동 배포)
- [x] D) 주 1회 자동화 파이프라인 — Task Scheduler + GH Actions cron 0 22 * * 0 + ntfy.sh
- [x] E) BUY/SELL/HOLD 의사결정 엔진 — 신뢰도%·포지션 사이징·진입/청산 트리거 (Decision Agent)
- [x] F) AI 언어 인사이트 + 액션플랜 — 한국어 자동 리포트, S&P500+코스피 실행 계획 (Narrative Agent)
- [x] G) CSV → Google Sheets → Looker Studio 파이프라인 — gspread 자동화 + GitHub Pages CSV URL (Sheets Agent)
- [x] H) 산업별 딥다이브 — 반도체/AI·AI플랫폼·에너지/원자재, 21개 종목 1Y/1M 수익률 (Sector Agent)

---

## 실행 방법
Claude Code에서 이 파일을 읽고 Agent Teams를 생성한다.
[ ] = 자동 실행, [?] = 대표님 확인 필요, [x] = 완료

---

---

## 현재 시스템 상태

| 항목 | 상태 |
|------|------|
| pm_quality_checks | 24/24 PASS (QG-1 SKIP 포함) |
| 회귀 테스트 | **77 PASS, 1 SKIP, 0 FAIL (~63초)** — source: CLAUDE.md "Regression baseline" 라인 (실측 2026-06-27). Phase 13-B-5 후 `regression_baseline.json` single source 전환 |
| 6-Layer 재감사 | **62/62 PASS** (L1:12 L2:12 L3:17 L4:8 L5:5 L_방법론:8) |
| SA 구조 감사 | SA-1~**SA-9** 자동 실행 (SA-9 신규: 에이전트 명세 완비 감사, 나머지 INFO) |
| 자율 개선 루프 | 폐쇄 루프 활성 — 파이프라인→SA→pending_requests 자동 등록 |
| 주간 감사 | `--weekly-audit` 플래그 + 일요일 자동 트리거 |
| stop_hook | FIX-A~F 완료 — Check1/Check2 실전 PASS 확인 |
| PIPELINE_STAGES | 14단계 (narrative 포함) |

### 미결 항목 (backlog / waiting)
| ID | 내용 | 상태 |
|----|------|------|
| REQ-SA4 | refresh_data.py Done Criteria 구현 완료 (DC-1~DC-5) | **완료** (2026-06-13) |
| REQ-SA2 | run_ui_agent.py:generate_html_dashboard() 226L | backlog |
| REQ-003 | Google Sheets 자동화 | waiting_credentials |
| REQ-004 | Notion 연동 | waiting_credentials |
| REQ-FUTURE-001 | 코스피100→코스피200 유니버스 확장 | backlog |


---

## Phase 10: CTD 브리지 연결

### ctd_bridge.json v4 스키마 업데이트

- [ ] 현재 브리지 파일 스키마 확인 (구버전: BBAND #1)
- [ ] 현재 시스템 스키마 확인 (현재: VIX #1)
- [ ] ctd_weights.json + ctd_bridge.json v4 스키마로 업데이트
- [ ] CTD 웹앱에서 정상 표시 확인
- [ ] Telegram 보고 + git push
<!-- STOP: connecting-dots-ctd 별도 저장소 — AI-Analyzer에서 실행 불가 (2026-06-13) -->

---

## Phase 11-A: Narrative Agent Spawn 전환

배경: run_narrative_agent.py L365 주석이 이미 "Claude Code 서브에이전트 수동 실행" 전제 —
      자동 Spawn 전환이 설계 의도와 일치.
선행조건: Phase 12-1 완료 ✅ (2026-06-21, c40c7dc) — 우선순위: Phase 13-B 완료 후 착수

- [ ] Task 1 — run_narrative_agent.py L365 주석 확인 및 Spawn 진입점 정의
- [ ] Task 2 — pm_orchestrator.py에 Group E 추가 (_run_group_spawn 함수 구현)
- [ ] Task 3 — narrative_context.json → FINAL_REPORT.md 생성을 서브에이전트가 완전 자동 처리하도록 수정
- [ ] Task 4 — _verify_output_contract() Spawn 완료 후에도 동일하게 실행 (계약 준수 감시)
- [ ] Task 5 — failure_memory 연동: Spawn exit code → _record_failure()/_record_success() 호출
- [ ] Gate — FINAL_REPORT.md 자동 생성 + 수치 포함 여부 검증 + 회귀 테스트 PASS

## Phase 11-B: Audit Agent Spawn 전환 (선택)

배경: 파이프라인 최종 게이트 — 감사 실패가 다른 단계에 오염되지 않도록 독립 격리 실행.
선행조건: Phase 12-1 완료 ✅ (2026-06-21, c40c7dc) — 우선순위: Phase 13-B 완료 후 착수 (11-A와 병렬 가능)

- [ ] Task 1 — run_audit_agent.py Spawn 진입점 정의 (audit_report.json 계약 명세)
- [ ] Task 2 — pm_orchestrator.py Group E에 Audit 추가 (Phase 11-A 완료 후 병행)
- [ ] Task 3 — Spawn 결과(APPROVE/HOLD)를 pm_orchestrator.py 최종 판정 로직에 자동 연결
- [ ] Task 4 — failure_memory 연동 및 Telegram 보고 유지
- [ ] Gate — audit_report.json 생성 + APPROVE/HOLD 자동 판정 전달 + 회귀 테스트 PASS

---

## Phase 13 — Agent Peer Review Framework

### 배경
2026-06-27 세션에서 사용자가 agentmemory recall로 5개 신호 식별 → PM Agent가 개선안
제시 → 13명 워커 에이전트(PM 제외)가 각자 도메인 관점에서 동의/반대/보강 의견 제출 →
컨센서스 매트릭스 + 새 발견 + 시급성 재투표로 집계. 이 다단계 협의 과정이 일회성이
아니라 반복 적용 가능한 프레임워크로 굳혀져야 한다는 사용자 결정.

핵심 효과 (2026-06-27 1회 실측):
- PM의 mtime+키 검증 제안이 6 agent로부터 "RC-3c류 위장 못 잡음" 반박 → 보강 5건 추가
- PM이 "가장 시급=신호 5"로 골랐으나 sector·meta-audit는 신호 1, audit는 신호 3 →
  PM 자기 진단의 사각지대 노출
- agent별 1차 방어선·CPCV·schemas·의존성 정밀화 등 PM 보고서에 없던 5개 항목 신규 발굴

### Phase 13-A: 2026-06-27 세션 기록 (record-only)

- [x] 신호 1: FP-001/002 (PM 완료 보고 신뢰성) — mtime+키만으로 위장 못 잡음 컨센서스 (6/13)
- [x] 신호 2: 규칙 우선순위 (user_override > validation HOLD > baseline auto-proceed)
- [x] 신호 3: 분석 회귀 — `cross_validate_return()` grep 0건 / Granger stationary 미검증 / confidence all_inds 적용
- [x] 신호 4: 최소 5개 게이트 — `ctd_ready` boolean → `sys.exit(1)` + 카테고리 다양성 ≥3 보강 요구
- [x] 신호 5: CI 함정 — `.github/workflows/deploy-dashboard.yml:94-96` `if: always()` 제거
- [x] 13-agent 의견 수집 (data, analysis, evaluator, validation, decision, stock, sector, news, narrative, ui, report, audit, meta-audit)
- [x] 신규 5개 발굴:
  - data-agent: zero-fill 시계열 검증 → `_verify_no_zero_fill()` 신설
  - analysis-agent: CPCV + Deflated Sharpe (TSS+IC 단일분할 누설 위험)
  - news-agent: agent별 1차 방어선 (article ≥5, source ≥3)
  - narrative-agent: `schemas/narrative_context.schema.json` 키 계약 고정 (FIX-G 재발 방지)
  - stock-agent: f09(기여도)는 evaluator 독립 → 의존성 그래프 정밀화
- [x] 시급성 재투표 결과: 신호 5 (3표 validation/ui/report) vs 신호 1 (2표 sector/meta-audit) vs 신호 3 (1표 audit)
- [x] 사용자 결정: 5개 신호 진행은 보류, 프레임워크 아키텍처화 우선

### Phase 13-B: TF v3.4 구현

#### 배경
2026-06-27 8라운드 비판적 설계 리뷰로 확정된 TF v3.4.
PM Agent가 혼자 분석을 완결하는 패턴 방지.
13개 에이전트가 서로 검토하는 구조.

설계 진화 이력 (v1 → v3.4):
- v1: SUBAGENT only, 코드 retry
- v2: Dual mode (SUBAGENT + TEAM) 도입
- v3: Hook 시스템 발견 — SubagentStop/PostToolBatch/SessionEnd로 인프라 대체
- v3.1: Windows + PowerShell 제약 반영 (in-process only, Python 통일)
- v3.2~3.4: regression baseline 처리, label 자기서명 폐기, scope 축소

#### 아키텍처 결정 (확정)
- (Hook schema 강제): SubagentStop hook exit 2 → schema 강제 (코드 retry 폐기)
- (Hook aggregator): PostToolBatch hook + `additionalContext` → aggregator (별도 모듈 X)
- (Memory loop): SessionEnd → `memory_lesson_save` → 다음 세션 자동 recall
- (Hook 등록): SubagentStop hook은 `settings.json` regex matcher로 중앙 등록 (Anthropic 공식 지원 2가지 방식 — settings.json 중앙 / agent MD frontmatter 분산 — 중 전자 채택). 유지보수성 우선: hook path 변경 시 1줄 수정 vs 13 MD 수정.
- (Windows 제약): TEAM 모드는 Phase 13-D로 분리
- (Regression 위임): DC-7 삭제 → stop_hook.py / SA-8 / pm_quality_checks에 위임

#### Tasks (순서대로)

- [x] Phase 13-B-1: Schema 파일 2개 신설 (완료 2026-06-28, commit 4a83954)
  - `schemas/peer_review_response.schema.json`
  - `schemas/peer_review_concerns.schema.json`
  - 완료 기준: DC-1 (pytest fixture로 schema 유효성 확인) ✅ 88 PASS / 0 FAIL / 53초

- [ ] Phase 13-B-2: Hook 4개 구현
  - `.claude/hooks/tf_aggregate.py` (PostToolBatch)
  - `.claude/hooks/tf_schema_check.py` (SubagentStop)
  - `.claude/hooks/tf_debate_force.py` (TeammateIdle, TEAM 전용)
  - `.claude/hooks/lesson_save.py` (SessionEnd)
  - 모든 hook은 Python 스크립트로 통일 (.cmd/.bat 금지)
  - command + args exec form 사용 (Windows-safe)
  - 완료 기준: DC-4, DC-5

- [x] Phase 13-B-3: `/tf-review` slash command + `.active` lifecycle (완료 2026-06-29)
  - **C안 채택** — subprocess에서 Task tool 호출 불가능 architectural constraint 회피
  - `.claude/commands/tf-review.md` — 5-Step 워크플로 (set_active → save proposal →
    Task spawn × 13 (단일 메시지 병렬) → clear_active → aggregate read)
  - `agents/tf_active.py` — set/clear/is/get 헬퍼 (slash command + pytest 양쪽 사용)
  - `.claude/settings.json` env 블록: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
  - 완료 기준: DC-2 재정의 — command 파일 존재 + .active lifecycle 검증

- [ ] Phase 13-B-4: 13개 에이전트 MD 업데이트 (**scope 제약: 2026-06-29 결정**)
  - 각 MD에 `## Peer Review Concerns` **1 섹션만 추가** (body)
  - 각 MD frontmatter에 `hooks.SubagentStop` 추가 — DC-4 settings.json 중앙 등록으로 대체됨, 불요
  - **OWASP 체크리스트 / `## Contract` JSON 추가 금지** — Phase 14로 분리
  - 근거: pm-agent (2026-06-29) catch — scope creep 회피, 단일 자율 블록 commits ≤ 3 보존
  - 완료 기준: DC-3, DC-8

- [ ] Phase 13-B-5: 기존 파일 연동
  - `agents/pm_orchestrator.py`: `_invoke_peer_review()` 추가
  - `agents/pm_quality.py`: QC-27 추가
  - `stop_hook.py`: Telegram digest 확장
  - `pending_requests.json` 스키마 확장 (`source: tf` 필드)
  - `regression_baseline.json` 신설 (병합 시점 `pytest agents/tests/ -v --tb=short -q` 실측값으로 초기화. 이후 사람이 명시적으로 갱신)
  - 완료 기준: DC-9, DC-10, DC-11

- [ ] Phase 13-B-6: 테스트 + 검증
  - `agents/tests/test_peer_review.py` 작성
  - 전체 pytest PASS (실측 2026-06-27: 77 PASS / 1 SKIP / 63초, TF 신규 추가 후 78+ 목표)
  - dogfood run 1회 실행
  - 완료 기준: DC-6, DC-7 (위임)

- [ ] **Phase 13-B-7: AI Harness Hardening** (신설 2026-06-29) — pm-agent 비판 + AI Harness v6.0 분야 재조사 후 도출된 critical gap 처리

  **13-B-7-1: bypassPermissions deny list 추가** (Tier 1 즉시)
  - settings.json deny 패턴 추가:
    - `Bash(git push --force *)` / `Bash(git push -f *)` (force push 차단)
    - `Bash(gh secret set *)` (secret 노출 차단)
    - `Bash(rm -rf *)` (destructive 차단)
    - `Write(.env)` (credential overwrite 차단)
  - 완료 기준: settings.json git diff + pytest 108 PASS 유지
  - 근거: AI Harness 원칙 6 (안전장치) + bypassPermissions 유지하면서 high-risk만 selective deny

  **13-B-7-2: tf_schema_check.py 확장 — 실측 layer**
  - agent별 `tools_used` / `runtime_sec` 측정 + 로그
  - `output/peer_review/<session>/metrics/<agent>.json` 기록
  - **강제는 다음 phase, 측정 먼저** (pm-agent: "강제 layer 먼저, contract 나중" 권고)
  - 완료 기준: 13 agent dogfood 후 metrics 파일 13건 생성 확인
  - 근거: 12-Metric Framework (Agent Behavior / Production Health 측정)

  **13-B-7-3: 🔴 Level 8 동적 게이트 도입 (진짜 CRITICAL)**
  - 배경: FIX-G + 라운드 14 *"DONE_CRITERIA: PASS 위장"* 실패 패턴 보유 = 우리 환경 입증 결함
  - `regression_baseline.json` 에 DC별 evidence 필드 신설:
    ```json
    {
      "dc_evidence": {
        "DC-N": {"level_claimed": 8, "evidence_files": [...], "dynamic_test_log": "..."}
      }
    }
    ```
  - `pm_quality.py` QC-29 신설:
    - DC Level ≥ 8 표기 + evidence 빈 경우 CRITICAL 알림
    - Telegram 즉시 보고
  - 기존 DC-1~11 backfill (evidence 수집 또는 N/A 명시)
  - 완료 기준: pytest QC-29 회귀 5+ PASS + 모든 PASS 표기 DC의 evidence 보유
  - 근거: AI Harness 원칙 2 (Runtime > design intent) + 메타 원칙 3 (Behavioral Contracts 강제)

  **Phase 13-B-7 진행 순서**: 13-B-7-1 (5분, 즉시) → 13-B-7-3 (2시간, CRITICAL 다음) → 13-B-7-2 (1시간, 마지막)

#### Done Criteria

- [ ] DC-1: schema fixture 유효성 확인
- [x] DC-2: `/tf-review` slash command 등록 + `.active` lifecycle 동작 (재정의 2026-06-29) — **PASS (static, dogfood pending DC-6)**. 원안 `peer_review.py --dry-run`은 architectural impossibility로 폐기 (Task tool은 subprocess에서 호출 불가) → C안 채택: `.claude/commands/tf-review.md` slash command + `agents/tf_active.py` 헬퍼. 정직성: 정적 검증 (file 존재 + lifecycle helper pytest)만 완료, 13 Agent 실 spawn + hook lifecycle 동적 검증은 DC-6 (manual dogfood) 책무.
- [ ] DC-3: 13개 에이전트 MD "Peer Review Concerns" 섹션 존재 (audit-agent grep)
- [x] DC-4: SubagentStop hook 등록 ✅ (commit 392ed66) — `settings.json` regex matcher 방식 채택 (`^(data|analysis|...)-agent$`). Anthropic 공식 2가지 방식 (중앙/분산) 중 유지보수성 우선으로 중앙 등록. 분산(MD frontmatter)도 동등 지원이나 미채택.
- [x] DC-5: `tf_aggregate.py` → aggregate.md 4섹션 생성 ✅ (commit 49f8821)
       주의: PostToolBatch는 matcher 미지원 → 모든 parallel batch에서 firing.
       `.active` 플래그 gate로 TF 외 호출 차단 + hook 내부 schema validation으로
       corruption 위험 0 (defensive code). 단 Phase 13-B-3에서 `.active` lifecycle
       정밀 제어 필수 (TF 13 reviewer spawn 직전 set / 완료 직후 unset).
- [x] DC-6: 재정의 2026-06-29 (옵션 6a) — 원안 `test_peer_review.py PASS`는 architectural 한계로 폐기 (slash command를 subprocess pytest로 dogfood 불가, C안 결정과 같은 근거). 합쳐서 처리: 정적 부분 = `agents/tests/test_tf_review_command.py` (7 PASS, 이미 commit 4a83954 등에 포함, file/lifecycle/keyword 검증). 동적 부분 = manual dogfood (Claude Code 세션 내 `/tf-review <proposal>` 실 호출 + aggregate.md 출력 확인). 자동 회귀 불가, 사람 1회 검증.

### DC 우선순위 노트 (2026-06-29 결정)
1. **DC-3, DC-8** 먼저 — 13 MD body section 추가 + audit-agent grep gate. 완전 자동화 가능, ROI 명확.
2. **DC-9, DC-10, DC-11** 다음 — Python 코드 (hook + QC + digest), 단위 테스트 가능.
3. **DC-6 manual dogfood** 최후 — 위 모두 정적 충족 후 1회 사람 검증.

(pm-agent 권고 "DC-6 ROI 최고" 는 DC-6 자동화 불가 architectural constraint 미고려 — 정정.)
- [ ] DC-7: 회귀 검증 stop_hook.py / SA-8 / pm_quality에 위임 (별도 gate 없음 — 결정 명시)
- [ ] DC-8: audit-agent grep gate 확인
- [ ] DC-9: `memory_lesson_save` SessionEnd hook 성공 호출
- [ ] DC-10: `stop_hook.py` Telegram digest TF 요약 포함
- [ ] DC-11: `pm_quality.py` QC-27 동작 확인

### 실행 규칙
- 13-A는 record-only (이미 완료)
- 13-B-1부터 순차 실행 (schema → hook → 본체 → MD → 연동 → 테스트)
- 각 Phase 완료마다 `pytest agents/tests/ -v --tb=short -q` 실행 (~63초), 기존 77 PASS / 1 SKIP / 0 FAIL 유지 확인
- hook은 모두 Python 스크립트, `command + args` exec form 사용 (Windows-safe)
- TEAM 모드 코드 포함하되 env var 없으면 SKIP 처리
- TEAM 모드 실측은 Phase 13-D로 분리
- 5개 신호(13-A) 자체의 구현은 별도 Phase로 분리 (지금 시작 금지)
- GitHub Actions CI ratchet/gate 인프라(obj-r4-1, r4-2, r5-1, r5-2)는 별도 Phase 13-E 또는 폐기 — 사용자 결정 대기

## Phase 13-C — 명세 자동 보완 사후 검토 (16 agent MD, 백로그)

REQ-SA9 series 16 items 일괄 이관 (2026-06-30). 각 agent MD 의 AUTO-GENERATED 섹션
("Role / Execution / Done Criteria") 내용 검토 + 채택/거절. 우선순위 낮음 (advisory).

- 처리 방식: 사용자 ad-hoc review, batch 자동 처리 없음
- 의도 메타데이터: `pending_requests.json` 의 `request` / `details` 필드에 보존
- 완료 기준: 16건 모두 closed (accept / reject 표기)

**대상 16 IDs**:
- `REQ-SA9-analysis-agent`, `REQ-SA9-audit-agent`, `REQ-SA9-data-agent`,
- `REQ-SA9-decision-agent`, `REQ-SA9-evaluator-agent`, `REQ-SA9-meta-audit-agent`,
- `REQ-SA9-narrative-agent`, `REQ-SA9-news-agent`, `REQ-SA9-orchestrator`,
- `REQ-SA9-report-agent`, `REQ-SA9-sector-agent`, `REQ-SA9-stock-agent`,
- `REQ-SA9-ui-agent`, `REQ-SA9-validation-agent`, `REQ-SA9T-evaluator-agent`,
- `REQ-SA9-pm-agent`

근거: title/created_at 메타데이터 없이 backlog 누적 → 매 세션 stop_hook digest 노이즈.
batch close 가 의도 정보 손실 0 (request 필드 명확) + pending count 부담 -16.
