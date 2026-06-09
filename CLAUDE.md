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

## Agent 완료 기준 (Done Criteria) — 시스템 핵심 원칙

**각 Agent는 파일을 생성하는 것으로 "완료"가 아니다.**
**자신의 산출물이 품질 기준을 충족하는지 코드 내에서 직접 검증하고, 실패 시 exit(1)로 파이프라인을 차단한다.**

### 왜 이 원칙이 존재하는가
PM Conditions A-H가 모두 데이터/백엔드 기준이었고, UX 기준이 전무했다.
각 Agent가 "에러 없이 실행 완료 = 성공"으로 작동했기 때문에, 사용자가 이해할 수 없는
대시보드가 "통과" 처리됐다. 이 원칙은 해당 구조적 결함을 제거하기 위해 도입되었다.

### 각 Agent의 Done Criteria (코드 내 자체검증 의무)

| Agent | Done Criteria 코드 위치 | 핵심 조건 |
|-------|----------------------|-----------|
| Stock Agent | `run_stock_agent_v2.py` `__main__` 끝 | 동적 유니버스, ≥50 KOSPI, ≥100 SP500, 중복 없음 |
| Evaluator Agent | `run_evaluator_agent_v2.py` 끝 | ≥5 유효 지표, 방법론 체크리스트 |
| Validation Agent | `run_validation_agent.py` L1~L6 | 30개 체크 전항목, CRITICAL=0 |
| UI Agent | `run_ui_agent.py` `__main__` 자체검증 블록 | UX-1~UX-7 모바일/경고/HOLD/신뢰도 |

**새로운 Agent를 추가할 때는 반드시 Done Criteria 자체검증 블록을 포함해야 한다.**
Done Criteria 없는 Agent는 코드 리뷰에서 반려한다.

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

## 방법론 검증 체크리스트 (PM Agent 의무 확인)

**모든 분석 실행 전·후에 반드시 확인해야 하는 항목들.**
"결과가 그럴듯해 보인다"는 이유만으로 검증을 생략하는 것은 금지.

### 유니버스 검증
- [ ] U1. 분석 대상이 동적으로 수집되는가? (하드코딩 리스트 = 즉시 거부)
- [ ] U2. KOSPI 분석 시 전체 KRX 상장 기업 중 시총 기준으로 정렬했는가?
- [ ] U3. S&P500 분석 시 공식 구성종목 전체를 대상으로 했는가?
- [ ] U4. 유니버스 크기를 결과와 함께 명시했는가? (예: "100개 중 Top5")

### 데이터 품질 검증
- [ ] D1. FDR + yfinance 교차검증 완료 (수익률 차이 100%p 초과 시 불일치 플래그)
- [ ] D2. 최소 거래일수 충족 (≥50일)
- [ ] D3. 시가총액 단위 일관성 확인 (KRW/USD, 원/억원/조원 혼동 없음)
- [ ] D4. 분석 기간 일치 확인 (START~END 동일 적용)

### 결과 타당성 검증 (확증 편향 방지)
- [ ] R1. 1위 결과가 예상과 다를 때, 데이터 오류인지 실제 현상인지 검증한다
- [ ] R2. 기존 결과와 크게 다른 새 결과는 "왜 달라졌는가"를 설명해야 함
- [ ] R3. Top N에 없는 종목이 실제로 높은 수익률을 기록했다는 제보 → 유니버스 재검토 의무
- [ ] R4. 극단적 수익률(±500%이상) 종목은 데이터 이상 여부를 우선 의심하고 검증

### 방법론 검증
- [ ] M1. contribution_score 공식: |corr| × |1Y_return| × (marcap_현재가 / 기준단위)
- [ ] M2. beneficiary_score 공식: excess_return × |corr|
- [ ] M3. 시가총액은 시작 시점 기준 사용 (지수 기여도는 시작 시점 비중이 적절)
- [ ] M4. 동일 기업 복수 클래스 주식 처리 (GOOGL/GOOG, 삼성전자/삼성전자우)

