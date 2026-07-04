# Consensus Snapshot -- SK hynix (000660)

- 데이터 시점 상태: **snapshot** (daily 누적 시작 전 단일 스냅샷)
- 데이터 품질 점수: **1.00** / 1.00

## 기본 컨센서스

| 항목 | 값 |
|---|---|
| 투자의견 (1~5 scale) | 4.0 |
| 추정기관 수 | 24 |
| 최근 컨센서스 목표주가 | 2,470,417원 (2026-05-29 기준) |
| 1개월 전 목표주가 | 1,738,750원 |
| 1개월 변화율 | +42.08% |

## AI 분석 (Q1~Q5)

| 질문 | 결과 | 변화율 |
|---|---|---|
| Q1 목표주가 추세 | 상승 | +42.08% |
| Q2 EPS 추세 | 상승 | +421.85% |
| Q3 영업이익 추세 | 데이터 부족 | N/A |
| Q4 4사분면 분류 | **TRUE_UPGRADE** | -- |
| Q5 글로벌 vs 국내 | GLOBAL_DATA_INSUFFICIENT | -- |

## 코멘트

목표가·EPS 모두 상향. 펀더멘털 기반 정상 업그레이드.

## 데이터 해석 주의사항

- **한국 매수편향 주의**: KCMI 2025 (Buy 93.1%, Sell 0.1%, 2020-2024). 투자의견 수치 자체는 신호 가치가 낮으므로 EPS / 목표가 revision 을 우선.
- **목표주가 역할**: sentiment_valuation_proxy -- Bradshaw, Brown, Huang 2013 -- 12-month target price end-of-period achievement 38%, MAFE ~45%. 절대 가격 예측이 아닌 sentiment / valuation proxy 로 해석.
- **시점 상태**: single fetch; not yet a daily-accumulated point-in-time series. Naver/WiseReport historical entries may have been retroactively updated (Ljungqvist 2009).

## 참고 (footnote)

- KCMI 2025, *Optimism Bias in Analyst Research*: 2020-2024 한국 sell-side Buy 93.1%, Sell 0.1%.
- Bradshaw, Brown, Huang 2013, *Review of Accounting Studies*: 12-month target price 달성률 38%, 평균 절대 오차 ~45%.
- Ljungqvist, Malloy, Marston 2009, *Journal of Finance*: I/B/E/S 과거 레코드의 retroactive 변경 1.6%~21.7%.
