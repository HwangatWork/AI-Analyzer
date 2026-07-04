# SQLite 스키마 설계 — AI Analyzer

- 작성일: 2026-07-04
- 상태: 초안 (사용자 검토 대기 · 코드 생성/DB 파일 생성 없음)
- 범위: 매크로 지표 29개 parquet + 컨센서스 트래커 immutable snapshot + 라이브 가격 오버레이 + 글로벌 IB + accuracy state 를 하나의 SQLite 데이터베이스로 통합할지에 대한 스키마 설계와 대안

---

## 0. 실측 근거 (Evidence)

설계에 앞서 실제 파일을 열어 확인한 내용. 스키마 결정의 정합성은 아래 fact 로 검증한다.

### 0.1 매크로 지표 parquet (29 개 중 관측)

| 파일 | rows | source 컬럼 | 첫 source 값 | date range |
|---|---|---|---|---|
| NASDAQ100 | 274 | O | `FDR:QQQ` | 2025-05-16 → 2026-06-18 |
| SP500 | 274 | O | `FDR:US500` | ~ |
| VIX | 275 | O | `FDR:^VIX` | ~ |
| FED_ASSETS | 57 | O | `FRED:WALCL` | 주간 (2025-05-21 → 2026-06-17) |
| KOSPI | 266 | O | `FDR:KS11` | ~ |
| BBAND | 255 | O | `CALC:BBAND_pctB` | 계산 파생 |
| RSI14 | 260 | O | `CALC:RSI14` | 계산 파생 |
| CNN_FG | 400 | O | `alternative.me:FnG` | 400 rows (더 긴 히스토리) |
| SEMICONDUCTOR_EXPORT | 23 | X | (누락) | 월간 |
| DXY | 268 | X | (누락) | |
| MARKET_STRENGTH | 175 | X | (누락) | |
| WTI | 268 | X | (누락) | |

**공통 스키마**: `date: datetime64[ns]`, `value: float64`, `source: object` (일부 누락).
**date 유일성**: FED_ASSETS 기준 `n_unique_dates == n_rows` — 지표별로 (indicator, date) 조합은 유일.
**source 4 종 누락**: DXY / MARKET_STRENGTH / WTI / SEMICONDUCTOR_EXPORT — 스키마 상에서 NULL 허용 필요.

### 0.2 컨센서스 parsed.json (schema_version 0.3)

`output/consensus_snapshot/000660_2026-07-03_parsed.json` 실측 top-level 키:

```
annual_indicators     dict  (fy_labels + metrics{BPS, EPS, PBR, PCR, PER, EV/EBITDA, EBITDA, 배당수익률})
chart_latest_target_date  str  '2026-05-...'
chart_latest_target_price float 2470417.0
close_price_latest    float 2628000.0
close_price_series    list  [{x_ms, y}, ...]  monthly WiseReport chartData2
target_price_series   list  [{x_ms, y}, ...]  monthly WiseReport chartData2
estimates             dict  {"2025/12(A)": {...}, "2026/12(E)": {...}}
global_ib             dict  (yfinance aggregate 요약)
global_ib_named       list  (per-firm named IB targets, 12 entries in this file)
investment_opinion    float 1.0
latest_target_price   float
n_analysts            int   24
opinion_breakdown     dict  {today, a_month_ago, found} — today = {buy, hold, sell, strong_buy, strong_sell, total}
parser_warnings       list
per_firm_targets      dict  {firms: [{firm, rating, target_price, prior_target_price, change_pct, report_date, prior_rating}, ...], n=6}
prior_target_price    float
quarterly_earnings    dict  {announce_dates, found, quarters: [{yymm, revenue_actual, revenue_consensus, ...surprise/qoq/yoy}], yymm}
reconciliation        dict  {chart_latest_target, close_latest, per_eps_close_diff_pct, per_times_eps, static_target, static_vs_chart_target_diff_pct}
schema_version        str  '0.3'
static_eps            float 307655.0
static_per            float 8.54
static_raw_cells      list
static_target_price   float 3177083.0
target_price_change_1m_pct  float
target_price_change_label   str
```

### 0.3 컨센서스 analysis.json

```
answers          dict  {Q1_direction, Q1_target_price_change_pct, Q2_..., Q5_details, Q5_global_vs_domestic}
company          str
data_quality     dict  {components: {estimates_present, investment_opinion, latest_target_price, n_analysts, sufficient_series_length, target_price_change_1m_pct}, score}
global_ib_named  list  (parsed.json 과 중복 저장됨)
meta_audit       dict
parser_warnings  list
raw_inputs       dict  (Q별 source metadata)
reconciliation   dict  (parsed.json 과 동일)
schema_version   str
ticker           str
```

### 0.4 fetch.json (raw HTML provenance)

```
bytes            int
company          str
encoding_detected str
errors           list
exit_code        int
fetched_at       str  ISO8601 with TZ '2026-06-30T07:52:25+09:00'
http_status      int
raw_html_path    str  'output/consensus_snapshot\\000660_2026-06-30_raw.html'
robots_decision  dict (allowed, reason, robots_status, robots_url, url, user_agent)
sha256           str  raw HTML 의 64자 hex
source           str  'wisereport'
ticker           str
url              str
```

### 0.5 history manifest.json (immutable point-in-time 잠금)

`output/consensus_snapshot/history/000660/2026-07-03/manifest.json` :

```
date              str
files             dict  {analysis.json: sha256, parsed.json: sha256, report.md: sha256}
pipeline_git_head_sha  str
schema_version    str  '1.0'
ticker            str
top_sha256        str  Merkle-style aggregate hash
written_at_utc    str
```

이미 파일 시스템 수준에서 sha256 매니페스트가 존재한다. SQLite 스키마는 이 provenance 를 그대로 승계해야 한다.

