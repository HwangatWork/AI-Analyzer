# UX-FIX-1 구현 리포트 — 데이터/판단 정합성 결함 3건 (Level 10)

- 작성일: 2026-07-05
- 근거 감사: `reports/ux_audit_2026-07-05.md`, `reports/ux_audit_peer_review_2026-07-05.md`
- 스코프: **잘못된 정보/판단 왜곡만** 수정 (CSS/레이아웃은 별도 커밋)
- 회귀 기준: 착수 baseline **275 PASS / 0 FAIL** → 완료 **283 PASS / 0 FAIL** (신규 8 테스트 포함)

---

## 착수 baseline (procedure step 1)

```
$ python -m pytest agents/tests/ -q → 275 passed, 0 failed (43.50s)

# M-14 A: 반도체 섹션/id 중복
$ grep -c 'id="semiconductor-export"' output/dashboard.html → 2
$ grep -c '반도체 수출 동향' output/dashboard.html          → 2

# M-05: 반도체/AI 섹터에 비-반도체 유입
$ grep -oE 'Accenture|Adobe Inc\.|Apple Inc\.' output/dashboard.html | sort | uniq -c
  → 2 Accenture / 2 Adobe Inc. / 3 Apple Inc.

# M-14 B: Alphabet share-class 중복
$ grep -oE 'GOOGL|GOOG' output/sector_analysis.json | sort | uniq -c
  → 1 GOOG / 1 GOOGL
```

---

## M-16 (HIGH) — 약세 신호 지표명 전면 소실 → **FIXED**

### 근본 원인 (numeric proof)
`agents/run_ui_agent.py:126` `"bullish": signal > 0` 에서 `signal` 은
`np.float64`(pandas `.mean()/.std()` 경유) → `bullish` 는 `np.bool_`.
`agents/run_ux_signal_agent.py:190` 의 데드코드 `s.get("bullish") is False` 는
**identity 비교**라 `np.bool_(False) is False == False`. 이 라인이 L187 의 올바른
truthy 로직을 덮어써 약세 리스트가 항상 `[]`.

```
$ python -c "import numpy as np; b=np.float64(-0.5)>0; print(b is False)"
→ False              # np.bool_(False) is False → identity 실패
$ python -c "import numpy as np; print(not (np.float64(-0.5)>0))"
→ True               # truthy 판정은 정상
# is-False bearish: []   vs   truthy bearish: ['X']  (동일 입력)
```

라이브 경로 확정: `run_ui_agent.py:553` `signal = compute_composite_signal(...)`
→ (nan_safe 미적용) → `:488 generate_signal_section(signal)`. 즉 in-memory 는
`np.bool_`. (persisted `final_results.json` 은 nan_safe 로 python bool 이라
파일 재빌드 경로만 보면 버그가 가려짐 — 실제 파이프라인은 in-memory 경로.)

### 수정
- `run_ux_signal_agent.py:189-190` 데드코드 제거, L187 정본(truthy) 유지 + 주석.
- 근본 강건성: `run_ui_agent.py:126` `bool(signal > 0)` 로 소스에서 python bool 정규화
  (다른 소비자 영향 없음 — 이미 nan_safe 도 np.bool_→bool 변환하던 값).

### before/after (재빌드 dashboard)
```
before: 약세 신호 카드 지표명 div 부재 (강세만 표시 → 강세 편향)
after : 약세 신호 → US10Y · INSTITUTION_NET · WTI
        강세 신호 → HY_SPREAD · MARKET_STRENGTH · VIX
```

### 엣지케이스 (실측 PASS)
| bullish 값 | 기대 | 결과 |
|-----------|------|------|
| np.bool_(False) | bearish | PASS |
| np.bool_(True)  | bullish | PASS |
| python False    | bearish | PASS |
| python True     | bullish | PASS |
| 키 부재         | bearish 제외 | PASS |

---

## M-05 (HIGH) — 섹터 오분류 (Adobe/Accenture/Apple → "반도체/AI") → **FIXED**

### 근본 원인
1. `SECTORS['반도체/AI'].us_sector_kw = [..., "Technology"]` → S&P500 IT 섹터
   **전체**(Accenture=IT Consulting, Adobe=Application Software, Apple=Hardware) 매칭.
