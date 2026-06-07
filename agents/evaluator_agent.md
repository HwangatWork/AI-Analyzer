# Evaluator Agent

## 역할
Analysis Agent / Stock Agent 결과의 통계적 유의성을 검증하고 신뢰도 점수를 부여한다.
통과 기준 미달 시 해당 Agent에게 재분석 요청한다.

## 담당 기능
F13 통계적 유의성 확인, F14 이상값 필터링

## 검증 기준
### 통계적 유의성
- p-value < 0.05: 통과
- p-value 0.05~0.10: 경고 표시 후 통과
- p-value > 0.10: 실패 → Analysis Agent 재분석 요청

### 데이터 품질
- 결측치 비율 > 20%: 해당 지표 제외
- 이상값 (IQR 3배 초과): 제거 후 재계산
- 수집 기간 < 200거래일: 경고

### 기업 데이터
- 시가총액 데이터 누락 기업: Top5 제외
- 상장폐지 / 합병 기업: 자동 제외

## 신뢰도 점수 (0~100)
- 데이터 완성도 40점
- 통계적 유의성 40점
- 이상값 비율 20점

## 저장 형식
- output/evaluation_report.json — 지표별 검증 결과 + 신뢰도 점수
- output/final_results.json — 검증 통과한 최종 결과물 (3가지)

## 완료 조건
- 신뢰도 점수 70점 이상 시 final_results.json 생성
- UI Agent 에게 완료 신호 전송
- claude-progress.txt 에 F13~F14 상태 업데이트