### 0.6 global_ib_named.json (뉴스 기반, Phase 14-4)

```
manual_entries   list
merged_entries   list  [{firm, target_price, currency, report_date, source_url, source_urls, source_name, source_count,
                          confidence, extraction_method, evidence_phrase, is_stale, analyst_ctx_score,
                          underwriter_ctx_score, proximity_chars}, ...]
n_merged         int
news_search      dict  {attempted_searches, entries, found, n_entries, probed_at}
probed_at        str
ticker           str
ticker_ko        str
```

### 0.7 global_ib_aggregate.json (yfinance)

```
breakdown_prior_1m {buy, hold, sell, strong_buy, strong_sell, total}
breakdown_today    (same)
currency           str
error              str|null
found              bool
n_analysts         int
per_firm           list  (yfinance 는 per_firm 을 대체로 [] 반환 — 스키마상 존재하지만 실측 empty)
probed_at          str
recommendation_key str  'strong_buy'
recommendation_mean float
source_name        str  'yfinance_aggregate'
target_high        float
target_low         float
target_mean        float
target_median      float
```

### 0.8 live_prices.json

```
generated_at  str
generator     str  'scripts/consensus_accuracy_daily.py'
prices        dict  {ticker: {close, currency, as_of, source, market, name}}
```

### 0.9 _accuracy_state.json

```
generated_at str
streaks      dict  {ticker: {count, last_diff_pct, last_stale_day}}
```

---

## (A) DDL — 스키마 (실행 금지, 문서용)

### A.1 핵심 결정: 3 계층 데이터 모델

관측된 fact 3 가지로부터 자연스레 도출됨:

1. **live 계층** — 매일 UPSERT (live_prices, _accuracy_state)
2. **snapshot 계층** — 하루에 한 번 작성 후 immutable (parsed.json, analysis.json, raw.html)
3. **frozen historical 계층** — history/ 아래 sha256 매니페스트로 잠긴 과거 스냅샷

Snapshot 계층은 **append-only + snapshot_id PK** 로 강제하고, live 계층은 별도 테이블에서 UPSERT 로 관리. Trigger 로 snapshot rows 의 UPDATE/DELETE 를 차단해 immutability 를 스키마 레벨에서 보장한다.

### A.2 DDL

