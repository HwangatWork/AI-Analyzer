# 6-Layer Agentic Engineering 감사 기준

AI Analyzer 14개 Agent에 대한 설계 품질 평가. 각 Layer 10점 만점.

## Layer 1: Identity & Scope (정체성/범위)
- 각 에이전트가 명확한 책임 경계를 가지고 있는가?
- 입력/출력 계약(계약 기반 인터페이스)이 정의됐는가?
- .claude/agents/*.md frontmatter(name/description/tools) 완비 여부
- 단일 책임 원칙: 한 파일이 두 개 이상의 에이전트 역할을 담당하는가?

## Layer 2: Action Contracts (행위 계약)
- 금지 행위가 실제 코드에서 준수되는가?
- 에이전트가 자신의 영역 밖의 작업을 수행하는가?
- data-agent가 분석(regression/zscore) 수행 여부
- audit-agent가 코드 수정 여부
- Done Criteria가 정의된 에이전트의 검증 섹션 완비 여부

## Layer 3: Verification (자체 검증)
- Done Criteria + exit(1) 가드 동시 존재 여부 (SD-12 기준)
- 빈 리스트에서 vacuously True가 되는 조건 없는가? (SD-13 기준)
- 자체 검증이 실제로 파이프라인을 차단하는가?

## Layer 4: State Management (상태 관리)
- baseline/pending/progress 파일이 올바르게 갱신되는가?
- 세션 간 상태 연속성(pm_baseline.json, pending_requests.json)
- claude-progress.txt가 실제 실행 에이전트에 의해 갱신되는가?
- updated 타임스탬프 하드코딩 여부 (SD-18)

## Layer 5: Observability (관찰 가능성)
- 핵심 에이전트에 Telegram 알림이 연결됐는가?
- 실패 시 로그가 진단 가능한 형태로 출력되는가?
- SD-7~SD-20 자가진단이 실제 이슈를 커버하는가?

## Layer 6: Governance (거버넌스)
- CLAUDE.md 규칙이 코드에 실제로 구현됐는가?
- 재발 방지 패턴이 체크리스트에 등록됐는가?
- 새 에이전트 추가 가이드라인이 명문화됐는가?
- meta-audit-agent가 전체 감사 루프를 닫는가?