2. `.head(n)` 이 **시총이 아닌 FDR 원본(대략 알파벳) 순서** 상위 n → docstring
   "시총 상위 N개" 와 불일치. (FDR `StockListing("S&P500")` 컬럼 = Symbol/Name/
   Sector/Industry — **MarketCap 컬럼 자체가 없음**, 실측 확인.)
3. 섹터 간 dedup 부재.

### 수정 (`agents/run_sector_agent.py`)
- ① `us_sector_kw` 를 `["Semiconductor"]` 로 좁힘. `us_industry_kw` 에
  `"Electronic Components"` 추가(Amphenol 등 정상 편입). 광의 "Technology" 제거.
- ② `_dynamic_us_tickers`: MarketCap/Marcap/MktCap 컬럼 탐지 → 존재 시 내림차순
  정렬 후 상위 n. **부재 시 원본 순서 유지 + 로그**
  (`[동적US] 시총 컬럼 부재 — FDR 원본 순서 유지(시총 정렬 미적용)`).
  → 현재 FDR 데이터엔 컬럼 부재이므로 **시총 정렬은 미적용, 로그만 출력**(정직 보고).
- ③ `run_sector_analysis`: `seen_tickers` 전역 set 으로 앞선 섹터에 배정된 티커를
  후순위 섹터에서 제외 (섹터 간 중복 제거).

### before/after (`output/sector_analysis.json` 재생성, exit 0 / DONE_CRITERIA PASS)
```
before 반도체/AI: ACN(Accenture), ADBE(Adobe), AMD, AKAM, APH, ADI, AAPL(Apple) ...
after  반도체/AI: AMD, Amphenol, Analog Devices, Applied Materials, Broadcom,
                  Coherent, Corning (+ SK하이닉스/삼성전자/한미반도체) — 전부 반도체/전자

$ 반도체/AI bad tickers(Accenture/Adobe/Apple): []   PASS
$ cross-sector 중복 티커: {}                          PASS
```
Accenture/Adobe 는 실제 industry(IT Consulting / Application Software)에 맞게
`AI/플랫폼` 으로 이동. Apple 은 어떤 섹터에도 없음(잔존 1건은 종목 Top5 = 별개 정상 기능).

### 엣지케이스
- 시총 컬럼 부재 폴백: 로그 출력 + 원본 순서 유지 확인(실측).
- 스키마 불변: top-level(3 섹터 + `_meta`), 섹터 키(`tickers`/`theme`/`key_risk`/
  `universe_src`) 동일. 소비자(`run_ui_agent`=재빌드 7/7 PASS, `pm_quality` QH-1=
  ticker count≥3, `run_validation_agent` P4=파일 존재) 전부 값이 아닌 스키마/카운트만
  읽음 → 무영향.

---

## M-14 (HIGH) — 반도체 섹션 이중 렌더 + GOOGL/GOOG 중복 → **FIXED**

### A. 이중 반도체 섹션 (상충 수치)
두 소스가 같은 제목/같은 id 로 인접 렌더:
- (제거) `run_ux_signal_agent.py` 내장 — `output/semiconductor_export.json`
  = ECOS **수출금액지수(2020=100)**, 전월 +16.7% / 전년 +151.0%.
  `semiconductor_monitor` 는 QI-1 로 **모니터링 전용** 전환됨.
- (정본 유지) `run_ui_agent.py::_html_semiconductor_section` —
  `data/raw/SEMICONDUCTOR_EXPORT.parquet` = **관세청 실적(actual USD FOB, HS8542)**,
  전월 +2.5% / 전년 +54.0%. Level-8 DC 게이트(`run_data_agent_v2.py`)로 생성되는
  **실측 금액** 소스이므로 정본으로 채택.

조립 이중 삽입 경로: `run_ux_signal_agent.py:332 {semiconductor_section}` +
`run_ui_agent.py:448 {signal_html}{semiconductor_html}`. 전자를 제거.

수정: `run_ux_signal_agent.py` 의 반도체 섹션 로딩/HTML(L200-287) 삭제,
return 말미 `{semiconductor_section}` 제거. (`_build_semi_chart` 는 미사용화되나
스코프상 최소변경 위해 정의는 잔존.)

