# AI Analyzer Agent Team (.claude/agents/)

Level 10 Agent Team 구조. 대표님 제안 5개 → 14개로 확장.
각 에이전트는 6개 항목(책임/입력계약/출력계약/허용행위/금지행위/검증요구)을 모두 명시.

## 5개 제안 대비 추가된 것

| 추가 | 이유 |
|------|------|
| 입력/출력 계약 | 에이전트 간 데이터 불일치 방지 (SD-8 vs NQ-4 류) |
| 금지 행위 | 범위 침범 방지 |
| 검증 요구 | "성공 기본값"(RC-1) 방지 |
| evaluator/validation/audit | 문제 대부분이 검증 단계에서 발생 |
| meta-audit | PM 자기감사 (오늘 못 잡은 추적성 문제) |
| routing 테이블 | 작업→에이전트 분류 |

## 에이전트 레이어

- 오케스트레이션: orchestrator
- 데이터: data-agent, news-agent
- 분석: analysis-agent, stock-agent, sector-agent
- 검증: evaluator-agent, validation-agent, audit-agent
- 의사결정/출력: decision-agent, narrative-agent, ui-agent
- 배포: report-agent
- 자기감사: meta-audit-agent

## 라우팅 테이블 (작업 유형 → 에이전트)

| 작업 유형 | 담당 에이전트 | 검증 에이전트 |
|----------|--------------|--------------|
| 데이터 수집 | data-agent | validation-agent |
| 시황 생성 | news-agent | audit-agent (URL/제목 검증) |
| 가중치 분석 | analysis-agent | evaluator-agent |
| 종목 분석 | stock-agent | evaluator-agent (교차검증) |
| 산업 분석 | sector-agent | validation-agent |
| 의사결정 | decision-agent | audit-agent (신뢰도 게이트) |
| 리포트 작성 | narrative-agent | audit-agent (템플릿 위장 탐지) |
| 대시보드 | ui-agent | validation-agent (Pages 200) |
| 배포 | report-agent | — |
| 명세-구현 점검 | audit-agent | — |
| PM 자기점검 | meta-audit-agent | — |
| 전체 조율·최종판단 | orchestrator | evaluator+validation+audit 3종 |

## 설치 방법

1. 프로젝트 루트에 `.claude/agents/` 디렉토리 생성
2. 이 14개 .md 파일을 그 안에 복사
3. Claude Code에서 `/agents` 실행 → 14개 인식 확인
4. orchestrator부터 단계적으로 실제 호출 테스트

## 전환 원칙 (한 번에 다 바꾸지 말 것)

기존 Python 스크립트 → /agent 전환은 **단계적으로**.
1단계: narrative-agent (이미 /agent 방식, 검증용)
2단계: 검증 3종(evaluator/validation/audit) 추가
3단계: 데이터/분석 에이전트 순차 전환
각 단계마다 기존 파이프라인과 결과 비교(회귀 확인) 후 다음 단계.
