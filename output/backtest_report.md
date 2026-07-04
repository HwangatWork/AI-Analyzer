# Phase P (Purpose Return) — Backtest Report

Generated: 2026-07-05
Pre-registration freeze SHA: `77b13c6e8b72` (`output/phase_p_preregistration.json`)
Peer review: `reports/phase_p/peer_review_2026_07_05.md`

## 요약 판정

프롬프트 `prompts/phase_p_purpose_return.md` 의 4개 검증 과제 (P-1 지표 가중치 백테스트,
P-2 기여 Top5 precision@5, P-3 수혜 Top5 forward return, P-4 BUY/SELL/HOLD 시뮬레이션) 를
사전 등록된 계약(pre-registration) 하에 실 데이터로 실행했다. 결과는 정직 원칙에 따라
성공 기준 완화 없이 그대로 기록한다.

| Test | 결과 (요약) | 정직 판정 |
|------|-------------|-----------|
| **P-4** | Strategy 0% cumret vs SP500 BH +0.14% / KOSPI BH -10.65%. 시그널 12개 스냅샷 전체에서 BUY 미발생 → 전략 진입 0회 | **Primary criterion not met — Sharpe undefined (0 trades)** — gate 발화 실패. 리스크-오프 신호 자체는 KOSPI 하락을 예고했으나 매매 룰이 활성화되지 않음 |
| **P-1** | Top5 hit rate 36.7% (11/30) vs Bottom5 60.0% (18/30). Δ=-23.3pp. **2-proportion z-test raw p ≈ 0.07** on 5d SP500 forward direction, N_snap=6 | **경고 — sign opposite hypothesis**. p 값은 α=0.05 못 넘지만 방향 자체가 가중치 랭킹의 예측력에 반대 (bottom-weighted 지표가 오히려 hit rate 우위) |
| **P-2** | Mean precision@5 = 0.533 < chance baseline 0.625 (universe=8, N_snap=6) | **미달 (baseline degenerate)** — universe=8 에서 5/8=0.625 는 broken yardstick. inferential 판정에는 SP500 500-ticker universe 또는 permutation null 필요 (다음 사이클) |
| **P-3** | SP500: 필터 후 N_evaluable=0 (100% top5 가 warn_reason). KOSPI: N=2, mean excess -0.019%, win rate 50% | **산출물 사용 불가 — pipeline output problem** (100% warn_reason 은 base rate 대비 ~7σ 이상, filter 문제 아님) |

**종합**: 프롬프트 성공 기준을 만족한 항목은 0/4. 이는 프롬프트가 예상한 **"예측력이 없다고
나오면 그게 이 작업의 가장 가치 있는 발견이다"** 조건에 해당하며, 각 항목의 실패 원인을
아래 분해 분석에 정리한다.

---

## 데이터 및 방법론

- **표본**: 12 daily pipeline commit 스냅샷 (2026-06-19 → 2026-07-04) — 사전 등록 목록 확정
- **External anchor** (OL-7): yfinance (SP500, US 종목), FinanceDataReader (KOSPI, KR 종목)
- **Forward window 가용성**: 5d=최대 6 스냅샷, 10d=0, 20d=0 (오늘=2026-07-05)
- **인프라 신설 없음**: 기존 도구만 사용 (yfinance, FDR, git). 백테스트 러너는
  `scripts/phase_p_backtest.py` 단일 스크립트로 CI 미연동.
- **Pre-registration gate**: runner 는 매 실행마다 pre-registration 파일이 HEAD 커밋에
  있고 디스크 내용과 일치함을 검증. FP-001 (사후 기준 완화) 방지.

---

## P-4. BUY/SELL/HOLD 시그널 성과

**질문**: decision.json 시그널을 그대로 따랐다면 buy-and-hold 보다 나았는가?

**결과** (12 스냅샷, tx cost 10 bps, HOLD=carry-over, 초기 상태=flat):

| Variant | Asset | Strat cumret | BH cumret | 50/50 cumret | Strat Sharpe | BH Sharpe | Trades | Avg exposure |
|---------|-------|-------------:|----------:|-------------:|-------------:|----------:|-------:|-------------:|
| unconditional | SP500 | +0.000% | +0.140% | +0.075% | (undef) | 0.394 | 0 | 0.0% |
| unconditional | KOSPI | +0.000% | -10.650% | -5.132% | (undef) | -2.754 | 0 | 0.0% |
| conf ≥ 60 | SP500 | +0.000% | +0.140% | +0.075% | (undef) | 0.394 | 0 | 0.0% |
| conf ≥ 60 | KOSPI | +0.000% | -10.650% | -5.132% | (undef) | -2.754 | 0 | 0.0% |
| conf ≥ 70 | (동일) | ... | ... | ... | ... | ... | 0 | 0.0% |

