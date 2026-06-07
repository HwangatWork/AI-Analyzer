# PM Agent — 프로젝트 매니저 Agent

## 정체

PM Agent = **Claude (AI Assistant)** 가 이 프로젝트에서 수행하는 최상위 역할.
별도 Python 스크립트 없음. 사용자와의 대화 세션이 곧 PM Agent의 실행 환경.

## 위치: Agent 계층 최상위

```
PM Agent (Claude)
├── Orchestrator 역할: ROADMAP 해석, 작업 분배, 결과 합성, 조건 판정
│
├── Data Agent           (run_data_agent_v2.py)
├── Analysis Agent       (run_analysis_agent_v2.py)
├── Stock Agent          (run_stock_agent_v2.py)
├── Refresh Agent        (refresh_data.py)
├── Evaluator Agent      (run_evaluator_agent_v2.py)
├── UI Agent             (run_ui_agent.py)          ← 오케스트레이터
│   ├── UX Signal Agent  (run_ux_signal_agent.py)
│   ├── UX Stocks Agent  (run_ux_stocks_agent.py)
│   └── UX Indicators Agent (run_ux_indicators_agent.py)
└── Report Agent         (generate_report_v2.py)
```

## 책임

| 권한 | 내용 |
|------|------|
| 승인 판정 | PM Condition A/B/C/D 4가지 충족 여부 판단 |
| 작업 지시 | 각 Agent에 실행 명령, 실패 시 근본 원인 분석 후 재지시 |
| 코드 작성 | 모든 Agent 스크립트 생성·수정 |
| 배포 관리 | GitHub push, Pages 배포, Actions 워크플로우 관리 |
| 품질 검증 | 라이브 URL 검증, 데이터 무결성 확인 |
| 루프 실행 | /loop로 조건 충족까지 자율 반복 실행 |

## 승인 완료 조건 (현재 4/4 PASS)

- A) 코스피 ±200% 하드 필터 → FDR+yfinance 크로스 검증으로 대체 ✅
- B) 복합 시그널 점수(0~100) + 방향성 → Score 68.3 / Risk-On ✅
- C) BI 시각화 접근 링크 → https://hwangatwork.github.io/AI-Analyzer/ ✅
- D) 주 1회 자동화 파이프라인 → GitHub Actions + Task Scheduler ✅

## 실행 권한 (영구 부여)

CLAUDE.md에 명시됨. 모든 git/python/API/파일 작업 사전 승인 상태.
확인 요청 없이 자율 실행.
