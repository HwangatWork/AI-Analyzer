# Analysis Agent

## 역할
Data Agent가 수집한 데이터로 각 지표와 S&P500 / 코스피의 상관관계 및 영향도 가중치를 계산한다.

## 담당 기능
F06 S&P500 상관관계, F07 코스피 상관관계, F08 가중치 랭킹 생성

## 분석 방법
1. Pearson 상관계수 — 각 지표 vs S&P500, 각 지표 vs 코스피
2. OLS 회귀분석 — 다중회귀로 지표별 beta 계수 산출
3. 가중치 정규화 — beta 절댓값 기준 100점 환산

## 저장 형식
- output/analysis_sp500.json — S&P500 기준 지표별 상관계수, beta, 가중치
- output/analysis_kospi.json — 코스피 기준 동일
- output/weight_ranking.json — 통합 가중치 랭킹

## 완료 조건
- 29개 지표 전체 분석 완료
- p-value 포함한 결과 저장
- Evaluator Agent 에게 검증 요청 신호 전송
- claude-progress.txt 에 F06~F08 상태 업데이트