**정직 발견**:
1. 12 스냅샷 전체에서 **BUY 시그널 0회**. SP500: 8× SELL/AVOID + 4× HOLD. KOSPI: 4× SELL/AVOID + 8× HOLD. 모든 confidence tier 동일.
2. **Primary criterion (pre-reg: gated Sharpe > BH Sharpe) not met — Sharpe undefined (std=0, zero trades)**. "미판정" 이 아니라 **"test-of-strategy failed to activate"** — gate 자체가 발화 못한 것 (evaluator-agent round-2 지적).
3. 초기 상태 flat 규칙 하에 전략은 12일 내내 100% 현금 → cumret 0.000%. **Pre-reg 는 initial_state 를 명시하지 않았음** — 이는 pre-reg 결함으로 인식 (다음 사이클에 initial_state=long sensitivity 병기 필요, REQ-Phase-P-rerun 에 반영).
4. **KOSPI 하락(-10.65%)은 회피**했지만 이는 예측력이 아니라 "매수 시그널이 없으면 진입 안 함" + "flat 시작" 이라는 구조적 결과. Initial_state=long 시나리오 추정 (evaluator round-2): 첫 SELL 에서 청산 → KOSPI ~10.5pp outperform, SP500 ~0.24pp underperform. **하지만 이 시나리오는 pre-reg 에 없으므로 리포트에서 판정 기준으로 삼지 않음** (FP-001 회피).
5. **SP500 상승(+0.14%)은 놓쳤음**. 절대 손실은 작지만 리스크-오프 편향의 대가.
6. Confidence gate variants (60/70) 는 모두 동일 결과 — BUY 시그널이 없으므로 gate 는 무의미.
7. Sharpe 는 std=0 → 정의 불가. N=9~11 거래일로 통계적 Sharpe 는 SE≈1.6 (peer review 명시).

**성공 기준 미달 원인 분해**:
- **원인 1**: 관측 창(2026-06 후반부) 은 파이프라인이 리스크-오프 모드 를 지속 판단한 구간. BUY 시그널 발생 표본이 없음.
- **원인 2**: `direction=risk-off` 4회 (6/25 fe4bde2, 6/28, 6/29, 6/30) 는 실제 KOSPI 하락(-10.65%) 을 대체로 정확히 예고 → 하방 회피 시그널 자체는 유효했을 가능성.
- **원인 3**: BUY 진입 로직 검증이 불가능하므로 **P-4 는 "롱 매수 예측력" 을 판정할 수 없다**. 판정 가능한 것은 "리스크-오프 회피 능력" 뿐이며, 이 구간에서는 KOSPI 회피 +10.65pp / SP500 회피 -0.14pp.

**ROADMAP 개선 후보** (실행 안 함, 등록만):
- decision agent 의 BUY 조건 재검토: 어떤 지표 조합/컴포짓 임계값이 BUY 를 만드는지 명세.
- 이번 12 스냅샷 중 실제 시장이 상승했을 때 (예: 6/23~6/25) 왜 시그널이 HOLD/SELL 이었는지 인과 분해.
- Peer review 권고: 50/50 constant-mix 를 primary benchmark 로 (buy-and-hold 는 항상-롱 편향).

---

## P-1. 지표 가중치 랭킹 예측력 (SP500 5d forward direction)

**질문**: 가중치 상위 지표가 실제로 하위 지표보다 지수 방향을 더 잘 예측하는가?

**방법**: 각 스냅샷의 `market_signal.indicator_signals` 를 `weight` desc 정렬 →
상위 5, 하위 5 두 그룹. 각 지표의 `bullish` (bool) 이 5d SP500 forward direction 과
일치하면 hit. 그룹 hit rate 를 6 스냅샷에 걸쳐 집계.

**결과** (N_snap=6, horizon=5d, asset=SP500):

