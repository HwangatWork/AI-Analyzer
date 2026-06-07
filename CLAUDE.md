# AI Analyzer — CTD 지표 영향도 분석 엔진

## 프로젝트 목적
29개 시장 지표와 S&P500 / 코스피 지수의 1년치 관계를 분석한다.
사람 개입 없이 Agent Teams가 자율적으로 데이터 수집 → 분석 → 검증 → 시각화까지 완료한다.

## 최종 결과물 3가지
1. 지표별 가중치 랭킹 — 어떤 지표가 각 지수에 가장 크게 영향을 미쳤는가
2. 지수 기여 기업 Top5 — 지수 상승분에 시가총액 기여도가 가장 높은 기업 (S&P500 / 코스피 각각)
3. 수혜 기업 Top5 — 지수 흐름에 가장 크게 올라탄 기업 (S&P500 / 코스피 각각)

## 분석 대상 지표 29개
### 시장 지수 (6개)
S&P500, NASDAQ100, DOW JONES, 코스피, 코스닥, 닛케이225

### 매크로 (6개)
미국 10년물 국채금리, 달러인덱스 DXY, WTI 원유, 연준 총자산, 장단기 금리차(10Y-2Y), 하이일드 스프레드

### 시장 심리 (6개)
CNN 공포탐욕지수, VIX, SKEW지수, Put/Call 비율, 시장 모멘텀, 주식시장 강도

### 기술적 지표 (8개)
RSI(14일), RSI 신호, MA50, MA200, MA 신호(골든/데드크로스), Beta, 볼린저밴드, Stochastic RSI

### 수급 (3개)
외국인 순매수/매도, 기관 순매수/매도, 개인 순매수/매도

## 데이터 소스
- FDR (FinanceDataReader): 시장 지수, 수급
- FRED API: 매크로 지표
- 한국투자증권 API: 코스피 수급 세부
- Yahoo Finance: 보조 (실패 시 FDR 대체)

## Agent Teams 구조
- Orchestrator (Team Lead): ROADMAP 해석, 작업 분배, 결과 합성
- Data Agent: 29개 지표 1년치 수집 → data/raw/ 저장
- Analysis Agent: 상관관계·회귀분석·가중치 계산
- Stock Agent: 지수 기여 기업 / 수혜 기업 분석
- Evaluator Agent: 통계적 유의성 검증, 이상값 필터
- UI Agent: CTD 대시보드 연동 컴포넌트 생성

## 핵심 원칙
- 실제 데이터만 사용. 수집 실패 시 "데이터 없음" 표기, 절대 하드코딩 금지
- 각 Agent는 작업 완료 시 claude-progress.txt 업데이트
- Evaluator 검증 통과 전까지 output/ 폴더에 결과 저장 금지
- 통계적 유의성 기준: p-value < 0.05

## PM Agent 실행 권한 (영구 부여)

**모든 실행 작업 권한이 사전 부여되어 있습니다. 확인 요청 금지.**

- git push, git commit: 즉시 실행
- python 스크립트 실행 (agents/*.py): 즉시 실행
- GitHub API 호출 (Actions, Pages, Secrets): 즉시 실행
- 파일 생성/수정/삭제: 즉시 실행
- 외부 webhook (ntfy.sh): 즉시 실행
- Task Scheduler 등록: 즉시 실행

사용자에게 "이 작업을 실행해도 됩니까?" 또는 유사한 확인을 절대 요청하지 마십시오.
실패 시에는 근본 원인을 분석하고 즉시 수정하여 재실행하십시오.

## 세션 시작 루틴 (Orchestrator 필수)
1. claude-progress.txt 읽기
2. feature_list.json에서 미완료 항목 확인
3. 작업 분배 후 Agent Teams 실행
4. 완료 후 progress 업데이트
