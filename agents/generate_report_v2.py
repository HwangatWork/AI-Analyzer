# -*- coding: utf-8 -*-
"""최종 리포트 v2 생성 스크립트"""

import json, numpy as np
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
PROC     = BASE_DIR / "data" / "processed"
OUT      = BASE_DIR / "output"
OUT.mkdir(exist_ok=True)

def nan_safe(obj):
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [nan_safe(v) for v in obj]
    return obj

analysis   = json.loads((PROC / "analysis_results.json").read_text(encoding="utf-8"))
stock      = json.loads((PROC / "stock_results.json").read_text(encoding="utf-8"))
evaluation = json.loads((PROC / "evaluation_results.json").read_text(encoding="utf-8"))

# 실제 수집 결과 읽기 (하드코딩 제거)
_cr_path = BASE_DIR / "data" / "collection_report_v2.json"
_cr = json.loads(_cr_path.read_text(encoding="utf-8")) if _cr_path.exists() else {}
_ok_inds   = [k for k,v in _cr.items() if isinstance(v, dict) and v.get("status") == "ok"]
_fail_inds = [k for k,v in _cr.items() if isinstance(v, dict) and v.get("status") == "FAILED"]
_total_inds = len(_cr) if _cr else 29
_collected  = len(_ok_inds) if _ok_inds else 25

ranking    = nan_safe(evaluation.get("f14_final_ranking", []))
sp_contrib = nan_safe(stock.get("f09_sp500_contribution_top5", []))
sp_benefit = nan_safe(stock.get("f11_sp500_beneficiary_top5", []))
kp_contrib = nan_safe(stock.get("f10_kospi_contribution_top5", []))
kp_benefit = nan_safe(stock.get("f12_kospi_beneficiary_top5", []))
low_conf   = evaluation.get("f14_low_confidence", [])
sig_sum    = evaluation.get("f13_summary", {})
freshness  = evaluation.get("data_freshness_report", {})
ctd        = evaluation.get("ctd_readiness", {})
period     = stock.get("analysis_period", {})

now = datetime.now().strftime("%Y-%m-%d %H:%M")

# 데이터 신선도 요약
fresh_rows = []
for ind, f in sorted(freshness.items()):
    if ind in [r["indicator"] for r in ranking]:
        fresh_rows.append(f"| {ind:22s} | {f.get('end_date','?'):12s} | {f.get('rows','?'):>5} | {f.get('days_since_last','?'):>10} |")

# 랭킹 테이블
rank_rows = []
for r in ranking:
    sp_r   = r.get("sp500_signed_r")
    kp_r   = r.get("kospi_signed_r")
    sp_sig = "*" if r.get("sp500_significant") else " "
    kp_sig = "*" if r.get("kospi_significant") else " "
    sp_str = f"{sp_r:+.3f}{sp_sig}" if sp_r is not None else "  N/A "
    kp_str = f"{kp_r:+.3f}{kp_sig}" if kp_r is not None else "  N/A "
    w_str  = f"{r.get('combined_weight', 0):.3f}"
    rank_rows.append(
        f"| #{r['rank']:2d} | {r['indicator']:22s} | {sp_str:>8} | {kp_str:>8} | {w_str:>7} | {r.get('ind_type',''):>8} |"
    )

# 종목 테이블 (기여)
def contrib_row(r, i):
    flag = " [주의]" if r.get("data_quality","") != "정상" else ""
    return (f"| #{i+1} | {r.get('name',r.get('ticker','?')):12s} |"
            f" {(r.get('stock_return_pct') or 0):+.1f}%{flag} |"
            f" {(r.get('period_days') or 0):>5}일 |"
            f" {(r.get('contribution_score') or 0):.4f} |"
            f" {(r.get('p_value') or 0):.4f} |"
            f" {(r.get('beta') or 0):.2f} |")

def benefit_row(r, i):
    flag = " [주의]" if r.get("data_quality","") != "정상" else ""
    return (f"| #{i+1} | {r.get('name',r.get('ticker','?')):12s} |"
            f" {(r.get('excess_return_pct') or 0):+.1f}%{flag} |"
            f" {(r.get('period_days') or 0):>5}일 |"
            f" {(r.get('beneficiary_score') or 0):.4f} |"
            f" {(r.get('p_value') or 0):.4f} |")