| 그룹 | Hits | Total | Hit rate | Wilson 90% CI |
|------|-----:|------:|--------:|:--------------|
| Top 5 | 11 | 30 | **0.367** | (0.237, 0.522) |
| Bottom 5 | 18 | 30 | **0.600** | (0.442, 0.740) |
| Δ (top - bottom) | | | **-0.233** | CI 겹침 |

**Per-snapshot 상세** (fwd = 5d SP500 forward return):

| Date | fwd return | actual UP | Top5 hits | Bot5 hits |
|------|-----------:|:---------:|:---------:|:---------:|
| 2026-06-25 | +1.709% | UP | 2/5 | 1/5 |
| 2026-06-24 | +1.699% | UP | 1/5 | 1/5 |
| 2026-06-23 | +1.818% | UP | 2/5 | 2/5 |
| 2026-06-22 | -0.433% | DOWN | 2/5 | 5/5 |
| 2026-06-20 | -1.954% | DOWN | 2/5 | 4/5 |
| 2026-06-19 | -1.954% | DOWN | 2/5 | 5/5 |

**정직 발견**:
1. 프롬프트 원래 성공 기준 (상위 그룹 > 하위 그룹, p<0.05, N≥30) — **미달, 방향 반전**. Δ = -0.233 이며 **2-proportion z-test raw p ≈ 0.07** (z ≈ -1.80, 두 그룹 pooled p = 0.483). Holm-Bonferroni α = 0.05/6 = 0.0083 은 통과 못하지만 raw p 는 α=0.05 에 근접 → "descriptive only" 프레이밍이 신호를 과소평가할 위험 (analysis-agent round-2 지적). 방향 자체가 pipeline 자체 가중치 산식의 예측 가설에 반대.
2. **DOWN 3일** (6/19, 6/20, 6/22): Bottom5 hit rate 4~5/5. 저가중 지표가 하락을 정확히 예고. 이는 저가중 지표가 실제로는 "리스크-오프 알람" 을 잘 냈는데 가중치 산식이 이를 낮게 평가했다는 시사점.
3. **UP 3일** (6/23, 6/24, 6/25): Top5 hit rate 5/15 = 33%, Bot5 4/15 = 27%. 상승장에서는 두 그룹 모두 부진.
4. 6 스냅샷 × 5 인디케이터 = 30 obs 는 프롬프트의 최소 30 요건은 만족하나, 스냅샷별 독립성 문제(같은 지표가 여러 스냅샷에 반복) 로 실질적 유효 표본은 훨씬 작음. Holm-adjusted 는 6-test family α=0.05 하에 p=0.07 이 통과 못하므로 통계적 유의성 주장 불가 — 그러나 방향 반전 자체는 pipeline 개선 우선순위 근거로 충분.

**성공 기준 미달 원인 분해**:
- **원인 1**: 가중치 산식(시차 상관 · Granger · 동행 페널티) 의 어느 항이 노이즈인가?
  이번 스냅샷 데이터로 6 시점만 관측되므로 항별 분해는 정보 부족 → **인프라 추가 없이는 진단 불가**.
- **원인 2**: 저가중 지표들이 리스크-오프 국면에서 더 정확했다는 사실은 가중치가
  "과거 상관관계 강도" 를 우선시하고 "국면 적합성" 을 반영하지 않는다는 가설과 부합.
- **원인 3**: `_CONTEMPORANEOUS` / `_SELF_REFERENTIAL` 필터가 이미 적용된 뒤에도 나오는 결과 → 필터 강화만으로는 해결 어려움.

**ROADMAP 개선 후보** (등록 대상):
- 가중치 산식에 forward-window validation 항목 추가 (현재 산식은 과거 window 만 사용).
- 국면(리스크-온/리스크-오프) 분류 후 지표 가중치를 국면별로 계산.
- Q4 2026 (~90 daily snapshots) 까지 데이터 축적 후 walk-forward embargo(-20d) 재실행.

---

## P-2. 지수 기여 Top5 precision@5 (SP500, 5d forward)

**질문**: contribution_top5 가 실제 forward window 기여 상위 종목을 잘 맞추는가?

**정의 정정** (peer review): 원 프롬프트의 "그날 실제 지수 기여도" 는
past-249d 값과 self-consistency 자체이므로 tautological. **정정된 정의**:
precision@5 = |snapshot Top5 ∩ empirical Top5 over T+1..T+5| / 5, empirical Top5 =
스냅샷 시점 market_cap 가중 forward return 순위.

