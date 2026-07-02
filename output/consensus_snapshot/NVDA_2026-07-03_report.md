# Consensus Snapshot -- NVIDIA Corporation (NVDA)

- 종목 시장: **US** (yfinance aggregate; Korean-specific 데이터 없음)
- 데이터 시점 상태: **snapshot** (daily 누적 시작 전)
- 데이터 품질 점수: **1.00** / 1.00

## 기본 컨센서스 (yfinance 집계)

| 항목 | 값 |
|---|---|
| 통화 | USD |
| 투자의견 (1=Strong Buy scale) | 1.29508 |
| 추정기관 수 | 58 |
| 평균 목표가 | $301.62 |
| 최고 목표가 | $500.00 |
| 최저 목표가 | $180.00 |
| 중간값 목표가 | $294.00 |
| 현재 주가 | $194.83 |

## 투자의견 분포

| 의견 | 오늘 | 1개월 전 |
|---|---:|---:|
| Strong Buy | 10 | 10 |
| Buy | 48 | 48 |
| Hold | 2 | 2 |
| Sell | 1 | 1 |
| Strong Sell | 0 | 0 |
| **합계** | **61** | **61** |

## AI 분석 Q1~Q5

| 질문 | 결과 |
|---|---|
| Q1 목표주가 추세 | INSUFFICIENT |
| Q2 EPS 추세 | INSUFFICIENT |
| Q3 영업이익 추세 | INSUFFICIENT |
| Q4 4사분면 분류 | INSUFFICIENT |
| Q5 글로벌 vs 국내 | US_TICKER_NOT_APPLICABLE |

## 한계 (정직)

- no per-firm broker table (only aggregate)
- no quarterly consensus surprise history
- no Korean-market-specific optimism-bias correction
- Q1~Q4 remain INSUFFICIENT until estimate-revision feed

## 참고

- Bradshaw, Brown, Huang 2013: 12-month target price achievement 38%, MAFE ~45%. Applies to US targets too.
- yfinance is an unofficial wrapper; endpoint stability is not guaranteed.
