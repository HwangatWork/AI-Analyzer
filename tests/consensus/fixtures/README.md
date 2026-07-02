# tests/consensus/fixtures/ — 정직 메타

meta-audit 9차 Q4 CRITICAL fix (2026-07-02): fixture 소스 정합성 문서화.

## 파일 목록

| 파일 | source | fetched_at | purpose |
|------|--------|------------|---------|
| `robots_sample_allowed.txt` | SYNTHETIC | N/A | Phase 14-0-A2 positive path (allow /) |
| `robots_sample_denied_all.txt` | SYNTHETIC | N/A | Phase 14-0-A2 negative path (Disallow: /) |
| `wisereport_000660_sample.html` | wisereport.co.kr (14-1) | 2026-06-30 | Phase 14-1 naver_parser 회귀 |

## Silent drift 방지 룰

- **SYNTHETIC fixture**: 합성 텍스트, 실 사이트 정책과 무관. static analyzer 자체의
  parsing 정합성만 검증. 실 사이트 부합 여부는 Phase 14-0-B1 (live policy audit) 책무.
- **캡처된 fixture**: source URL + fetched_at ISO 필수. 사이트 정책 변경 시 재캡처.
- **정합성 감사**: `tools/consensus/robots_check.py` (14-0-B2 live) 가 매 실행마다 실
  사이트 robots.txt fetch → 이 fixture 와 diff 발생 시 refresh 필요.

## refresh cadence
- SYNTHETIC: manual (테스트 로직 변경 시)
- 캡처된 fixture: 분기 1회 또는 사이트 정책 변경 감지 시