**결과** (N_snap=6, universe=8 unique tickers, chance baseline=5/8=0.625):

| Date | precision@5 | 예측 Top5 | 교집합 |
|------|-----:|-----------|--------|
| 2026-06-25 | 0.600 | AAPL, GOOG, MSFT, MU, NVDA | AAPL, GOOG, MSFT |
| 2026-06-24 | 0.600 | AAPL, AMD, GOOG, MU, NVDA | AAPL, AMD, GOOG |
| 2026-06-23 | 0.800 | AAPL, AMD, GOOG, MU, NVDA | AMD, GOOG, MU, NVDA |
| 2026-06-22 | 0.400 | AAPL, AVGO, GOOG, MU, NVDA | GOOG, MU |
| 2026-06-20 | 0.400 | AAPL, AVGO, GOOG, MU, NVDA | AAPL, MU |
| 2026-06-19 | 0.400 | AAPL, AVGO, GOOG, MU, NVDA | AAPL, MU |
| **평균** | **0.533** | | |

**정직 발견**:
1. Mean precision@5 (0.533) < chance baseline (0.625). **다만 baseline 자체가 broken yardstick** — universe=8 에서 5/8=0.625 은 "무작위 5개 선택 = 5/8 확률" 이라는 degenerate 상태이므로 유의미한 비교 기준이 아님 (analysis-agent round-2 지적).
2. **하지만 universe 가 극도로 좁음** — 12 스냅샷 전체에서 관측된 unique ticker 가 8개
   (AAPL, AMD, AVGO, GOOG, MSFT, MU, NVDA, WDC/등). 이는 top5 자체가 이 좁은 집합 안에서 순환한다는 뜻.
3. **Inferential 판정 불가**: 이 결과로 "예측력 없음" 을 결론짓기 위해서는 (a) SP500 500-ticker universe 로 확장하거나 (b) 스냅샷-forward 페어링을 permutation 으로 shuffle 한 null distribution (1000 iter) 대비 empirical p-value 산출이 필요. 둘 다 인프라 추가에 해당해 이번 범위 밖 (**REQ-P2-universe 로 등록**). 현 결과는 "measured, not conclusive."
4. 프롬프트 성공 기준 (precision@5 ≥ 0.6) 대비: 6 스냅샷 중 3 스냅샷 (6/23, 6/24, 6/25) 은 만족, 3 스냅샷은 미달. 평균 0.533.

**성공 기준 미달 원인 분해**:
- **원인 1**: universe 정의가 결과에 결정적. 좁은 universe 에서는 chance 가 높아짐.
- **원인 2**: contribution_top5 가 시가총액 대형주 위주로 편향 (MSFT/AAPL/GOOG 매번 등장) → forward 기여를 잘 맞추려면 대형주 순환 예측 능력이 필요.

**ROADMAP 개선 후보**:
- Universe 를 S&P500 500 종목 전체로 확장한 precision@5 재계산 (별도 스크립트로).
- 대형주 편향 완화를 위한 sector-diversified top5 옵션 검토.

---

## P-3. 수혜 Top5 forward return vs benchmark

**질문**: beneficiary_top5 로 선정된 종목이 이후 실제로 시장을 이겼는가?

**결과** (5d horizon, exclusion filter: warn_reason / excess_return_pct > 200 / n_days < 180):

| Asset | N_evaluable | Mean excess | Win rate |
|-------|-----:|-----:|-----:|
| SP500 | **0** | (N/A) | (N/A) |
| KOSPI | **2** | -0.019% | 0.500 |

**KOSPI 평가 가능 상세**:
- 2026-06-24: excess = +7.853% (surviving: 000990.KS -12.6%, 322000.KS +24.3% / bench: -1.98%)
- 2026-06-23: excess = -7.890% (surviving: 000990.KS -4.57% / bench: +3.32%)

**정직 발견**:
1. **SP500 beneficiary_top5 의 100% 가 warn_reason 존재** — 매 스냅샷에서 5/5 tickers 가 SNDK (스핀오프), MU (+694%), WDC (스핀오프) 등 스핀오프 및 극단 수익률 티커. 사전등록된 exclusion filter (peer review 권고) 를 적용하면 SP500 은 0개 남음.
2. KOSPI 도 유사 — 대부분 warn_reason 존재 (극단 수익률). 필터 통과 N=2 로 통계 불가.
3. 프롬프트 원 성공 기준 (20d 초과수익 평균 > 0, 승률 > 50%) — **오늘 판정 불가** (20d forward 데이터 부재).
4. **beneficiary_top5 파이프라인 산출물의 근본 문제**: warn_reason 이 있는 티커를
   Top5 에 그대로 유지 → 사후 필터링 부담을 downstream 에 전가.

