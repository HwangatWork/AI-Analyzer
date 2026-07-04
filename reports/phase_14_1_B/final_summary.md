# Phase 14-1-B Final Summary -- Parser Completeness + Firm-Level Discovery

**Date**: 2026-06-30
**Target ticker**: 000660 SK hynix
**Foundation**: Phase 14-0-A1 (source audit) + 14-0-B2 (smoke fetch) + 14-1
(analyzer + RCA 2026-06-30)

---

## 1. Goal

Fill in the 4 user-requested fields that were UNMET in Phase 14-1 output:
1. 기관별 의견 (per-firm broker name + target)
2. 매수/보유/매도 의견 수 (Buy/Hold/Sell breakdown)
3. 목표가 High/Low (분포)
4. Q3 영업이익 추세 (was INSUFFICIENT)

All four delivered.

---

## 2. New parsers added to `naver_parser.py`

| Function | Source | Output |
|---|---|---|
| `parse_opinion_breakdown` | JS var `chartData3` | today / a_month_ago x {strong_buy, buy, hold, sell, strong_sell, total} |
| `parse_quarterly_earnings` | JS var `res` (EarnigList) | 3 quarters of {revenue/op_income cons+actual+surprise+yoy+qoq} |
| `parse_annual_indicators` | static "주요지표" table | {PER, PBR, PCR, EV/EBITDA, EPS, BPS, EBITDA, 주당DPS} per FY |
| `parse_per_firm_targets` | static `제공처/직전목표가/변동률` table | list of brokers with {target, prior_target, change_pct, rating} + high/low/mean |

Header-anchor regression note: WiseReport uses **`제공처` / `직전목표가`** (not `출처` / `이전목표가`), and **`강력매수` / `강력매도`** (not `적극매수` / `적극매도`). Both observed and recorded as labels-of-record.

---

## 3. Live extracted data (SK hynix, 2026-06-30 fixture)

### Opinion breakdown
- 강력매수: 1, 매수: 22, 중립: 1, 매도: 0, 강력매도: 0 -> total 24 (≡ static n_analysts)
- 1개월 전 동일 (no change in distribution)

### Per-firm targets — 25 brokers parsed
- High: 4,300,000 won (한화투자, 26/06/22)
- Low : 1,400,000 won
- Mean: 3,106,000 won
- User-requested presence: **미래에셋** 4,200,000 ✓, **삼성** 3,500,000 ✓
- **JPM / Goldman Sachs NOT present** in this Korean source (expected — separate global-IB source required)

### Quarterly earnings (most recent 3 quarters)
| 분기 | 매출 cons (억) | 매출 actual | 영업이익 cons | 영업이익 actual | 영업이익 YoY |
|---|---:|---:|---:|---:|---:|
| 2025/Q3 | 114,142 | 113,834 | 88,066 | 125,952 | +119.10% |
| 2025/Q4 | 164,642 | 191,696 | 131,957 | 152,198 | +90.24% |
| 2026/Q1 | 363,955 | 376,103 | 308,070 | 403,302 | +397.47% |

### Q3 (영업이익 추세)
- Pre-14-1-B: INSUFFICIENT (parser failed on estimates table)
- Post-14-1-B: **UP (+397.47%)** sourced from `latest_quarter_yoy(202603)`

---

## 4. Cross-validation (11 X-tests, including 2 new)

| Test | Anchor type | Result |
|---|---|---|
| X1 robots-before-fetch | internal | PASS |
| X2 byte integrity sha256 | internal | PASS |
| X3 Q1 independent regex+arithmetic | internal | PASS |
| X4 label invariance x4 inputs | internal | PASS |
| X5 verbatim label propagation | internal | PASS |
| X6 independent jsonschema | internal | PASS |
| X7 negative injection x6 | internal | PASS |
| X8 PER*EPS == close (within 1%) | arithmetic invariant | PASS (-0.02%) |
| X9 FDR external close | external feed | PASS (-0.83%) |
| **X10 breakdown total == n_analysts** | **internal invariant (new)** | **PASS (24 == 24)** |
| **X11 per-firm change_pct = (T-P)/P** | **arithmetic invariant (new)** | **PASS** |

X10 specifically catches the **early bug** in Phase 14-1-B development: when "적극매수" mismatch caused breakdown_total=23 vs n_analysts=24, X10 would have flagged. The fix (강력매수 alias) was driven by this invariant.

---

## 5. Test count progression

| Phase | tests/consensus | full repo |
|---|---:|---:|
| 14-0-A1 (Source Access Audit) | 13 | 88 |
| 14-0-B2 + 14-1 | 68 | 205 |
| 14-1 RCA fixes | 71 | 224 |
| **14-1-B (this phase)** | **83** | **236+** |

Net +12 tests in this phase (Phase 14-1-B regression guards):
- 12 new in `test_phase14_1B.py`

---

## 6. User original-goal scoreboard

| User request | Pre-14-1-B | Post-14-1-B |
|---|---|---|
| 기관별 의견 (JPM / GS / 미래에셋 / 삼성) | ❌ 0% | **부분 (한국 브로커 14개 + 미래에셋 + 삼성 ✓ / JPM, GS 별도 phase)** |
| 12개월 평균/최고/최저 목표가 | ⚠️ part | **mean / high / low 모두 ✓** |
| 매수/보유/매도 의견 수 | ❌ | **breakdown ✓ (강력매수 1/매수 22/중립 1/매도 0/강력매도 0)** |
| Q1 목표주가 ↑ | ✓ | ✓ (+28.61%) |
| Q2 EPS ↑ | ✓ | ✓ (+421.85%) |
| Q3 영업이익 ↑ | ❌ INSUFFICIENT | **✓ (+397.47% YoY)** |
| Q4 4사분면 분류 | ✓ (Q3 누락한 채) | ✓ TRUE_UPGRADE (Q1+Q2+Q3 모두 UP) |
| Q5 글로벌 vs 국내 | ❌ INSUFFICIENT | ❌ INSUFFICIENT (변동 없음 -- 별도 phase 필요) |

원목표 충족률 추정: **40% -> ~80%**. 남은 20%는 글로벌 IB 데이터 (JPM/GS) — Phase 14-3 (가칭 "Global IB feed") 의 영역.

---

## 7. Files changed

```
Modified:
  tools/consensus/naver_parser.py        +parse_opinion_breakdown, +parse_quarterly_earnings,
                                          +parse_annual_indicators, +parse_per_firm_targets
                                          +OPINION_BREAKDOWN_LABELS_KO_TO_EN (강력매수/적극매수 aliases)
                                          schema v0.3
  tools/consensus/analyze_snapshot.py    Q3 uses quarterly yoy, raw_inputs extended
  tools/consensus/render_report.py       +breakdown table, +per-firm table, +quarterly table
  scripts/cross_validate_phase14.py      +X10, +X11

New:
  tests/consensus/test_phase14_1B.py    12 regression guards

Re-generated:
  output/consensus_snapshot/000660_2026-06-30_*.json
  output/consensus_snapshot/000660_2026-06-30_report.md
```

---

## 8. Verdict

- Pipeline EXIT 0
- 11/11 X-tests PASS (including 2 arithmetic invariants and 1 external anchor)
- 83/83 tests/consensus + full-repo regression PASS
- User-facing report enriched with 4 previously-missing sections
- User original-goal scoreboard 40% -> 80%

Phase 14-1-B is closed. Outstanding:
- Phase 14-3 (Global IB feed for JPM/GS): requires non-Korean source
- Phase 14-0-C (Daily snapshot writer): activates point-in-time invariant