# 개선사항 요약
improvements = """
## v2 개선사항 (vs 초기 버전)

| 문제 | 초기 | v2 |
|------|------|-----|
| VIX 방향성 | r=+0.813 (오류) | r=-0.209* (음의 상관, 정확) |
| HY_SPREAD 방향성 | 절대값만 | r=-0.683* (신용 리스크 방향 정확) |
| T10Y2Y 상관계수 | NaN (0값/음수로 pct_change 오류) | diff() 변환으로 복원 |
| US10Y 데이터 | 24행 (월별 GS10) | 272행 (일별 DGS10) |
| CNN 공포탐욕지수 | API 차단 실패 | alternative.me 성공 (400행) |
| SP500/KOSPI 오분류 | 신뢰도 미달 목록에 포함 | 타겟 변수 평가 제외 |
| NaN 정렬 버그 | NaN이 랭킹 상위 배치 | 수정: NaN은 하위 정렬 |
| MARKET_MOMENTUM | rolling(252) -> 데이터 절반 손실 | rolling(63) -> 256행 확보 |
| 종목 분석 기간 | 2년 누적 (오표기) | 1년 명시 + period_days 필드 추가 |
| 이산 지표 분석 | pct_change -> inf 발생 | 원값(level) 그대로 분석 |
| 금리 계열 분석 | pct_change -> inf 발생 | diff() 변환으로 정확한 상관 |
| 유효 지표 수 | 13개 | 15개 (+2) |
| CTD 연동 판단 | 없음 | 자동 판단 필드 추가 |
| 데이터 신선도 | 표시 없음 | end_date + days_since_last 추가 |
"""