```sql
-- =====================================================================
-- 1) 티커/식별자 사전
-- =====================================================================
CREATE TABLE tickers (
    ticker       TEXT PRIMARY KEY,                  -- '000660', 'NVDA', 'GOOGL', 'VRT'
    ticker_ko    TEXT,                              -- 'SK하이닉스' (한글, nullable for US)
    name_en      TEXT,                              -- 'SK hynix', 'NVIDIA'
    market       TEXT NOT NULL CHECK (market IN ('KR', 'US', 'JP', 'GLOBAL')),
    currency     TEXT NOT NULL CHECK (currency IN ('KRW', 'USD', 'JPY', 'EUR')),
    is_index     INTEGER NOT NULL DEFAULT 0 CHECK (is_index IN (0,1)),  -- 매크로 지표면 1
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- =====================================================================
-- 2) 지표/시리즈 사전 (매크로 29 + 종목 close 를 통합 관리)
-- =====================================================================
CREATE TABLE series (
    series_id     TEXT PRIMARY KEY,                 -- 'NASDAQ100', 'SP500', 'TICKER_CLOSE:000660'
    kind          TEXT NOT NULL CHECK (kind IN
                    ('macro_price','macro_calc','macro_alt','ticker_close')),
    source_label  TEXT,                             -- parquet 'source' 컬럼 원본 ('FDR:QQQ', 'FRED:WALCL', 'CALC:RSI14')
    unit          TEXT,                             -- 'USD', 'KRW', 'bps', 'ratio', 'index'
    frequency     TEXT CHECK (frequency IN ('daily','weekly','monthly','irregular')),
    ticker        TEXT,                             -- ticker_close 인 경우 tickers.ticker 참조
    notes         TEXT,
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);

-- =====================================================================
-- 3) 가격/지표 시계열 (single unified table — 근거는 (B).1)
-- =====================================================================
CREATE TABLE prices (
    series_id     TEXT NOT NULL,
    ts_date       TEXT NOT NULL,                    -- 'YYYY-MM-DD' 관측일
    value         REAL NOT NULL,
    source        TEXT,                             -- NULL 허용 (DXY/WTI/MARKET_STRENGTH/SEMICONDUCTOR_EXPORT 4종 실측 누락)
    fetched_at    TEXT NOT NULL,                    -- ISO8601 UTC — 언제 수집됐는가
    layer         TEXT NOT NULL DEFAULT 'live'
                    CHECK (layer IN ('live','snapshot','frozen')),
    PRIMARY KEY (series_id, ts_date),
    FOREIGN KEY (series_id) REFERENCES series(series_id)
);
CREATE INDEX idx_prices_date         ON prices(ts_date);
CREATE INDEX idx_prices_series_date  ON prices(series_id, ts_date DESC);

-- 소급 수정 대응: bitemporal history 는 별도 테이블 (근거 (B).2)
CREATE TABLE prices_history (
    series_id     TEXT NOT NULL,
    ts_date       TEXT NOT NULL,                    -- observation date
    recorded_at   TEXT NOT NULL,                    -- when this revision was stored (UTC ISO8601)
    value         REAL NOT NULL,
    source        TEXT,
    fetched_at    TEXT NOT NULL,
    superseded_by TEXT,                             -- NULL if still current; else FK to next recorded_at
    PRIMARY KEY (series_id, ts_date, recorded_at)
);
CREATE INDEX idx_prices_history_lookup ON prices_history(series_id, ts_date, recorded_at DESC);

-- =====================================================================
-- 4) 컨센서스 snapshot (하루에 한 번, immutable)
-- =====================================================================
CREATE TABLE consensus_snapshots (
    snapshot_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                 TEXT NOT NULL,
    snapshot_date          TEXT NOT NULL,           -- 'YYYY-MM-DD' (한국 KST 기준 wisereport 조회일)
    fetched_at             TEXT NOT NULL,           -- ISO8601 with TZ
    source                 TEXT NOT NULL,           -- 'wisereport'
    url                    TEXT NOT NULL,
    http_status            INTEGER NOT NULL,
    bytes                  INTEGER,
    encoding_detected      TEXT,
    schema_version         TEXT NOT NULL,           -- parsed.json 의 schema_version ('0.3')
    manifest_schema_ver    TEXT,                    -- history/manifest.json schema_version ('1.0')
    pipeline_git_head_sha  TEXT,                    -- 재현성 잠금 (manifest.json 에서 승계)
    raw_html_sha256        TEXT NOT NULL,           -- fetch.json.sha256 — 64 hex
    parsed_sha256          TEXT,                    -- history/.../manifest.json.files['parsed.json']
    analysis_sha256        TEXT,                    -- history/.../manifest.json.files['analysis.json']
    report_sha256          TEXT,                    -- history/.../manifest.json.files['report.md']
    top_sha256             TEXT,                    -- history/.../manifest.json.top_sha256 (Merkle)
    raw_html_path          TEXT,                    -- 원본 파일 위치 (검증 fallback)
    robots_allowed         INTEGER CHECK (robots_allowed IN (0,1)),
    robots_reason          TEXT,
    parser_warnings_json   TEXT,                    -- JSON1: 소수 warning list 그대로 저장
    UNIQUE (ticker, snapshot_date, source),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);
CREATE INDEX idx_snap_ticker_date ON consensus_snapshots(ticker, snapshot_date DESC);

-- 강제 immutability (trigger — 자세한 논의는 (B).3)
CREATE TRIGGER trg_consensus_snapshots_no_update
BEFORE UPDATE ON consensus_snapshots
BEGIN
    SELECT RAISE(ABORT, 'consensus_snapshots is append-only (immutable)');
END;
CREATE TRIGGER trg_consensus_snapshots_no_delete
BEFORE DELETE ON consensus_snapshots
BEGIN
    SELECT RAISE(ABORT, 'consensus_snapshots is append-only (immutable)');
END;

-- =====================================================================
-- 5) 컨센서스 정형 필드 (스칼라 값들만 정규화; 근거 (B).4)
-- =====================================================================
CREATE TABLE consensus_scalars (
    snapshot_id                   INTEGER PRIMARY KEY,
    company                       TEXT,
    n_analysts                    INTEGER,
    investment_opinion            REAL,
    latest_target_price           REAL,
    prior_target_price            REAL,
    target_price_change_1m_pct    REAL,
    target_price_change_label     TEXT,
    static_target_price           REAL,             -- WiseReport 현재 스냅샷 (권위 있는 current)
    static_eps                    REAL,
    static_per                    REAL,
    chart_latest_target_price     REAL,             -- chartData2 최신 (월별, lag 있음)
    chart_latest_target_date      TEXT,
    close_price_latest            REAL,             -- snapshot 시점의 monthly-lagged close (stale 가능)
    -- reconciliation 파생값 (parsed.json.reconciliation 그대로)
    recon_per_times_eps           REAL,
    recon_per_eps_close_diff_pct  REAL,             -- CLAUDE.md OL-7: |x| < 1% invariant
    recon_static_vs_chart_target_diff_pct REAL,
    -- data_quality (analysis.json)
    data_quality_score            REAL,
    data_quality_components_json  TEXT,             -- JSON1 (6 boolean flags — 자주 진화)
    -- authoritative_current_target: 별도 컬럼으로 선택 결과 저장 (OL-7 mandate 1)
    authoritative_target_price    REAL,             -- static/chart 중 어느 쪽이 채택됐는가
    authoritative_target_source   TEXT CHECK
        (authoritative_target_source IN ('static','chart','manual_override')),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 6) opinion_breakdown (today vs a_month_ago)
-- =====================================================================
CREATE TABLE consensus_opinion_breakdown (
    snapshot_id   INTEGER NOT NULL,
    window        TEXT NOT NULL CHECK (window IN ('today','a_month_ago','prior_1m','yfinance_today','yfinance_prior_1m')),
    strong_buy    INTEGER,
    buy           INTEGER,
    hold          INTEGER,
    sell          INTEGER,
    strong_sell   INTEGER,
    total         INTEGER,
    PRIMARY KEY (snapshot_id, window),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 7) per_firm_targets (WiseReport 국내 하우스 컨센서스)
-- =====================================================================
CREATE TABLE consensus_per_firm (
    snapshot_id        INTEGER NOT NULL,
    firm               TEXT NOT NULL,                -- '한투', '하나', 'LS', ...
    target_price       REAL,
    prior_target_price REAL,
    change_pct         REAL,
    rating             TEXT,
    prior_rating       TEXT,
    report_date        TEXT,                         -- 'YY/MM/DD' 원본 유지 (실측 포맷)
    PRIMARY KEY (snapshot_id, firm, COALESCE(report_date, '')),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);
CREATE INDEX idx_per_firm_snapshot ON consensus_per_firm(snapshot_id);

-- =====================================================================
-- 8) global_ib_named (Phase 14-4: 뉴스 regex 로 추출한 named IB targets)
-- =====================================================================
CREATE TABLE consensus_global_ib_named (
    snapshot_id           INTEGER NOT NULL,
    firm                  TEXT NOT NULL,             -- 'JPMorgan', 'Goldman Sachs', 'Morgan Stanley', 'CLSA', ...
    origin                TEXT NOT NULL CHECK (origin IN ('manual','news_regex','yfinance_per_firm')),
    target_price          REAL,
    currency              TEXT,
    report_date           TEXT,                      -- 'YYYY-MM-DD'
    is_stale              INTEGER CHECK (is_stale IN (0,1)),
    confidence            TEXT CHECK (confidence IN ('low','medium','high')),
    extraction_method     TEXT,                      -- 'news_regex', 'yfinance', 'manual'
    source_name           TEXT,                      -- 'hankyung_search', 'yfinance', ...
    source_url            TEXT,
    source_urls_json      TEXT,                      -- JSON1: multi-URL 지원
    source_count          INTEGER,
    evidence_phrase       TEXT,
    analyst_ctx_score     INTEGER,
    underwriter_ctx_score INTEGER,
    proximity_chars       INTEGER,
    PRIMARY KEY (snapshot_id, firm, origin, COALESCE(report_date, ''), COALESCE(source_url, '')),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);
CREATE INDEX idx_ib_named_snapshot_firm ON consensus_global_ib_named(snapshot_id, firm);

-- =====================================================================
-- 9) global_ib_aggregate (Phase 14-3: yfinance 집계 요약)
-- =====================================================================
CREATE TABLE consensus_global_ib_aggregate (
    snapshot_id        INTEGER PRIMARY KEY,
    source_name        TEXT,                         -- 'yfinance_aggregate'
    currency           TEXT,
    n_analysts         INTEGER,
    target_high        REAL,
    target_low         REAL,
    target_mean        REAL,
    target_median      REAL,
    recommendation_key TEXT,
    recommendation_mean REAL,
    probed_at          TEXT,
    found              INTEGER CHECK (found IN (0,1)),
    error              TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 10) 분기 실적 (quarterly_earnings.quarters)
-- =====================================================================
CREATE TABLE consensus_quarterly_earnings (
    snapshot_id             INTEGER NOT NULL,
    yymm                    TEXT NOT NULL,           -- '202509', '202512', '202603'
    announce_date           TEXT,                    -- '2025/10/29(잠정)' — 원본 유지
    revenue_actual          REAL,
    revenue_consensus       REAL,
    revenue_surprise_pct    REAL,
    revenue_qoq_pct         REAL,
    revenue_yoy_pct         REAL,
    op_income_actual        REAL,
    op_income_consensus     REAL,
    op_income_surprise_pct  REAL,
    op_income_qoq_pct       REAL,
    op_income_yoy_pct       REAL,
    PRIMARY KEY (snapshot_id, yymm),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 11) 연간 지표 (annual_indicators: FY 별 metric 매트릭스)
-- =====================================================================
-- fy_labels: ['2025/12(A)', '2026/12(E)']  metrics: {BPS, EPS, PBR, PCR, PER, EV/EBITDA, EBITDA, 배당수익률}
-- long format 으로 저장 (metric name 이 진화하므로 정규화 우선)
CREATE TABLE consensus_annual_indicators (
    snapshot_id  INTEGER NOT NULL,
    fy_label     TEXT NOT NULL,                       -- '2025/12(A)', '2026/12(E)'  (A=Actual, E=Estimate)
    metric       TEXT NOT NULL,                       -- 'BPS','EPS','PBR','PCR','PER','EV/EBITDA','EBITDA','배당수익률'
    value        REAL,
    PRIMARY KEY (snapshot_id, fy_label, metric),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 12) 시계열 series (target/close monthly from chartData2)
-- =====================================================================
-- 원본은 x_ms (unix ms) + y — snapshot 별로 monthly point 를 그대로 append
CREATE TABLE consensus_chart_series (
    snapshot_id  INTEGER NOT NULL,
    series_kind  TEXT NOT NULL CHECK (series_kind IN ('target','close')),
    ts_date      TEXT NOT NULL,                       -- x_ms 를 UTC date 로 변환한 YYYY-MM-DD
    x_ms         INTEGER NOT NULL,                    -- 원본 unix ms (재현용)
    y            REAL,
    PRIMARY KEY (snapshot_id, series_kind, ts_date),
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);
CREATE INDEX idx_chart_series_kind_date ON consensus_chart_series(series_kind, ts_date);

-- =====================================================================
-- 13) Q1-Q5 analyst answers (analysis.json.answers)
-- =====================================================================
CREATE TABLE consensus_analysis_answers (
    snapshot_id                  INTEGER PRIMARY KEY,
    q1_direction                 TEXT,                -- 'UP', 'DOWN', 'FLAT'
    q1_target_price_change_pct   REAL,
    q2_direction                 TEXT,
    q2_eps_change_pct            REAL,
    q3_direction                 TEXT,
    q3_op_income_change_pct      REAL,
    q4_quadrant                  TEXT,                -- 'TRUE_UPGRADE', 'FALSE_UPGRADE', ...
    q5_global_vs_domestic        TEXT,                -- 'ALIGNED_DIRECTION_AND_LEVEL', ...
    q5_details_json              TEXT,                -- JSON1: Q5_details 중첩 유연 저장
    raw_inputs_json              TEXT,                -- JSON1: raw_inputs 딕셔너리 (검증용)
    meta_audit_json              TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES consensus_snapshots(snapshot_id)
);

-- =====================================================================
-- 14) LIVE 계층: 라이브 가격 오버레이 (live_prices.json 대체)
-- =====================================================================
CREATE TABLE live_prices (
    ticker      TEXT PRIMARY KEY,
    close       REAL NOT NULL,
    currency    TEXT NOT NULL,
    as_of       TEXT NOT NULL,                        -- 'YYYY-MM-DD' 시장 close 기준일
    source      TEXT NOT NULL,                        -- 'FinanceDataReader', 'yfinance'
    market      TEXT NOT NULL,
    name        TEXT,
    updated_at  TEXT NOT NULL,                        -- generated_at 값 (매일 갱신)
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);
-- as_of 이 갱신된 이력을 유지하려면 prices_history 로 미러링 (선택; (B).6)

-- =====================================================================
-- 15) accuracy_state (스냅샷 stale 여부 추적)
-- =====================================================================
CREATE TABLE accuracy_streaks (
    ticker           TEXT PRIMARY KEY,
    streak_count     INTEGER NOT NULL DEFAULT 0,
    last_diff_pct    REAL,
    last_stale_day   TEXT,                            -- 'YYYY-MM-DD' or NULL
    updated_at       TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);

-- =====================================================================
-- 16) 파일 매니페스트 (frozen historical layer — 파일 시스템과 동기)
-- =====================================================================
-- history/<ticker>/<date>/manifest.json 을 SQLite 안에서 조회 가능하게 미러링
-- (파일이 계속 파일 시스템에 존재하므로 SQLite 는 인덱스 역할)
CREATE TABLE frozen_manifests (
    manifest_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                 TEXT NOT NULL,
    manifest_date          TEXT NOT NULL,             -- 'YYYY-MM-DD'
    manifest_schema_ver    TEXT NOT NULL,             -- '1.0'
    top_sha256             TEXT NOT NULL,             -- Merkle
    pipeline_git_head_sha  TEXT,
    written_at_utc         TEXT NOT NULL,
    manifest_path          TEXT NOT NULL,             -- 상대 경로 (예: 'output/consensus_snapshot/history/000660/2026-07-03/manifest.json')
    UNIQUE (ticker, manifest_date),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);

CREATE TABLE frozen_manifest_files (
    manifest_id  INTEGER NOT NULL,
    filename     TEXT NOT NULL,                       -- 'parsed.json', 'analysis.json', 'report.md'
    sha256       TEXT NOT NULL,
    PRIMARY KEY (manifest_id, filename),
    FOREIGN KEY (manifest_id) REFERENCES frozen_manifests(manifest_id)
);

CREATE TRIGGER trg_frozen_manifests_no_update
BEFORE UPDATE ON frozen_manifests
BEGIN
    SELECT RAISE(ABORT, 'frozen_manifests is append-only');
END;
CREATE TRIGGER trg_frozen_manifests_no_delete
BEFORE DELETE ON frozen_manifests
BEGIN
    SELECT RAISE(ABORT, 'frozen_manifests is append-only');
END;

-- =====================================================================
-- 17) 스키마 버전 관리
-- =====================================================================
CREATE TABLE schema_migrations (
    version       INTEGER PRIMARY KEY,                -- 1, 2, 3, ...
    applied_at    TEXT NOT NULL,
    description   TEXT NOT NULL,
    checksum      TEXT                                -- 마이그레이션 SQL 파일 sha256
);
```

