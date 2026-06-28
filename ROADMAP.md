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
- (MD 분산): 각 에이전트 MD가 자기 SubagentStop hook 보유
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

- [ ] Phase 13-B-3: `agents/peer_review.py` 구현
  - `dispatch(report, scope)` → SUBAGENT mode
  - `_spawn_subagents(agents, prompt)` → Task() × 13 병렬
  - 완료 기준: DC-2 (`--dry-run` exits 0)

- [ ] Phase 13-B-4: 13개 에이전트 MD 업데이트
  - 각 MD에 "Peer Review Concerns" 섹션 추가 (body)
  - 각 MD frontmatter에 `hooks.SubagentStop` 추가
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

#### Done Criteria

- [ ] DC-1: schema fixture 유효성 확인
- [ ] DC-2: `peer_review.py --dry-run` exits 0
- [ ] DC-3: 13개 에이전트 MD "Peer Review Concerns" 섹션 존재 (audit-agent grep)
- [ ] DC-4: 13개 에이전트 MD frontmatter `hooks.SubagentStop` 존재
- [x] DC-5: `tf_aggregate.py` → aggregate.md 4섹션 생성 ✅ (commit 49f8821)
       주의: PostToolBatch는 matcher 미지원 → 모든 parallel batch에서 firing.
       `.active` 플래그 gate로 TF 외 호출 차단 + hook 내부 schema validation으로
       corruption 위험 0 (defensive code). 단 Phase 13-B-3에서 `.active` lifecycle
       정밀 제어 필수 (TF 13 reviewer spawn 직전 set / 완료 직후 unset).
- [ ] DC-6: `test_peer_review.py` PASS (team tests SKIP if env var unset)
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