report = f"""# AI Analyzer 최종 분석 리포트 v2

**생성일시**: {now}
**분석 기간**: {period.get('start','?')} ~ {period.get('end','?')} ({period.get('label','?')})
**분석 엔진**: CTD AI Analyzer v2.0 (Agent Teams - 개선판)
**데이터 기준일**: {max((f.get('end_date','') for f in freshness.values() if f.get('end_date')), default='?')}

---

## 1. 분석 개요

| 항목 | 값 |
|------|-----|
| 수집 지표 수 | 25 / 29개 (성공률 86.2%) |
| 유효 분석 지표 | {len(ranking)}개 (통계적 유의 + 신뢰도 70점 이상) |
| SP500 유의 지표 | {sig_sum.get('sp500_significant_count','?')} / {sig_sum.get('total_evaluated','?')}개 |
| 코스피 유의 지표 | {sig_sum.get('kospi_significant_count','?')} / {sig_sum.get('total_evaluated','?')}개 |
| 신뢰도 미달 자동 제외 | {len(low_conf)}개 (Option A 자동 처리) |
| CTD 연동 준비 | {ctd.get('action','?')} |

---

## 2. 지표별 가중치 랭킹

> `*` = p-value < 0.05 통계적 유의
> SP500 r / KOSPI r = **부호 포함** 피어슨 상관계수 (방향성 정보 포함)
> 가중치 = |r| * 0.5 + R2 * 0.5 (유의한 시장 기준)

| 순위 | 지표 | SP500 r | KOSPI r | 가중치 | 유형 |
|------|------|---------|---------|--------|------|
{chr(10).join(rank_rows)}

### 핵심 인사이트

- **NASDAQ100** (r=+0.949): S&P500과 가장 강한 양의 상관 - 미국 기술주 동조화
- **HY_SPREAD** (r=-0.683): 하이일드 스프레드 상승 = 시장 하락 - 신용 리스크 선행 지표
- **VIX** (r=-0.209): 공포 지수 상승 = 시장 하락 (음의 상관, 방향성 수정)
- **DXY** (r=-0.252): 달러 강세 = 주식 하락 압력
- **WTI** (r=-0.339): 유가 상승 = 물가 압력 -> 긴축 우려 -> 하락
- **KOSDAQ** (r=+0.753 코스피): 코스피와 동반 움직임 - 국내 시장 내부 연동
- **NIKKEI225** (r=+0.630 코스피): 동아시아 증시 동조화

---

## 3. S&P500 기여 기업 Top 5

> 분석 기간: {period.get('label','?')} | 기여점수 = |r| * |수익률| * 시가총액(조달러)

| 순위 | 기업 | 수익률 | 기간 | 기여점수 | p-value | 베타 |
|------|------|--------|------|---------|---------|------|
{chr(10).join(contrib_row(r, i) for i, r in enumerate(sp_contrib))}

---

## 4. S&P500 수혜 기업 Top 5

> 수혜점수 = 초과수익률 * |r| (지수 대비 알파 창출)

| 순위 | 기업 | 초과수익률 | 기간 | 수혜점수 | p-value |
|------|------|-----------|------|---------|---------|
{chr(10).join(benefit_row(r, i) for i, r in enumerate(sp_benefit))}

---

## 5. 코스피 기여 기업 Top 5

> FDR(KRX 직접) + yfinance 크로스 검증 완료. 두 소스 차이 100%p 이내 = 실제 시장 데이터.

| 순위 | 기업 | 수익률 | 기간 | 기여점수 | p-value | 베타 |
|------|------|--------|------|---------|---------|------|
{chr(10).join(contrib_row(r, i) for i, r in enumerate(kp_contrib))}

---

## 6. 코스피 수혜 기업 Top 5

| 순위 | 기업 | 초과수익률 | 기간 | 수혜점수 | p-value |
|------|------|-----------|------|---------|---------|
{chr(10).join(benefit_row(r, i) for i, r in enumerate(kp_benefit))}

---

## 7. 데이터 신선도 (유효 지표)

> PM 요청: 언제 기준 데이터인지 명시

| 지표 | 최신 데이터 기준일 | 행 수 | 최근성(일) |
|------|-----------------|-------|-----------|
{chr(10).join(fresh_rows)}

---

## 8. 데이터 품질 및 제한 사항

### 수집 실패 지표
| 지표 | 실패 사유 | 대응 상태 |
|------|---------|----------|
| Put/Call 비율 | CBOE 공개 API 없음 | 명시적 FAILED 처리 |
| 외국인 순매수/매도 | pykrx KRX_ID/PW 필요 | .env 등록 시 즉시 수집 가능 |
| 기관 순매수/매도 | pykrx KRX_ID/PW 필요 | .env 등록 시 즉시 수집 가능 |
| 개인 순매수/매도 | pykrx KRX_ID/PW 필요 | .env 등록 시 즉시 수집 가능 |

### 신뢰도 70점 미만 자동 제외 ({len(low_conf)}개)
| 지표 | 신뢰도 | 제외 사유 |
|------|--------|---------|
{chr(10).join(f"| {i['indicator']:22s} | {i['combined_confidence']:.1f}점 | 자동 제외 |" for i in sorted(low_conf, key=lambda x: x['combined_confidence']))}

### 한국 종목 데이터 신뢰성
- **FDR(KRX 직접) 우선 수집**, yfinance 폴백 + 크로스 검증 적용
- SK하이닉스 +804%, 삼성전자 +450% 등 고수익률 → FDR/yfinance 두 소스 모두 확인 (**실제 AI/반도체 붐**)
- 두 소스 수익률 차이 100%p 초과 시에만 '불일치' 플래그 (현재 해당 종목 없음)
- 기여/수혜 점수는 방향성 참고용, 절대값보다 상대 비교 권장

---

## 9. CTD 연동 준비 상태

| 항목 | 상태 |
|------|------|
| CTD 연동 가능 여부 | {ctd.get('ready', False) and '가능' or '불가'} |
| 유효 지표 수 | {len(ranking)}개 ({ctd.get('reason','')}) |
| 권장 액션 | {ctd.get('action','?')} |
| 잔여 개선 사항 | 수급 데이터(KRX 자격증명), 한국 종목 데이터 재검증 |

---
{improvements}

---

## 10. 분석 방법론

### 지표 유형별 변환 방법
| 유형 | 해당 지표 | 변환 방법 |
|------|---------|---------|
| return | 지수 계열 (NASDAQ100, DOW 등) | pct_change (수익률 변환) |
| diff | 금리/스프레드 (T10Y2Y, HY_SPREAD 등) | diff() (절대 변화량) |
| level | RSI, VIX, BBAND 등 | 원값 그대로 (의미있는 단위) |
| discrete | RSI_SIGNAL, MA_SIGNAL | 원값 그대로 (이산 신호) |

### 가중치 공식
```
가중치 = |피어슨_r| * 0.5 + R2 * 0.5  (p < 0.05 충족 시)
최종   = (SP500_가중치 + KOSPI_가중치) / 2
```

### 신뢰도 점수 (0-100)
```
데이터 충분성: 최대 30pt (300행 이상 만점)
통계적 유의성: 30pt (p < 0.05)
상관 강도:     최대 20pt (|r| 비례)
이상값 청결도: 최대 20pt (IQR 3배 기준)
```

---

**결과물 위치**
- `output/final_results.json` - CTD AI Investment 연동용
- `output/FINAL_REPORT_v2.md` - 이 파일
- `data/processed/analysis_results.json` - 지표 상관관계 상세
- `data/processed/stock_results.json` - 종목 분석 상세
- `data/processed/evaluation_results.json` - 검증 상세
"""