**성공 기준 미달 원인 분해**:
- **원인 1**: `beneficiary_score` 계산이 past 1yr excess return 을 우선시하기에 스핀오프
  같은 base effect 를 그대로 반영. warn_reason 자체는 표시되지만 랭킹에서 제외되지 않음.
- **원인 2**: 12 스냅샷 전체에서 warn_reason 없는 SP500 후보가 하나도 top5 에 진입하지 못한 것은 랭킹 정의 자체의 편향을 시사.
- **원인 3 (analysis-agent round-2)**: 정상 warn_reason base rate 는 universe 대비 5-15% 예상 (스핀오프+극단수익률 은 드묾). **관측 100% 는 예상 대비 ~7σ 이상 초과** → 이는 exclusion filter 문제가 아니라 **pipeline output 오염 문제**. Fix 위치는 `run_stock_agent.py` / `run_beneficiary_agent` 의 score 계산부이지 backtest filter 가 아님.

**ROADMAP 개선 후보**:
- `beneficiary_score` 계산 전에 warn_reason 후보 자동 제외 옵션 추가 (mask flag).
- Winsorization: past 1yr return 을 99th percentile 로 clip.
- 최소 180일 continuous price history 요건을 파이프라인 필터에 이관.

---

## INTERPRETATION LIMITS (round-2 peer review 반영)

이 리포트의 어떤 수치도 아래 한계 밖으로 일반화하면 안 된다:

1. **표본 크기**: N=12 스냅샷 (2026-06-19 → 2026-07-04). Analysis-agent 명시 minimum viable pooled N ≈ 60. **어떤 결과도 통계적 추론이 아니라 descriptive stat 이다.**
2. **관측 시장 국면**: 이 26일 창은 KOSPI 하락 (-10.65%) + SP500 대체로 flat 이라는 특정 리스크-오프 국면. 상승장 표본 없음. → P-4 결과는 상승장에서 시그널이 어떻게 작동할지 말해주지 못한다.
3. **P-2 universe = 8 tickers**: chance baseline 0.625 는 degenerate. 예측력 판정에는 SP500 500-ticker universe 또는 permutation null 필요.
4. **P-4 initial state = flat**: pre-reg 결함으로 명시 안 됨. Long-start sensitivity 는 이번 실행에 미포함. Evaluator 추정으로는 KOSPI ~+10.5pp, SP500 ~-0.24pp.
5. **Gate 발화 조건**: 12 스냅샷 전체에 BUY 시그널 없음 → gate variant 3개 모두 무의미. 따라서 P-4 결과는 "매수 로직 검증" 이 아니라 "매수 시그널 생성 여부 관찰" 이다.
6. **Forward window**: 20d 및 10d 는 오늘(2026-07-05) 데이터 부재로 실행 불가. 5d 만 최대 6 스냅샷 지원.
7. **Beneficiary filter 100% 제외**: 이는 backtest 문제가 아니라 pipeline 산출물 편향 (base rate 7σ 이상 초과). Fix 는 backtest 가 아니라 stock_agent 자체.

---

## 사전 등록 준수 (FP-001 방지 확인)

- Pre-registration file: `output/phase_p_preregistration.json`
- Freeze SHA: `77b13c6e8b72` (2026-07-05, 커밋 `docs(phase-p): peer review + pre-registration freeze`)
- Runner gate: `scripts/phase_p_backtest.py::assert_preregistration()` — HEAD ancestor 검증 + 디스크-HEAD 일치 검증
- **성공 기준 사후 완화 여부**: 없음. P-1 (p<0.05, N≥30) 은 그대로 유지하되 미달로 판정.
  P-3 (20d excess>0) 은 데이터 부재로 오늘 판정 불가로 명시. 어느 항목도 기준을 낮추지 않음.
- Level 8+ evidence: 각 P-* 는 exit 0 + numeric summary line + JSON output + 회귀 테스트.

---

## Peer Review Cross-Validation (2-round agent iteration)