### A.3 재현/조회를 돕는 View 예시 (참고, 코드는 아님)

```sql
-- 오늘 각 티커의 authoritative target vs live close
CREATE VIEW v_ticker_gap_today AS
SELECT
    s.ticker,
    lp.as_of         AS live_close_date,
    lp.close         AS live_close,
    lp.currency      AS live_currency,
    cs.snapshot_date AS latest_snapshot_date,
    cs2.authoritative_target_price,
    cs2.authoritative_target_source,
    (cs2.authoritative_target_price - lp.close) / NULLIF(lp.close, 0) * 100.0 AS upside_pct
FROM tickers s
LEFT JOIN live_prices lp ON lp.ticker = s.ticker
LEFT JOIN (
    SELECT ticker, MAX(snapshot_date) AS max_date FROM consensus_snapshots GROUP BY ticker
) latest ON latest.ticker = s.ticker
LEFT JOIN consensus_snapshots cs ON cs.ticker = latest.ticker AND cs.snapshot_date = latest.max_date
LEFT JOIN consensus_scalars cs2 ON cs2.snapshot_id = cs.snapshot_id
WHERE s.is_index = 0;
```

---

## (B) 설계 결정 근거

### (B).1 가격/지표 시계열: single `prices` 테이블로 통합

- **결정**: 매크로 29 + 종목 close 를 `prices` 하나로 합치되, `series_id` 를 discriminator 로 사용.
- **근거 (fact)**: 실측 결과 모든 parquet 이 `(date, value, source?)` 로 완전 동일한 shape. 저장 관점에서 물리적으로 다른 테이블일 이유가 없다.
- **근거 (query)**: "SP500 vs 지표 X 상관성" 계산 시 join key 가 `(series_id, ts_date)` 로 균일 → 쿼리가 단순.
- **트레이드오프**: series_id 값 세트가 커지면 index cardinality 가 커진다. 그러나 30 종 미만 (매크로 29 + 티커 종가 4~수십) 이라 무시 가능.
- **대안**: `macro_prices` 와 `ticker_prices` 분리. 장점은 semantic 분리·매크로 데이터에 `source NULL` 허용을 없앨 수 있음 (분리 시 ticker_prices 는 source NOT NULL 가능). 단점은 지표-지표, 지표-종목 상관 쿼리가 `UNION` 필요 → 채택 안 함.

