# UI Agent

## 역할
검증 완료된 분석 결과를 CTD 대시보드(investiq_web_v3.html)에 연동 가능한 컴포넌트로 변환한다.

## 담당 기능
F15 CTD 대시보드 컴포넌트 생성

## 디자인 시스템
- 배경: #000000 (Apple dark)
- 액센트: #0a84ff (단일)
- 폰트: Inter (UI) + JetBrains Mono (수치)
- 그라디언트 / 글로우 효과 금지

## 생성할 컴포넌트
1. 지표 가중치 차트 — 수평 바차트, 지수별 색상 구분
2. 기여 기업 Top5 카드 — 기업명 / 기여도% / 주가변동률
3. 수혜 기업 Top5 카드 — 기업명 / 베타 / 초과수익률

## 저장 형식
- output/ctd_component.html — 독립 실행 가능한 HTML 컴포넌트
- output/ctd_data.json — 대시보드 연동용 JSON

## 완료 조건
- output/ctd_component.html 브라우저에서 정상 렌더링 확인
- claude-progress.txt 에 F15 상태 업데이트
- 전체 완료 보고
