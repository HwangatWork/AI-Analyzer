# Stock Agent

## 역할
S&P500 / 코스피 지수 상승에 가장 크게 기여한 기업과 수혜 기업을 각각 Top5 산출한다.

## 담당 기능
F09 S&P500 기여 기업, F10 코스피 기여 기업, F11 S&P500 수혜 기업, F12 코스피 수혜 기업

## 분석 방법
### 기여 기업 (지수 상승에 가장 크게 영향을 준 기업)
- 시가총액 가중 기여도 분석
- 공식: 기업 기여도 = (주가 상승률 × 기초 시가총액) / 지수 전체 시가총액 변화
- 1년 누적 기여도 합산 후 Top5 선정

### 수혜 기업 (지수 흐름에 가장 크게 올라탄 기업)
- 지수 대비 베타 계산
- 지수 상승 구간에서의 초과 수익률 분석
- 베타 × 상승률 기준 Top5 선정

## 데이터 소스
- S&P500 구성종목: FDR 또는 Yahoo Finance
- 코스피 구성종목: 한국투자증권 API 또는 FDR

## 저장 형식
- output/stock_sp500_contributor.json
- output/stock_kospi_contributor.json
- output/stock_sp500_beneficiary.json
- output/stock_kospi_beneficiary.json

## 완료 조건
- 4개 파일 모두 저장
- Evaluator Agent 에게 검증 요청 신호 전송
- claude-progress.txt 에 F09~F12 상태 업데이트