### (B).2 point-in-time query: bitemporal (`ts_date` + `recorded_at`)

- **결정**: 대부분 쿼리는 `prices` (single-axis) 로 처리. 소급 수정 이력이 필요할 때만 `prices_history` 로 이중 시간축 관리.
- **근거**: Ljungqvist 2009 I/B/E/S 사례 — 애널리스트 컨센서스는 사후 수정 리스크 존재. 우리 데이터에서도 FDR 이 종종 과거 값을 revise (예: 배당 재조정). single-table 로만 두면 lookahead bias 를 못 잡는다.
- **구현 룰**:
  - `prices` UPSERT 시, 기존 row 와 value 가 다르면 옛 row 를 `prices_history` 로 이동한 뒤 갱신.
  - 매크로 지표는 대부분 revise-in-place 이므로 실제 트래픽은 낮음.
- **컨센서스는 다르게 처리**: consensus 는 이미 snapshot 개념 (하루 = 하나의 immutable row) → bitemporal 필요 없음.

### (B).3 Immutability: append-only + trigger + sha256

- **결정**: consensus_snapshots / frozen_manifests 에 `BEFORE UPDATE`, `BEFORE DELETE` trigger 로 RAISE(ABORT).
- **근거**: Phase 14-0-C 정책은 write-once. 파일 시스템 sha256 매니페스트를 이미 갖고 있으므로, SQLite 도 동일 계약을 지켜야 한다. Trigger 는 애플리케이션 실수 방지에 효과적 (Postgres 의 `RULE` 이나 view-only pattern 대체).
- **대안 1**: SQLite `PRAGMA query_only = ON` — 세션 레벨이라 강제성 약함. 채택 안 함.
- **대안 2**: 별도 `_history` 테이블만 두고 원본은 자유롭게 변경. 그러면 immutable 계약이 문서 레벨에만 존재 → 불충분.
- **주의**: 스키마 마이그레이션 시 `DROP TRIGGER` → migrate → recreate 순서 필요. 마이그레이션 도구가 이를 인지해야 함.