**Round 1** (독립 병렬 평가, 상호 미공유):
- analysis-agent → `BLOCK_UNTIL_METHODOLOGY_FIX` (N 부족, P-2 tautological, P-3 survivorship bias, P-4 benchmark asymmetry)
- evaluator-agent → `ACCEPTABLE with fixes` (Holm-Bonferroni, pre-reg freeze, HOLD carry-over, indep fetcher)
- audit-agent → `feasible-with-caveats` (12 vs 15 snapshot 정정, 20d/10d 불가)

**Round 2** (각 agent 에 다른 두 agent 결론 + 실제 수치 공유, SendMessage 로 반박 iteration):
- analysis-agent → `revise_to_proceed` (P-1 p ≈ 0.07 명시 요구, P-2 baseline broken, P-3 7σ 초과 = pipeline 문제)
- evaluator-agent → `revise_to_caveated_acceptable` (Holm p 생략은 mild FP-001, initial_state 결함, canonical hash 필요)
- audit-agent → `revise-position → acceptable-verified` (모든 R1 blocker 해소 확인, spec-impl 8/8 match)

**PM-agent 최종 종합** (`amend-then-push`):
6-item minimum edit set 적용 후 push:
1. P-1 p ≈ 0.07 명시 + "sign opposite hypothesis"
2. P-4 "미판정" → "primary criterion not met (Sharpe undefined)"
3. P-2 "500 universe 확장 시 유의미" 추측 제거 + baseline degenerate 명시
4. INTERPRETATION LIMITS 섹션 추가
5. `test_p2_precision_below_chance` — P-2 결과 lock 회귀
6. `test_tx_cost_10bps_single_transition` — tx cost unit test

**Convergence 상태**: 3자 전원 revise 위치 이동. audit 완전 concur, analysis proceed 판정, evaluator caveated 유지 (freeze integrity 는 REQ 로 defer 합의).

Iteration 근거: `reports/phase_p/peer_review_2026_07_05.md` + Agent SendMessage transcript.

---

## 회귀 테스트

`tests/test_phase_p_backtest.py` — 실제 스냅샷 기반 (FIX-G 준수, 합성 fixture 금지):
- `test_preregistration_gate_valid` — freeze SHA 존재/ancestor/디스크-HEAD 일치 검증
- `test_wilson_ci_boundary` — 통계 헬퍼 순수함수 unit
- `test_normalize_action_sell_avoid` — "SELL/AVOID" → "SELL" 매핑
- `test_apply_gate_confidence` — confidence gate variants unit
- `test_passes_exclusion_warn_reason` — beneficiary exclusion 규칙 unit
- `test_p4_smoke_zero_buy_signal` — 실 스냅샷 3개로 P-4 sim 실행, 0 trades 상태 유지 검증

---

## ROADMAP 등록 (`pending_requests.json` 추가 예정)

각 P-* 실패 원인에 대응하는 개선 후보:

1. **REQ-P1-fix**: 지표 가중치 산식 forward-window validation 추가 — 현재 산식이
   과거 window 만 사용 → 리스크-오프 국면에서 저가중 지표가 hit rate 우위 발생.
2. **REQ-P2-universe**: precision@5 universe 를 S&P500 전체로 확장 (별도 스크립트).
3. **REQ-P3-filter**: `beneficiary_score` 계산 전 warn_reason 자동 제외 + winsorization
   + 180일 price history 최소 요건.
4. **REQ-P4-buy-conditions**: decision agent 의 BUY 조건이 12 스냅샷 관측 창에서 한번도
   발화하지 않은 원인 재검토 (composite_score 임계값 재보정?).
5. **REQ-Phase-P-rerun**: Q4 2026 (~90 daily snapshots) 도달 시 P-1 walk-forward
   embargo(-20d) 재실행.

---

## 부록: 결과 파일 위치

- `output/phase_p_p1_results.json` — P-1 상세 hit rate + Wilson CI + per-snapshot
- `output/phase_p_p2_results.json` — P-2 precision@5 상세
- `output/phase_p_p3_results.json` — P-3 excess return + exclusion 이력
- `output/phase_p_p4_results.json` — P-4 3 gates × 2 assets 상세
- `output/phase_p_preregistration.json` — freeze 계약 원본 (수정 금지)
- `output/backtest_cache/` — yfinance / FDR 캐시 (재실행 가속)
- `reports/phase_p/peer_review_2026_07_05.md` — 3-agent methodology review
