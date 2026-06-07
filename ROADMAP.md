# AI Analyzer ROADMAP

## 전체 비전 (5대 목표)
1. **AI 데이터 분석 대시보드 자동화** — 핵심 지표 AI 분석 → 직접 매수/매도 의사결정
2. **AI 반복 리포팅·분석 자동화** — 주 1회 자동 파이프라인, ntfy.sh 알림, AI 언어 리포트
3. **BI 대시보드로 의사결정 설득** — Looker Studio + GitHub Pages 시각화
4. **주식 산업·직무별 데이터 딥다이브** — 반도체/AI/에너지 섹터, 코스피/S&P500 동시 분석
5. **실무 AI 데이터 분석 도구 완성** — hook 기능으로 PM Agent가 승인할 때까지 LOOP 실행

## PM Agent 승인 조건 (A~H)
- [x] A) 코스피 종목 ±200% 초과 수익률 — FDR(KRX)+yfinance 교차검증 적용
- [x] B) 복합 시그널 점수(0~100) + 방향성 — Z-score 가중 합성, risk-on/neutral/risk-off
- [x] C) BI 시각화 접근 링크 — https://hwangatwork.github.io/AI-Analyzer/ (GitHub Pages 자동 배포)
- [x] D) 주 1회 자동화 파이프라인 — Task Scheduler + GH Actions cron 0 22 * * 0 + ntfy.sh
- [x] E) BUY/SELL/HOLD 의사결정 엔진 — 신뢰도%·포지션 사이징·진입/청산 트리거 (Decision Agent)
- [x] F) AI 언어 인사이트 + 액션플랜 — 한국어 자동 리포트, S&P500+코스피 실행 계획 (Narrative Agent)
- [x] G) CSV → Google Sheets → Looker Studio 파이프라인 — gspread 자동화 + GitHub Pages CSV URL (Sheets Agent)
- [x] H) 산업별 딥다이브 — 반도체/AI·AI플랫폼·에너지/원자재, 21개 종목 1Y/1M 수익률 (Sector Agent)

---

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

## Phase 5 - 시각화 (UI Agent v5 — 7개 서브 에이전트)
- [x] F15 매수/매도 의사결정 대시보드 (Decision Agent) — PM Condition E
- [x] F16 AI 한국어 리포트 + 액션플랜 (Narrative Agent) — PM Condition F
- [x] F17 시장 시그널 게이지 + Z-Score 바 (UX Signal Agent) — PM Condition B
- [x] F18 종목 기여/수혜 카드 (UX Stocks Agent) — PM Condition A
- [x] F19 산업별 딥다이브 섹터 분석 (Sector Agent) — PM Condition H
- [x] F20 Google Sheets + Looker Studio 연동 (Sheets Agent) — PM Condition G
- [x] F21 지표 랭킹 + 데이터 품질 (UX Indicators Agent) — PM Condition C

## Phase 6 - 자동화 (Automation)
- [x] run_pipeline.bat — 전체 파이프라인 순차 실행
- [x] GitHub Actions — push + cron 0 22 * * 0 자동 배포
- [x] ntfy.sh 알림 — 완료/실패 push notification
- [x] CLAUDE.md 영구 권한 — PM Agent 자율 실행 (확인 불필요)

## Phase 7 - 완료
- [x] output/final_results.json — PM Conditions A~H 전항목 PASS
- [x] output/dashboard.html — 7탭 대시보드 (v5)
- [x] https://hwangatwork.github.io/AI-Analyzer/ — GitHub Pages 라이브

---

## Agent Teams 현황 (L0~L2)

### L0: PM Agent (Claude — 오케스트레이터)
- 전체 ROADMAP 해석, Agent 분배, 승인 조건 검증
- 영구 실행 권한: git push/commit, python 실행, GitHub API, ntfy.sh

### L1: 핵심 에이전트
- **Data Agent** (run_data_agent_v2.py) — 29개 지표 1년치 수집
- **Analysis Agent** (run_analysis_agent_v2.py) — 상관관계·가중치 분석
- **Stock Agent** (run_stock_agent_v2.py) — 지수 기여/수혜 기업 분석
- **Evaluator Agent** (run_evaluator_agent_v2.py) — 통계 검증 (p<0.05)
- **UI Agent** (run_ui_agent.py) — 7개 서브 에이전트 오케스트레이션

### L2: UX/분석 서브 에이전트 (7개)
- **Decision Agent** (run_decision_agent.py) — BUY/SELL/HOLD 의사결정
- **Narrative Agent** (run_narrative_agent.py) — AI 한국어 리포트
- **UX Signal Agent** (run_ux_signal_agent.py) — 시그널 게이지
- **UX Stocks Agent** (run_ux_stocks_agent.py) — 종목 카드
- **Sector Agent** (run_sector_agent.py) — 산업별 딥다이브
- **Sheets Agent** (run_sheets_agent.py) — Looker Studio 연동
- **UX Indicators Agent** (run_ux_indicators_agent.py) — 지표 랭킹

---

## Orchestrator 실행 지침
1. Phase 1 완료 확인 후 즉시 Phase 2 시작
2. Phase 2 Data Agent 단독 실행 -> 완료 후 Phase 3 병렬 실행
3. Analysis Agent + Stock Agent 동시 실행 (독립 작업)
4. 둘 다 완료 후 Evaluator Agent 실행
5. 검증 통과 후 UI Agent 실행 (7개 서브 에이전트 자동 호출)
6. 모든 [?] 항목 제거됨 - 사람 개입 없이 끝까지 자율 실행
7. PM Conditions A~H 모두 PASS 확인 후 완료 보고
8. 완료 시 ntfy.sh 알림 + output/FINAL_REPORT.md 업데이트
---