### (B).4 정규화 vs JSON blob 트레이드오프

우리 데이터 3 카테고리로 분류:

| 필드 종류 | 예 | 방식 | 이유 |
|---|---|---|---|
| 스칼라 (안정) | n_analysts, target_price, PER, EPS | 정규화 컬럼 | 인덱스·집계·산술 invariant 검사 (`PER × EPS ~= close`) 필요 |
| 반복 리스트 (안정 shape) | per_firm_targets, quarterly_earnings, chart series | 별도 테이블 (long format) | row 개수 유동, PK 로 유일성 강제, snapshot 간 diff 쿼리 자연스러움 |
| 진화하는 딕셔너리 | data_quality.components, Q5_details, raw_inputs, meta_audit, parser_warnings | JSON1 컬럼 (`*_json TEXT`) | 필드 세트가 스키마 버전 사이에서 계속 변한다 (parsed.json schema_version 0.3, manifest 1.0 이미 다름). 매번 ALTER TABLE 비용 크다 |

- **근거 (실측)**: `data_quality.components` 는 6 개 boolean, 새 QC 추가되면 필드 늘어남. `Q5_details.implied` 딕셔너리는 이미 5 개 서브필드 (yfinance_mean 등) + `per_firm_jpm_gs_available` 같은 신규 플래그. 정규화하면 nullable 컬럼 폭발.
- **SQLite JSON1**: `json_extract(components_json, '$.estimates_present')` 로 인덱스 가능 (generated column + index) → 필요 시 pull-out 가능.
- **비대칭 룰**: `authoritative_target_price` 같은 CLAUDE.md OL-7 mandate 필드는 반드시 정규화 컬럼 (invariant 검사 대상).

### (B).5 NULL 정책

- `prices.source` NULL 허용 — 실측 4 종 (DXY / MARKET_STRENGTH / WTI / SEMICONDUCTOR_EXPORT) 이 이미 파일에 source 컬럼 없음. `series` 테이블의 `source_label` 로 우회 (series 레벨은 항상 채운다).
- `consensus_scalars` 의 static/chart 대다수 컬럼 NULL 허용 — 파서 실패 (예: SEMICONDUCTOR_EXPORT 처럼 `_FAILED.txt` 케이스) 시 부분 저장.
- `authoritative_target_price` 는 NULL 허용하되, 애플리케이션 로직에서 snapshot commit 시 반드시 선택된 값이 있도록 강제. NULL 로 남으면 후속 pm-agent 판단 불가 (CLAUDE.md OL-7 mandate 1 위반).

### (B).6 UPSERT vs live 계층 미러링

- `live_prices` 는 매일 오버라이트. 히스토리 필요 시:
  - **옵션 A**: 단순 UPSERT (히스토리 손실 — 오늘 close 만 남음).
  - **옵션 B**: UPSERT + BEFORE UPDATE trigger 로 옛 row 를 `prices` 테이블 (layer='live') 로 mirror. 이 경우 (series_id='TICKER_CLOSE:000660', ts_date=as_of, value=close) 로 append.
- **권장 (B)**: 종목 close 를 매크로 시계열과 같은 방식으로 저장하면 대시보드/분석에서 동일 API 로 접근 가능. `live_prices` 는 "가장 최근 값" 캐시 역할만.

### (B).7 UTC vs KST 시간대

- `fetched_at`, `probed_at`, `written_at_utc`, `generated_at` — 원본이 섞여 있음.
  - fetch.json: `+09:00` (KST)
  - manifest.json: `written_at_utc` (UTC)
  - live_prices.json: `+09:00`
- **결정**: SQLite 저장은 항상 UTC ISO8601 (`YYYY-MM-DDTHH:MM:SSZ`) 로 정규화. 원본 timezone 정보가 필요하면 별도 컬럼에 문자열 보존. `snapshot_date`, `as_of`, `ts_date` 는 date-only 라 시간대 무관하지만 "KST 자정 기준" 이라는 규약을 스키마 주석에 명시.

### (B).8 인덱스 전략