### B. share-class 중복 (GOOGL + GOOG)
`_dedup_share_classes(rows)` 신설 — name 에서 클래스 표기(`(Class A)`, `Class C`,
`Cl A` 등) 정규화한 base-name 기준 첫 항목만 유지. `_dynamic_us_tickers` 가
head(n) 직전에 적용.

### before/after (재빌드 dashboard)
```
$ grep -c 'id="semiconductor-export"' → 2 → 1
$ grep -c '반도체 수출 동향'          → 2 → 1  (살아남은 섹션 = "반도체 수출 동향 (관세청 실적)")
$ grep -oE 'GOOGL|GOOG' output/dashboard.html | sort|uniq -c → 3 GOOGL (GOOG 소멸)
$ AI/플랫폼: GOOGL 있음 / GOOG 없음                             PASS
```

### 엣지케이스 (share-class dedup, 실측 PASS)
| 입력 | 기대 | 결과 |
|------|------|------|
| GOOGL + GOOG + MSFT | [GOOGL, MSFT] | PASS |
| AAPL + NVDA (단일클래스 2사) | 2개 보존 | PASS |
| BRK.B + BRK.A | 1개 | PASS |
| Visa + Mastercard (별개 회사) | 2개(collapse 안됨) | PASS |
| [] | [] | PASS |

---

## 회귀테스트 (신규)
`agents/tests/test_ux_fix1_data_integrity.py` — 실제 함수 계약 기반(FIX-G 준수), 8 케이스:
- T-UXF-1: `generate_signal_section` HTML 에 약세 지표명 렌더 (np.bool_ / python bool)
- T-UXF-2: bearish 추출 truthy 로직 (np.bool_ / bool / 키부재)
- T-UXF-3: `final_results.json` bullish == python bool 계약
- T-UXF-4: 반도체/AI us_sector_kw 에 광의 "Technology" 부재
- T-UXF-5: `_dynamic_us_tickers` 반도체/AI 에 Accenture/Adobe/Apple 미포함 (실 FDR)
- T-UXF-6: `generate_signal_section` 이 semiconductor-export 섹션 미생성(단독 렌더)
- T-UXF-7: `_dedup_share_classes` (dedup + 단일클래스 보존 + 별개회사 유지)

```
$ python -m pytest agents/tests/test_ux_fix1_data_integrity.py -v → 8 passed (1.62s)
$ python -m pytest agents/tests/ -q                               → 283 passed, 0 failed (43.98s)
```

---

## 재현 커맨드 로그 (summary)
```
python -m pytest agents/tests/ -q                       # 275 → 283 PASS / 0 FAIL
python agents/run_sector_agent.py                       # exit 0, DONE_CRITERIA PASS
python agents/run_ui_agent.py                           # exit 0, UX 7/7 PASS, DC PASS
grep -c 'id="semiconductor-export"' output/dashboard.html   # 2 → 1
grep -c '반도체 수출 동향' output/dashboard.html            # 2 → 1
grep -oE 'Accenture|Adobe Inc\.|Apple Inc\.' output/dashboard.html | sort|uniq -c  # 2/2/3 → 1/1/1
grep -oE 'GOOGL|GOOG' output/dashboard.html | sort|uniq -c  # → GOOG 소멸
```

## 남은 리스크 / 정직 보고
- **시총 정렬 미적용**: FDR `StockListing("S&P500")` 에 MarketCap 컬럼이 없어
  시총 상위 N 선정은 이번 실행에서 **적용되지 않음**(로그로 명시). 컬럼이 있는
  데이터 소스로 교체되면 코드가 자동으로 정렬 경로를 탄다. docstring "시총 상위 N개"
  의 완전 이행은 별도 데이터소스 작업 필요(범위 밖).
- `_build_semi_chart` 는 M-14 수정으로 dead code 화(정의만 잔존) — 최소변경 원칙상
  삭제 보류. 별도 정리 커밋 권장.
- 커밋/푸시 미수행 — audit-agent 독립 검증 후 메인 세션이 수행.
