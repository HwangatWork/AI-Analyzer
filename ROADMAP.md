# AI Analyzer ROADMAP

## 실행 방법
Claude Code에서 이 파일을 읽고 Agent Teams를 생성한다.
[ ] = 자동 실행, [?] = 대표님 확인 필요, [x] = 완료

---


## Phase 1 - 환경 준비
- [x] 프로젝트 구조 생성
- [x] Agent Teams 활성화
- [x] CLAUDE.md / feature_list.json / agent 파일 작성
- [x] FRED API 키 .env 등록 확인

## Phase 2 - 데이터 수집 (Data Agent)
- [x] F01 시장 지수 6개 수집 (FDR) — 6/6 성공
- [x] F02 매크로 지표 6개 수집 (FRED API) — 6/6 성공
- [x] F03 시장 심리 지표 수집 — 4/6 (CNN/PutCall API 차단)
- [x] F04 기술적 지표 8개 산출 — 8/8 성공
- [x] F05 수급 3개 수집 (pykrx) — 0/3 (KRX 로그인 미등록)

## Phase 3 - 분석 (Analysis Agent + Stock Agent 병렬)
- [x] F06 지표별 S&P500 상관관계 분석
- [x] F07 지표별 코스피 상관관계 분석
- [x] F08 가중치 랭킹 생성 — 유효 13개 지표
- [x] F09 S&P500 기여 기업 Top5 — Alphabet/NVIDIA/Broadcom/Apple/Tesla
- [x] F10 코스피 기여 기업 Top5 — SK하이닉스/삼성전자/현대차/현대모비스/LG전자
- [x] F11 S&P500 수혜 기업 Top5 — Broadcom/Tesla/Alphabet/NVIDIA/Oracle
- [x] F12 코스피 수혜 기업 Top5 — SK하이닉스/삼성전자/현대모비스/LG전자/현대차

## Phase 4 - 검증 (Evaluator Agent)
- [x] F13 통계적 유의성 확인 — SP500 11개 / KOSPI 9개 유의
- [x] F14 이상값 필터링 및 신뢰도 점수 산출
- [x] 신뢰도 70점 미만 14개 지표 자동 제외 (Option A 자율 판단)

## Phase 5 - 시각화 (UI Agent)
- [x] F15 CTD 대시보드 컴포넌트 생성 — output/final_results.json

## Phase 6 - 완료
- [x] output/final_results.json 저장 완료
- [x] 전체 완료 보고서 output/FINAL_REPORT.md 작성 완료

---

## Orchestrator 실행 지침
1. Phase 1 완료 확인 후 즉시 Phase 2 시작
2. Phase 2 Data Agent 단독 실행 -> 완료 후 Phase 3 병렬 실행
3. Analysis Agent + Stock Agent 동시 실행 (독립 작업)
4. 둘 다 완료 후 Evaluator Agent 실행
5. 검증 통과 후 UI Agent 실행
6. 모든 [?] 항목 제거됨 - 사람 개입 없이 끝까지 자율 실행
7. 완료 시 output/FINAL_REPORT.md 에 전체 결과 요약 저장
---