- **범위 스캔 (시계열)**: `idx_prices_series_date(series_id, ts_date DESC)` — "최근 N일" 쿼리 최적화.
- **날짜 크로스섹션**: `idx_prices_date(ts_date)` — "특정 날짜 모든 지표" 쿼리.
- **snapshot lookup**: `idx_snap_ticker_date(ticker, snapshot_date DESC)` — "티커의 최신 snapshot" 쿼리 매우 흔함.
- **firm lookup**: `idx_per_firm_snapshot`, `idx_ib_named_snapshot_firm` — "특정 하우스의 시계열 target" 조회.
- **불필요한 인덱스는 만들지 않는다**: SQLite 는 write amplification 있음. 매일 UPSERT 는 write-heavy.

### (B).9 UNIQUE constraint 위치

- `prices` : PK `(series_id, ts_date)` — 관측일 유일.
- `consensus_snapshots` : PK 는 auto-increment `snapshot_id`, 그리고 `UNIQUE(ticker, snapshot_date, source)` — 같은 날 재실행 방지.
- `frozen_manifests` : `UNIQUE(ticker, manifest_date)` — history 폴더 규칙과 일치.
- `consensus_per_firm` : PK `(snapshot_id, firm, COALESCE(report_date, ''))` — 같은 하우스가 같은 리포트 날짜에 두 target 못 냄.
- `consensus_global_ib_named` : PK 에 `source_url` 포함 — 같은 firm 이 여러 뉴스 소스에서 다른 target 로 등장 가능 (실측 데이터 확인).

### (B).10 CHECK constraint

- `market IN ('KR','US','JP','GLOBAL')`, `currency IN ('KRW','USD','JPY','EUR')` — 명시적 whitelist.
- `layer IN ('live','snapshot','frozen')` — 3-tier 원칙 강제.
- `authoritative_target_source IN ('static','chart','manual_override')` — OL-7 mandate 1 (반드시 명시).
- `origin IN ('manual','news_regex','yfinance_per_firm')` — extraction 경로 tracking.

---

## (C) 마이그레이션 전략

### C.1 이관 순서 (파일 → SQLite)

1. **선행**: `tickers`, `series`, `schema_migrations` seed.
2. **매크로 parquet**: 파일 29 개를 순회, 각 row → `prices(series_id=<indicator>, ts_date=date, value, source, layer='live')`. NOT NULL 위반 없음 (실측). source 4 종 NULL 허용.
3. **live_prices.json → live_prices** 테이블 + `prices(series_id='TICKER_CLOSE:<ticker>', ..., layer='live')` 미러.
4. **_accuracy_state.json → accuracy_streaks**.
5. **history/<ticker>/<date>/manifest.json → frozen_manifests + frozen_manifest_files**. sha256 그대로 승계. 파일 경로도 저장 (파일 원본은 남겨둠 = 이중 백업).
6. **output/consensus_snapshot/<TICKER>_<DATE>_parsed.json + analysis.json + fetch.json → consensus_snapshots + consensus_scalars + consensus_opinion_breakdown + per_firm + global_ib_named + quarterly_earnings + annual_indicators + chart_series + analysis_answers**. 트랜잭션 단위: 스냅샷 1 개 = 1 트랜잭션.
7. **검증**: 이관 후 각 스냅샷의 raw_html_sha256 을 `output/consensus_snapshot/<TICKER>_<DATE>_raw.html` 실제 파일에서 재계산해서 일치 확인.

### C.2 sha256 매니페스트 유지

- `frozen_manifests` 는 파일 시스템 매니페스트의 **인덱스**. Source-of-truth 는 여전히 파일. SQLite 값이 오염돼도 파일에서 재구성 가능 → 이중 방어.
- 검증 스크립트 (제안): `scripts/audit_frozen_integrity.py` — DB row 를 순회하며 파일 재해싱, mismatch 발견 시 FAIL.

### C.3 동시성 & WAL

- **가정**: pipeline 은 순차 실행 (`pm_orchestrator.py` 가 stage 를 직렬로 진행). 그러나 대시보드 정적 export 스크립트가 read-only 로 동시 접근할 수 있음.
- **권장**: `PRAGMA journal_mode = WAL;` — 다중 reader + single writer 안전. 쓰기 완료 후 checkpoint.
- **write lock**: SQLite 는 db-level lock. 파이프라인 write 창구를 하나로 유지 (예: `db_writer.py` singleton). Agent 들은 write 요청을 이 모듈 통해서만.
- **timeout**: `PRAGMA busy_timeout = 5000;` — reader 가 checkpoint 대기 시 최대 5s.

### C.4 롤백 전략

- SQLite 파일 물리 백업: **매일 pipeline 실행 전** `data/db/analyzer.sqlite` → `data/db/backup/analyzer_YYYYMMDD.sqlite` (SQLite `.backup` 명령 또는 파일 복사; WAL 상태 반영 위해 `VACUUM INTO` 권장).
- 롤백 = 파일 복원. 파일 시스템 snapshot 은 그대로 남아 있으므로 재이관 가능 (C.1 재실행).
- 보존: 최근 30 일 + 매월 1일자 무기한 (원한다면).

---

## (D) 대안 — SQLite 도입이 오버킬인가?

