# Consensus Revision Tracker

## Purpose
LLM 보고서 보조용 한국 종목 컨센서스 추적 시스템. 1차 신호는
EPS / 영업이익 / 매출 FY1 추정치의 revision, 2차 보조 신호는 목표주가
revision. 가중치 없는 evidence table 로 시작하고, alpha 검증·자동 매매
용도는 명시적으로 보류한다.

첫 대상 종목: SK hynix (000660).

## Defaults (사용자 별도 결정 없이 진행 가능한 기본값)

| 항목 | 기본값 |
|---|---|
| Primary 목적 | LLM 보고서 보조 (C) |
| Secondary 목적 | 분석 대시보드 (B) |
| Deferred | 자동 매매 신호 (A) |
| 예산 | 0 KRW / month |
| 외부 배포 | false |
| 수집 모드 | metadata only (Phase 0-A1) |
| Live network | false (default) |
| 대상 종목 | 000660 SK hynix |
| Snapshot 빈도 | daily (계획) |

위 기본값에 반대하면 사용자가 수정값을 알려주어야 하고, 그 외에는 기본값으로
진행한다. **유료 가입, API key 사용, 로그인 페이지 접근, 외부 배포, 자동
스크래핑은 별도 명시적 승인이 필요**하다.

## Phase 0-A1: Static Source Access Audit (이 문서가 다루는 단계)

목표: 후보 데이터 소스의 *설정* 자체를 감사. **금융 데이터 본문은 수집하지
않으며, 외부 네트워크 호출도 하지 않는다.**

### Invariants
- `network_calls_made == 0` (출력 JSON 에 명시).
- 모든 source 의 `financial_data_fetch_allowed` 는 false 여야 한다.
- `--live`, `--fetch-data` 플래그는 거부된다 (exit 4).
- 어떤 API key 도, .env 도, 로그인 자격 증명도 읽지 않는다.

### Files
- `tools/consensus/source_access_audit.py` — audit 도구.
- `configs/consensus_sources.json` — 후보 소스 7개 (FnSpace, Naver Finance,
  Hankyung Consensus, Investing, DART, Finnhub, yfinance).
- `configs/policy_keywords.json` — ko/en × 6 카테고리 (automation,
  redistribution, login, api_key, storage, commercial_use).
- `tests/consensus/test_source_access_audit.py` — mock-only pytest.
- `output/consensus_audit/source_access_audit.json` — 실행 결과.
- `docs/consensus_revision_tracker.md` — 이 문서.

### CLI
```
python tools/consensus/source_access_audit.py \
  --config configs/consensus_sources.json \
  --policy configs/policy_keywords.json \
  --out output/consensus_audit/source_access_audit.json
```

### Exit Codes
| Code | 의미 |
|---|---|
| 0 | audit 완료, 출력 작성됨 |
| 1 | source config 무효 (필드 누락·중복·금지 플래그 위반) |
| 2 | 출력 파일 쓰기 실패 |
| 4 | 금지된 플래그 (`--live`, `--fetch-data`) |
| 5 | policy keyword config 무효 |
| 6 | 출력 스키마 검증 실패 |

### Done Criteria (Phase 0-A1)
- DC-1: `tools/consensus/source_access_audit.py` 존재.
- DC-2: `configs/consensus_sources.json` 의 sources 가 7개 이상.
- DC-3: `configs/policy_keywords.json` 에 ko/en 카테고리 6개 모두 존재.
- DC-4: 기본 실행이 외부 네트워크를 호출하지 않음.
- DC-5: `output/consensus_audit/source_access_audit.json` 생성.
- DC-6: 출력 JSON 의 `network_calls_made == 0`.
- DC-7: `--live` 거부 (exit 4).
- DC-8: `--fetch-data` 거부 (exit 4).
- DC-9: pytest mock-only 테스트 통과.
- DC-10: `python -m compileall` 통과.
- DC-11: 본 문서가 purpose, exit codes, point-in-time rule, 다음 phase 를 설명함.
- DC-12: 어떤 금융 데이터 페이지도 fetch 하지 않음.
- DC-13: 어떤 API key / secret / env 도 읽지 않음.
- DC-14: 어떤 commit / push 도 수행하지 않음.

## Point-in-Time Rule (시스템 영구 불변 원칙)