이 체크리스트를 통과하지 못한 결과는 output/에 저장하지 않는다.

## PM Condition I — UX 검증 체크리스트 (신규)

UI Agent가 dashboard.html을 생성한 후, 아래 항목을 반드시 검증한다.
**이 조건을 통과하지 못하면 dashboard.html을 output/에 저장하지 않는다.**

### I-1. 모바일 렌더링
- [ ] nav-tabs에 `overflow-x: auto; white-space: nowrap` 적용 (탭 텍스트 수직 깨짐 방지)
- [ ] @media (max-width: 768px)에서 grid-2/grid-3가 1열로 전환되는가
- [ ] 헤더/주요 컨텐츠가 360px 뷰포트에서 잘리지 않는가

### I-2. 데이터 품질 경고 표시
- [ ] 시가총액 $0B 종목: "미집계 ⚠" 표시 + 황색 경고 배너 ("최근 분사/상장" 설명)
- [ ] 수익률 ±1000% 초과 종목: ⚠ 아이콘 + "분사·합병 등 이벤트 영향 가능" 경고

### I-3. HOLD 신호 명확성
- [ ] HOLD 카드에 "신규 매수: 보류 / 기존 보유: 유지 / 추천 행동: 재확인" 텍스트 표시
- [ ] HOLD 시 포지션 바 0%가 아닌 상황 설명 텍스트로 대체

### I-4. 신뢰도 수치 설명
- [ ] 신뢰도 % 아래에 "지표 N개 중 M개 강세" 형태로 근거 표시

### I-5. 10초 이해 테스트 (자동 불가 — 주간 파이프라인 실행 후 수동 확인)
- [ ] 대시보드 첫 화면(매수/매도 탭)에서 시장 판단이 10초 내 파악 가능한가

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

## 구현 레벨 별 Evidence 요구사항 (REQ-018)

**레벨 8 이상 요청은 정적 분석(코드 읽기/grep)만으로 완료 처리 금지.**

| 구현 레벨 | 최소 Evidence 요구사항 |
|---------|---------------------|
| 레벨 5~6 | 파일/코드 위치 명시 (경로:라인번호) |
| 레벨 7   | 코드 레벨 검증 + 예상 동작 설명 |
| 레벨 8   | **동적 테스트 필수** — 실제 실행 exit code, 수치, 로그 출력 포함 |
| 레벨 9~10 | 레벨 8 + 엣지케이스/시뮬레이션 커버리지 |

**레벨 8 완료 보고 자가 체크리스트:**
- [ ] 정적 분석(코드 읽기)만인가? → 실제 실행 테스트 추가 후 재보고
- [ ] Evidence가 수치/로그인가? → 텍스트 설명만이면 미완료
- [ ] 이전에 같은 실수를 했는가? → CLAUDE.md에 패턴 추가

**재발 패턴 기록 (반복 실수 방지):**
- SD-12 B단계(2026-06-09): `exit(1) 존재 확인`을 정적 분석(grep)으로만 처리 → 실제 exit code=1 동적 확인 없이 완료 보고. 레벨 8 요청에 동적 테스트 필수.
- report_quality_check(): priority=high 항목에 수치/exit code 없으면 QR-1 경고 자동 발생
- SD-18(2026-06-09): `START = "2024-06-01"` 하드코딩 — 새 Agent 추가 시 날짜는 반드시 `datetime.now() - timedelta(days=N)` 형태로. 문서 주석의 날짜 리터럴도 동적 표현으로 대체.
- SD-19(2026-06-09): fix_request.md "자동 수정 계획" 항목이 실제 auto_fix 로직과 불일치 — 수정 계획 목록은 반드시 이슈 코드 기반으로 동적 도출해야 함.
- SD-20(2026-06-09): 세션 중 발견한 새 패턴을 SD 테이블에 즉시 추가하지 않음 — 새 SD 코드 발견 시 pm_self_diagnosis()에 블록 추가 + CLAUDE.md SD 테이블 동시 업데이트 의무.

