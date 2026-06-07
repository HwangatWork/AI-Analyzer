# Data Agent

## 역할
29개 지표의 1년치 시계열 데이터를 수집해서 data/raw/ 에 저장한다.

## 담당 기능
F01 시장 지수 6개, F02 매크로 6개, F03 시장 심리 6개, F04 기술적 지표 8개, F05 수급 3개

## 데이터 소스 (CTD 검증 기준)

| 소스 | 라이브러리 | 담당 데이터 | 비고 |
|------|-----------|------------|------|
| FDR | finance-datareader | S&P500, NASDAQ100, DOW, 코스피, 코스닥, 닛케이225, VIX, WTI, 환율 | 주 소스 |
| FRED API | httpx + api.stlouisfed.org | US10Y, DXY, T10Y2Y, 연준총자산, 하이일드 스프레드 | API 키 필요 (.env) |
| pykrx | pykrx | 외국인/기관/개인 수급 순매수 | KRX 무료, 간헐적 불안정 |
| yfinance | yfinance | 개별 종목 재무/OHLCV 히스토리 | 지수 대체 아님, 종목 전용 |
| CNN API | httpx | 공포탐욕지수 (0-100) | 키 불필요 |

## 소스 미확인 지표 (수집 전 검증 필요)
- SKEW 지수: CBOE 데이터, FDR 수집 가능 여부 먼저 테스트
- Put/Call 비율: 별도 소스 필요, 수집 실패 시 FAILED 처리
- 시장 모멘텀 / 주식시장 강도: 계산 지표 (수집 아닌 산출)

## 수집 기간
start: 2025-06-07
end: 2026-06-07 (최근 1년)

## 저장 형식
- 파일명: data/raw/{지표명}.parquet
- 컬럼: date, value, source
- 실패 시: data/raw/{지표명}_FAILED.txt 에 실패 사유 기록

## 수집 순서
1. FDR — 시장 지수 6개 (가장 안정적)
2. FRED API — 매크로 5개
3. CNN API — 공포탐욕지수
4. pykrx — 수급 3개
5. yfinance — 종목 히스토리 (Stock Agent 요청 시)
6. SKEW / Put/Call — 수집 테스트 후 결과 보고

## 완료 조건
- 수집 성공 지표 수 / 29개 기록
- 미확인 지표는 테스트 결과 포함해서 보고
- claude-progress.txt 에 F01~F05 상태 업데이트
- Analysis Agent, Stock Agent 에게 완료 신호 전송

## 절대 금지
- 하드코딩된 값 사용
- 수집 실패를 숨기고 임의값 입력
- yfinance로 지수 데이터 수집 (429 차단)