- **매일 저장한 snapshot 만 historical truth 로 인정한다.**
- 무료 페이지 (Naver / Hankyung / Investing) 의 "과거 컨센서스 화면" 은
  retroactive 수정 가능성 (Ljungqvist, Malloy, Marston 2009, JoF 에서
  I/B/E/S 1.6~21.7% record change 보고) 이 존재하므로 시계열로 직접 사용하지 않는다.
- backtest 또는 alpha 검증을 시도하기 전에 최소 60-90 일의 자체 daily
  snapshot 누적이 선행되어야 한다.
- Phase 0-A1 은 snapshot 을 시작하지 않는다. 이 단계는 *소스 자체가 안전한지*
  의 사전 검증.

## Next Phases (선언만, 이 PR 에선 미구현)

- **Phase 0-A2 (Static)**: robots.txt / terms 페이지 *파일* 을 사용자가 수동으로
  내려받아 정적 분석. 여전히 외부 네트워크 호출 0회. policy keyword 일치
  여부 기록.
- **Phase 0-B1 (Live policy audit, opt-in)**: `--live` 플래그가 도입되는 첫
  단계. **단, robots.txt 와 terms URL 로 한정**. 금융 데이터 본문 fetch 금지.
  사용자 명시 승인 필요.
- **Phase 0-B2 (Single-source smoke test)**: 단일 종목, 단일 소스, 1회 fetch.
  evidence schema 와 별개로 *smoke* 결과만 기록.
- **Phase 0-C (Day 1 snapshot writer)**: daily snapshot 시작. point-in-time
  invariant 활성화. 누적 7일 안정성 검증 후 Phase 1 로 진입.

## Verification Reporting Rule

본 phase 의 산출물을 검증할 때 다음을 지켜야 한다.

- `git status --short` 는 항상 raw 그대로 보고한다. **사전에 존재하던 변경이 있을 수 있으며, 그 경우 "clean" 으로 보고해서는 안 된다.**
- Phase 14-0-A1 이 추가/수정한 파일은 다음과 같다:
  - `ROADMAP.md` (1-line 추가)
  - `configs/consensus_sources.json`, `configs/policy_keywords.json`
  - `tools/consensus/source_access_audit.py`, `tools/__init__.py`, `tools/consensus/__init__.py`
  - `tests/consensus/test_source_access_audit.py`, `tests/__init__.py`, `tests/consensus/__init__.py`
  - `docs/consensus_revision_tracker.md` (본 문서)
  - `output/consensus_audit/.gitkeep`, `output/consensus_audit/source_access_audit.json`
- 그 외 항목 (예: `.claude/agents/*.md`, `data/collection_report_v2.json`, `pending_requests.json`, 그 외 `??` 항목들) 은 **본 phase 와 무관한 사전 변경** 이며, 본 phase 의 책임이 아니다.
- pytest 출력은 head/tail 로 잘라 보고하지 말고, 최소한 최종 요약 라인 (`N passed in X.XXs`) 과 exit code 를 함께 raw 로 보고한다.

## Risk Register (현재 인지된 항목)

- **Naver / Investing HTML 구조 변경**: 운영형 MVP 의 가장 큰 깨짐 요인.
  parser health-check 가 별도 도입되어야 함.
- **FnSpace 비용·라이선스**: 개인 가입 가능성과 월 비용 미확정. Phase 0-B
  진입 전 사용자 결정 필요.
- **Korean sell-side optimism bias** (KCMI 2025: Buy 93.1%, Sell 0.1%):
  Buy/Hold/Sell 카운트는 한국 시장에서 신호 가치가 낮음. revision 중심으로
  설계.
- **Target price 정확도 한계** (Bradshaw, Brown, Huang 2013: 12-month
  end-of-period 38%, MAFE 45%): 목표주가는 1차 예측 신호가 아닌 2차
  sentiment proxy 로만 사용.

## References (인용된 학술/기관 자료)

- Bradshaw, M., Brown, L., Huang, K. (2013), "Do sell-side analysts exhibit
  differential target price forecasting ability?", *Review of Accounting Studies*.
- Ljungqvist, A., Malloy, C., Marston, F. (2009), "Rewriting history",
  *Journal of Finance*.
- KCMI (2025), "Optimism Bias in Analyst Research".
- Asquith, P., Mikhail, M., Au, A. (2005), "Information content of equity
  analyst reports", *Journal of Financial Economics*.
- Hong, H., Lim, T., Stein, J. (2000), "Bad news travels slowly: size,
  analyst coverage, and the profitability of momentum strategies",
  *Journal of Finance*.