## 작업 완료 보고 표준 형식 (의무 준수)

**모든 작업 완료 시 아래 4개 섹션 순서로 보고한다.**
문제점을 긍정적 결과보다 반드시 먼저 기재. 추측성 보고 금지 — 검증된 사실만.

### 섹션 1. 요청 vs 결과 대조
| 요청 항목 | 상태 | 핵심 결과 |
|----------|------|----------|
각 요청 항목을 ✅ 완료 / ⚠️ 부분 완료 / ❌ 실패 로 표시.

### 섹션 2. 발견된 문제 (있을 경우만)
작업 중 발견한 이상·누락·오류를 긍정적 내용보다 먼저 제시.
없으면 이 섹션 생략.

### 섹션 3. 변경된 파일
파일명 + 변경 내용 한 줄 요약 목록.

### 섹션 4. 검증 결과
- pm_quality_checks: N/N PASS
- Done Criteria: 각 Agent Done Criteria 통과 여부
- Evidence: 실제 수치, 실행 출력값 (추측 금지)

### 미완료 항목 처리
완료 보고 후 미완료 항목이 있으면 pending_requests.json에 자동 등록.

## GitHub Actions 완료 보고 규칙

**GitHub Actions run-pipeline PASS Evidence 없이 완료 보고 금지.**

- CI 관련 작업(T7 등)은 실제 workflow run-pipeline job `conclusion=success` 확인 후에만 완료 처리
- 로컬 파일 수정(requirements.txt 추가, env vars 추가)만으로는 "CI 통과" 보고 불가
- 성공 기준: GitHub API 또는 Actions 탭에서 run-pipeline job conclusion=success 직접 확인
- 미확인 상태는 ROADMAP.md에서 `[⚠]` 표시 유지 (완료 `[x]` 처리 금지)

## SA-5 vs SA-6 체크 목적 구분

| 체크 | 대상 | 기준 | 이유 |
|------|------|------|------|
| SA-5 | S&P500 기여 Top1 | 시총 ≥ $200B | S&P500 구성종목은 대형주 보장 — 소형주가 Top1이면 데이터 오류 가능성 |
| SA-6 | KOSPI 기여 Top1 | 존재 + 시총 > 0 | contribution_score에 시총 가중치 내포. 소형주도 고수익률·고상관으로 Top1 가능. 금액 임계값 = 이중 체크 |

**SA-6 금액 기준을 두지 않는 이유**: `contribution_score = |corr| × |1Y_return| × 시총` 에서 시총이 작으면 자연히 점수가 낮아진다. 소형주가 Top1이 된다면 그 수익률/상관이 실제로 압도적임을 의미한다. 별도 시총 임계값은 이미 내포된 조건을 중복 검사하는 것이다.

**SA-6 FAIL 조건**: `ksp_cont` 가 비어있거나 Top1의 시총이 0 (시총 데이터 수집 실패).

## IQ-1 동행 지수 페널티 — 하드 필터 기준

아래 4개 지수는 S&P500/코스피와 **동시점 동행** 관계여서 Evaluator에서 완전 제외한다.
선행성(Granger) 없이 상관관계만 높은 지표는 "원인 지표"가 아니다.

```
_CONTEMPORANEOUS = {"NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"}
```

- IQ-1 필터는 p-value나 신뢰도 체크 이전에 적용 (hard filter)
- 동행 지수가 가중치 랭킹 상위에 등장하면 즉시 Evaluator 재실행
- 이 규칙은 `run_evaluator_agent_v2.py` `_CONTEMPORANEOUS` 변수로 구현됨

## 자기참조 지표 제외 목록 — Evaluator 필터