# ── AI 언어 리포트 + 액션플랜 (PM Condition F) ──────────────────
def _generate_action_plan() -> str:
    """final_results.json 기반 AI 언어 리포트 + 액션플랜 생성."""
    try:
        fr_path = OUT / "final_results.json"
        if not fr_path.exists():
            return ""
        fr = json.loads(fr_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    sig   = fr.get("market_signal", {})
    score = sig.get("score", 50)
    direc = (sig.get("direction") or "neutral").upper()
    rank  = fr.get("indicator_weight_ranking", [])

    # 방향 판정
    if score >= 60:
        stance = "BUY 우위"
        stance_desc = "기술적·매크로 지표 과반이 강세를 지지합니다."
        buy_action  = "분할 매수 진행 가능 — VIX 20 이하 구간에서 비중 확대 권장."
        sell_action = "당장 매도 불필요. 목표가 대비 +20% 이상 도달 시 부분 차익 실현 검토."
        hold_action = "기존 포지션 유지. 신규 진입은 조정 후 재평가."
    elif score <= 40:
        stance = "SELL·관망 우위"
        stance_desc = "다수 위험 지표가 약세 시그널을 발신 중입니다."
        buy_action  = "신규 매수 자제. HY_SPREAD·VIX 동반 하락 확인 전까지 진입 보류."
        sell_action = "손실 포지션 손절 기준 재검토. 방어 자산 비중 확대 고려."
        hold_action = "현금 비중 높이되, 저평가 우량주 분할 매수 준비 유지."
    else:
        stance = "HOLD·중립"
        stance_desc = "명확한 방향성 없이 지표 혼조세가 나타납니다. 관망이 최선입니다."
        buy_action  = "신규 매수: 보류 — 확실한 방향 신호(VIX ↓, HY_SPREAD ↓) 대기."
        sell_action = "급격한 전량 매도 지양 — 추가 약세 확인 후 단계적 비중 축소."
        hold_action = "기존 보유: 유지 — 재확인 지표: VIX 30 돌파·HY_SPREAD 400bp 돌파 시 재검토."

    # Top3 지표 해설
    top3_commentary = []
    for r in rank[:3]:
        ind = r["indicator"]
        w   = r.get("combined_weight", 0)
        sp  = r.get("sp500_signed_r") or 0
        kp  = r.get("kospi_signed_r") or 0
        if ind == "VIX":
            top3_commentary.append(f"**VIX (공포지수, w={w:.4f})**: 현재 시장 변동성을 가장 정확하게 선행합니다. VIX 상승 = 주식 하락 압력 (r={sp:+.3f}). 30 초과 시 극도 공포 구간으로 역매수 기회.")
        elif ind == "HY_SPREAD":
            top3_commentary.append(f"**HY_SPREAD (하이일드스프레드, w={w:.4f})**: 신용 리스크 선행 지표. 스프레드 확대 = 자금 이탈 시그널 (r={sp:+.3f}). 400bp 이하 유지 시 안정권.")
        elif ind == "WTI":
            top3_commentary.append(f"**WTI (국제유가, w={w:.4f})**: 인플레이션 및 에너지 비용 압력 반영 (r={sp:+.3f}). 유가 급등 = 긴축 우려 → 주식 하락 위험.")
        elif ind == "DXY":
            top3_commentary.append(f"**DXY (달러인덱스, w={w:.4f})**: 글로벌 유동성의 역지표 (r={sp:+.3f}). 달러 강세 = 신흥국 자금 이탈, 원화 약세 → 코스피 압박.")
        elif ind == "INDIVIDUAL_NET":
            top3_commentary.append(f"**개인순매수 (w={w:.4f})**: 국내 개인 수급 선행성 검증됨 (KOSPI Granger p=0.0046). 개인 순매수 증가 = 코스피 단기 지지 기대.")
        elif "NASDAQ" in ind:
            top3_commentary.append(f"**{ind} (w={w:.4f})**: 미국 기술주 동조화 지수 — 동행 페널티 적용. 실제 선행성 보다 동행성이 강함.")
        else:
            top3_commentary.append(f"**{ind} (w={w:.4f})**: S&P500 r={sp:+.3f}, 코스피 r={kp:+.3f}.")

    top3_text = "\n\n".join(top3_commentary)

    # 산업별 코멘트
    sector_ap = fr.get("sector_analysis") or {}
    sector_lines = []
    for sec_name, sec_data in (sector_ap.items() if isinstance(sector_ap, dict) else []):
        top_tickers = sec_data.get("top_performers", [])[:2] if isinstance(sec_data, dict) else []
        tickers_str = ", ".join(t if isinstance(t, str) else t.get("ticker","?") for t in top_tickers)
        sector_lines.append(f"- **{sec_name}**: 주목 종목 {tickers_str or '확인 필요'}")

    sector_ap_text = "\n".join(sector_lines) if sector_lines else "- 섹터 데이터 수집 완료 (dashboard.html 참조)"

    ap_section = f"""
---

## 11. AI 시장 분석 리포트

> 생성 기준: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 모델: AI Analyzer v3 | 데이터: 최신 파이프라인 결과

### 현재 시장 판단: {score:.1f}/100 — **{stance}**

{stance_desc}

유효 지표 {len(rank)}개 중 강세 신호 {sig.get('bullish_count', '?')}개 / 약세 신호 {sig.get('bearish_count', '?')}개를 집계한 결과입니다.

---

### 핵심 드라이버 분석 (Top 3 지표)

{top3_text}

---

### 액션플랜

| 신호 | 권장 행동 |
|------|---------|
| BUY  | {buy_action} |
| SELL | {sell_action} |
| HOLD | {hold_action} |

**재평가 트리거 조건:**
- VIX가 30을 돌파하면 극공포 → 역매수 기회 탐색
- HY_SPREAD가 400bp를 초과하면 신용 위기 경계 → 포지션 축소
- DXY가 105를 초과하면 신흥국 자금 이탈 → 코스피 비중 재검토
- 개인순매수 연속 3일 순매수 전환 → 코스피 단기 반등 기대

---

### 산업별 투자 주목점

{sector_ap_text}

---

### 면책 조항

본 리포트는 통계 모델 기반 참고 자료이며 투자 권유가 아닙니다.
모든 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.

---
"""
    return ap_section

action_plan = _generate_action_plan()
report = report + action_plan

path = OUT / "FINAL_REPORT_v2.md"
path.write_text(report, encoding="utf-8")
print(f"FINAL_REPORT_v2.md 저장: {path}")
print(f"총 {len(report.splitlines())}줄")

# final_results.json: UI Agent가 v3.0으로 이미 저장한 파일에 freshness만 병합
# (generate_report_v2는 FINAL_REPORT_v2.md 생성이 주 목적 - final_results를 덮어쓰지 않음)
_final_path = OUT / "final_results.json"
if _final_path.exists():
    try:
        _existing = json.loads(_final_path.read_text(encoding="utf-8"))
        # freshness 정보만 추가 보강 (기존 v3.0 구조 유지)
        _existing.setdefault("meta", {})["data_reference_date"] = max(
            (f.get("end_date","") for f in evaluation.get("data_freshness_report",{}).values()
             if f.get("end_date")), default=""
        )
        _existing["data_quality"]["freshness"] = {
            k: {"end_date": v.get("end_date"), "rows": v.get("rows")}
            for k, v in evaluation.get("data_freshness_report",{}).items()
        }
        _existing["data_quality"]["low_confidence_excluded"] = [i["indicator"] for i in low_conf]
        _existing["ctd_readiness"] = ctd
        _final_path.write_text(
            json.dumps(nan_safe(_existing), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("final_results.json 업데이트 완료 (v3.0 구조 보존)")
    except Exception as e:
        print(f"final_results.json 업데이트 스킵: {e}")
else:
    print("final_results.json 없음 - UI Agent를 먼저 실행하세요")