| 옵션 | 장점 | 단점 | 언제 채택 |
|---|---|---|---|
| **D1. 현행 파일 유지** | 코드 변경 0, 매니페스트 sha256 이미 존재, `.parquet` 은 컬럼 저장으로 시계열 스캔 최적 | ticker × date point-lookup 이 느림 (매 조회마다 파일 open), cross-ticker join 은 애플리케이션에서 `pandas.merge`, 스키마 진화 관리 어려움 | 파이프라인이 매일 1회 배치만 돌리고 실시간 조회 요구가 없을 때 |
| **D2. `data/index.parquet` 만 추가** | 최소 변경. `(ticker, snapshot_date) → file_path` mapping 만 캐시. `pd.read_parquet(idx).query(...)` 로 파일 찾기 | join·집계는 여전히 파일 read 후 pandas, immutability enforcement 없음 | 파일이 100 개 미만이고 파일명 규칙만으로 충분할 때. 현재 규모 (스냅샷 4 티커 × 며칠) 는 여기에 해당 가능 |
| **D3. 부분 SQLite (종목 가격만)** | live_prices UPSERT 만 SQLite 로. 나머지는 파일 그대로 | 두 저장소를 함께 관리 (심리적 부담). 대시보드는 두 소스 접근 필요 | live 계층만 UPSERT 부담이 크고 나머지는 immutable 이라 파일이 안전할 때. **본 프로젝트에 가장 실용적일 가능성 큼** |
| **D4. 전체 SQLite (본 문서 A 안)** | 통합 쿼리, invariant 검사, immutability trigger, view, join, 스키마 버전 관리 일원화 | 이관 비용, WAL 설정, 마이그레이션 도구 필요, sha256 이중 관리 | 여러 팀·여러 tool 이 같은 데이터를 쿼리하고 대시보드가 무거워질 때 |
| **D5. DuckDB** | parquet 을 그대로 쿼리 (zero-copy), SQL 문법 동일, 시계열 집계 매우 빠름 | write-once/immutable 강제 트리거 약함, single-writer 가정 필요, Windows 지원은 OK | 분석 workload 가 대부분 read-heavy 이고 데이터를 옮기고 싶지 않을 때. `SELECT ... FROM 'data/raw/*.parquet'` 그대로 |

**권장 판단** (사용자 결정 대상):
- 만약 매일 배치 실행 + 대시보드 정적 export 만이 요구사항이라면 → **D3 (부분 SQLite)** + parquet 그대로 유지.
- 여러 agent 가 동시에 read/write 하고 invariant enforcement 가 중요하다면 → **D4 (전체 SQLite, A안)**.
- 분석 우선 (LLM judge / evaluator 가 raw parquet 을 자주 join) 이라면 → **D5 (DuckDB)** 도 매우 매력적.

---

## (E) 개방 질문 (사용자 결정 필요)

1. **동시 접근 모델**: 파이프라인이 `pm_orchestrator.py` 단일 프로세스로만 write 하나? 아니면 GitHub Actions 병렬 job 에서도 쓸 수 있나?
   - Single writer → SQLite + WAL 로 충분.
   - Multi writer → SQLite 는 부적합. Postgres/DuckDB motherduck 고려.

2. **히스토리 보존 기간**: `prices_history` 를 무기한 유지? 아니면 90 일 지나면 archive?
   - 무기한 → DB 크기 증가하지만 소급 수정 감사 가능.
   - 90 일 → 최근 리비전만 유지. 아카이브 규칙 필요.

3. **쿼리 워크로드 프로필**: 대시보드/analyst agent 는 주로 (a) 최근 N일 시계열 range scan, (b) 특정 (ticker, date) point lookup, (c) cross-ticker aggregate 중 어느 쪽이 dominant?
   - (a) dominant → 현재 index 전략 OK, DuckDB 도 매력.
   - (b) dominant → SQLite point lookup 이 parquet 대비 훨씬 빠름 → SQLite 채택 우세.
   - (c) dominant → snapshot 별 pre-aggregated view 필요.

4. **대시보드 배포 경로**: 대시보드는 SQLite 를 **직접** 읽나 (예: `sql.js` 로 브라우저에서 open), 아니면 SQLite → JSON export 후 정적 배포 (현행 `output/*.json`)?
   - 직접 → DB 파일이 배포 artifact 에 포함 (수십 MB 가능).
   - JSON export → SQLite 는 서버측 SoT, 배포는 그대로 정적 JSON. **현재 파이프라인 흐름과 가장 잘 맞음.**

5. **스키마 진화 정책**: parsed.json `schema_version` (0.3), manifest `schema_version` (1.0), SQLite `schema_migrations.version` — 이 세 축을 어떻게 동기?
   - 룰 후보: SQLite migration N 은 parsed.json 최소 schema_version 을 명시. 그 미만 파일은 이관 대상에서 제외 (아니면 upgrade 스크립트).
   - `consensus_snapshots.schema_version` 컬럼으로 원본 버전 그대로 보존 → 사후 재해석 가능.

6. **JSON blob 필드 선택**: `data_quality_components_json`, `Q5_details_json`, `raw_inputs_json`, `meta_audit_json`, `parser_warnings_json`, `source_urls_json` — 이 6 개면 충분한가? 아니면 더 많이 blob 화 (예: `estimates_json`) 해야 하나?
   - 실측 estimates 필드는 FY 라벨이 매년 바뀜 (`2025/12(A)`, `2026/12(E)` 등) → **estimates 도 blob 후보**. 그러나 산술 invariant (PER × EPS) 계산 위해 정규화가 낫다는 경합.

7. **파일 시스템 원본을 유지할지**: history/ 아래 `parsed.json`, `analysis.json`, `raw.html` 을 SQLite 로 이관 후에도 파일로 남길 것인가?
   - 이중 저장 → 안전하지만 저장소 크기 2배.
   - 파일 삭제 (DB only) → 재현성/디버깅 어려움. `raw.html` 은 무조건 파일로 남기는 것 권장 (encoding 문제·향후 파서 개선 시 재파싱 필요).

---

## 요약

- 3-tier layer (live / snapshot / frozen) + `series_id` 로 매크로·종목 통합.
- Immutability 는 append-only + trigger + sha256 이중 방어.
- 반복 리스트는 long format 정규화, 진화하는 dict 는 JSON1 blob.
- Point-in-time 은 대부분 snapshot으로 처리, 매크로 revise 는 별도 `prices_history` bitemporal.
- SQLite 도입 자체가 오버킬일 수 있으므로 D1~D5 대안을 함께 병기 — 사용자가 워크로드 프로필을 답한 뒤 최종 결정.