아래 5개 지표는 **가격에서 직접 유도**되어 Granger 인과관계가 순환논리가 된다.
Z-Score 계산 및 가중치 랭킹에서 제외한다.

```
_SELF_REFERENTIAL = {"RSI14", "MA50", "RSI_SIGNAL", "BETA", "MA_SIGNAL"}
```

- MA200은 장기 추세 지표로 유효 — 포함 유지
- BBAND, STOCH_RSI, MARKET_MOMENTUM은 지연 지표(lagged)로 유효 — 포함 유지
- 이 규칙은 `run_evaluator_agent_v2.py` `_SELF_REFERENTIAL` 변수로 구현됨

## pm_self_diagnosis SD 기준 (SD-1~14)

`run_pm_agent.py`의 `pm_self_diagnosis()` 함수가 자동 탐지하는 이슈 목록.

| 코드 | 탐지 기준 | 자동 수정 여부 |
|------|-----------|----------------|
| SD-1 | 동행 지수(NASDAQ100/DOW/KOSDAQ/NIKKEI225)가 가중치 Top5에 존재 | ✅ Evaluator 재실행 |
| SD-2 | 자기참조 지표(RSI14/MA50 등)가 Z-Score 계산에 포함 | ✅ Evaluator 재실행 |
| SD-3 | Z-Score 지표 수 ≠ f14_final_ranking 수 | ✅ UI Agent 재실행 |
| SD-4 | 시그널 점수 범위 이상 (0 미만 또는 100 초과) | ✅ 재계산 |
| SD-5 | decision.json 미존재 또는 필수 필드 누락 | ✅ Decision Agent 재실행 |
| SD-6 | narrative_context.json 미존재 | ✅ Narrative Agent 재실행 |
| SD-7 | GitHub Actions 마지막 run-pipeline conclusion ≠ success | ❌ 수동 확인 필요 |
| SD-8 | News Agent URL이 뉴스 기사가 아닌 홈페이지 URL | ✅ News Agent 재실행 |
| SD-9 | TG 중복 전송 감지 (동일 해시 60s 이내) | ✅ 전송 차단 (자동) |
| SD-10 | Agent 파일 헤더 'Claude API 사용' 주장 vs 실제 API 호출 코드 불일치 | ❌ 수동 코드 수정 |
| SD-11 | 하드코딩 위장 패턴 탐지 (리터럴 기업명 3개+, `if True:` 우회, TODO stub) | ❌ 수동 코드 수정 |
| SD-12 | Done Criteria 정의 있으나 exit(1) 가드 없는 Agent 탐지 | ❌ 수동 코드 수정 |
| SD-13 | 빈 리스트에서 vacuously True가 되는 Done Criteria 조건 탐지 | ✅ Validation 재실행 |
| SD-14 | QC PASS 수가 기준선 대비 감소 (회귀) — Telegram 즉시 알림 | ✅ Validation 재실행 |
| SD-15 | pm_quality_checks() 지지 데이터 비어있는데 PASS (vacuous) — SA-7/SA-8 | ❌ 수동 확인 |
| SD-16 | final_results.json / decision.json 25시간 초과 — 파이프라인 미실행 가능성 | ❌ 수동 확인 |
| SD-17 | 핵심 출력 파일 크기 이상 (<1KB 빈파일 / >5MB 팽창) | ❌ 수동 확인 |
| SD-18 | Agent 파일 내 하드코딩 날짜 리터럴 (START 날짜 고정 등) | ✅ 동적 산출로 교체 |
| SD-19 | fix_request.md 자동 수정 계획이 실제 auto_fix 로직과 불일치 | ✅ _write_fix_request 동기화 |
| SD-20 | 이번 세션 발견 패턴 미반영 — SD 테이블/CLAUDE.md 재발방지 섹션 미업데이트 | ❌ 수동 CLAUDE.md 수정 |
