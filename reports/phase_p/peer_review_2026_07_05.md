# Phase P Methodology Peer Review — 2026-07-05

3 독립 에이전트 병렬 peer review 결과 요약. 프롬프트 `prompts/phase_p_purpose_return.md`
정량 기준의 실행 가능성 검증.

## 공통 결론 (수렴 발견)

- 실제 daily pipeline commit **N=12** (2026-06-19 → 2026-07-04).
  프롬프트의 "15" 는 weekly commit 3개 포함한 착시. P-1 N≥30 요건 미달.
- 오늘(2026-07-05) 기준 forward window 가용성:
  - **20d forward: 0 스냅샷** (P-3 20d, P-2 20d 오늘 실행 불가)
  - **10d forward: 0 스냅샷**
  - **5d forward: 최대 6 스냅샷**
- **P-4 만 오늘 완전 실행 가능** — 과거 시그널 → 과거 종가, forward window 불필요.
- **P-2 프롬프트 정의는 tautological** — 과거 249일 contribution vs 같은 날 contribution 은 자기일치.
  forward-window 재정의 필요.

## Analysis-Agent 결론 (BLOCK_UNTIL_METHODOLOGY_FIX)

- N=15 → one-sided binomial α=0.05 에서 검출 가능 hit rate 12/15=80%. Type II > 90%.
- Bootstrap 은 정보 추가 없음. Per-indicator pooling (13×15×20 ≈ 3900 obs) 는
  Newey-West lag=20 + snapshot-block bootstrap 시에만 유효. Effective N ≈ 54.
- Minimum viable pooled N ≈ 60. **권장: Q4 2026 (~90 daily snapshots) 까지 P-1 defer.**
- P-1 PIT 리스크: 249일 lookback 이 T+20 예측 window 와 중복 → López de Prado
  purge-and-embargo 필요 (ranking refit 시 t-20 까지만 사용).
- P-2 tautology 확정. 정정: precision@5 = snapshot Top5 ∩ t+1..t+20 실제 Top5.
  Chance baseline ~1%/slot → precision@5 > 15% 이상만 유의미.
- P-3 forward return 바이어스: 스핀오프(SNDK, WDC) 는 pre-split 가격 없음 → forward
  return 인위 상승. MU +694% 는 momentum reversal 후보.
  **Exclusion filter (pre-registered)**:
  - <180 days continuous price history 제외
  - past 1y return 99th percentile winsorize (~+200%)
  - warn_reason 존재 티커 제외
- P-4 benchmark asymmetry: SELL/HOLD→cash 시 up market 에서 mechanical underperform.
  Fair null: (a) 50/50 constant-mix, (b) β-matched buy-and-hold, (c) Sharpe primary.
  N=15 → Sharpe SE ≈ 1.6 → **서술 지표로만 취급**.

## Evaluator-Agent 결론 (ACCEPTABLE with fixes)

- Multiple testing: 2 groups × 2 indices × 3 horizons = 6 tests.
  Holm-Bonferroni family α=0.05. Primary = 20d S&P500 single α=0.05. 나머지 5개 secondary.
- P-4 confidence gate variants pre-register:
  - unconditional (all BUY)
  - `confidence_pct ≥ 60` (기존 evaluator MEDIUM 등급 대응)
  - `confidence_pct ≥ 70` (sensitivity)
- FP-001 방지 규칙: **모든 threshold/α/horizon 를 코드 실행 전 pre-registration JSON 에 freeze**.
  Runner 는 `frozen_at` 존재 + `git_sha_at_freeze` HEAD ancestor 검증 후 실행. 실패 시 exit(1).
- HOLD/neutral 처리: **carry-over prior position** (forced cash 아님).
  거래비용 0.1% 는 state transition 에만 부과.
- Self-reference 회피 evaluation signal:
  1. Independent fetcher forward returns (yfinance/FDR, OL-8 fetcher pattern)
  2. Snapshot-to-snapshot cross-check (D → D+next_snapshot 실현 contribution)

## Audit-Agent 결론 (feasible-with-caveats)

- 12 daily pipeline commits 실제 검증. 모두 `output/decision.json` + `output/final_results.json` 포함.
- Reusable tooling:
  - `stage_engine/backtest_h1.py` — pre-registered gate, block bootstrap, benchmark logic → P-1 skeleton
  - `stage_engine/data_loader.py` — 가격 loader
  - `tools/consensus/live_price_fetcher.py` — OL-8 fetcher (authoritative close)
- External anchor (OL-7) 4개 모두 확보: yfinance / FinanceDataReader.
- Level 8 evidence path: exit code + printed `CUM=...` `SHARPE=...` `MDD=...` + real snapshot regression test.
- Infra boundary rule: CI/hooks/scheduled 트리거 항목만 "infra". `scripts/`, `stage_engine/` 하 one-shot 은 "analysis". → Phase P 는 `scripts/phase_p_*` 허용.
- 인코딩 hazard: Korean 문자열 파싱 시 반드시 `encoding="utf-8"` 명시.

## 사용자 결정 (2026-07-05)

- 실행 범위: **P-4 완전 실행 + P-1~P-3 descriptive-only** (n=6, non-inferential 명시)
- Pre-registration file: **freeze 후 코드 작성**

## 다음 단계

1. `output/phase_p_preregistration.json` 작성 → 커밋 (git_sha_at_freeze 기록)
2. `scripts/phase_p_backtest.py` 작성 (runner gate 로 pre-reg 검증)
3. P-4 실행 → 실제 수치 리포트
4. P-1/P-2/P-3 descriptive-only 산출
5. `output/backtest_report.md` 작성
6. 회귀 테스트 추가 (실 스냅샷 기반, FIX-G 준수)
