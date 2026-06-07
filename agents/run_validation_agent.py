# -*- coding: utf-8 -*-
"""
Validation Agent — 전담 검증 에이전트
역할: 파이프라인의 모든 산출물을 독립적으로 검증한다.

검증 4개 레이어:
  Layer 1 — 유니버스 검증    : 분석 대상이 전체 지수 구성종목인가
  Layer 2 — 데이터 품질 검증 : 수집 데이터의 신뢰성 (교차검증, 신선도, 단위)
  Layer 3 — 결과 타당성 검증 : 극단값, 순위 일관성, 확증 편향 방지
  Layer 4 — 방법론 검증      : 공식 적용 오류, 단위 혼동, 기간 불일치

심각도:
  CRITICAL — 이 검증이 실패하면 output/ 저장을 차단
  WARNING  — 플래그 표시하고 계속 진행 (사람이 확인 필요)
  INFO     — 참고 정보

실행 위치: Evaluator Agent 완료 후, UI Agent 실행 전
"""

import json
import math
import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
OUT_DIR  = BASE_DIR / "output"

# ─────────────────────────────────────────────────────────────────────────────
# 검증 결과 구조
# ─────────────────────────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, layer: str, code: str, name: str, passed: bool,
            severity: str, detail: str, fix: str = ""):
        self.checks.append({
            "layer":    layer,
            "code":     code,
            "name":     name,
            "passed":   passed,
            "severity": severity,  # CRITICAL / WARNING / INFO
            "detail":   detail,
            "fix":      fix,
        })

    @property
    def critical_failures(self):
        return [c for c in self.checks if not c["passed"] and c["severity"] == "CRITICAL"]

    @property
    def warnings(self):
        return [c for c in self.checks if not c["passed"] and c["severity"] == "WARNING"]

    @property
    def passed_count(self):
        return sum(1 for c in self.checks if c["passed"])

    @property
    def total_count(self):
        return len(self.checks)

    def summary(self) -> dict:
        return {
            "total":            self.total_count,
            "passed":           self.passed_count,
            "failed_critical":  len(self.critical_failures),
            "failed_warning":   len(self.warnings),
            "pipeline_blocked": len(self.critical_failures) > 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: 유니버스 검증
# ─────────────────────────────────────────────────────────────────────────────

def validate_universe(vr: ValidationResult, stock_res: dict):
    layer = "L1_유니버스"
    universe = stock_res.get("universe", {})
    source   = universe.get("source", "")

    # U1: 동적 수집 여부
    is_dynamic = "fdr.StockListing" in source or "FDR(KRX" in source or "Wikipedia" in source
    vr.add(layer, "U1", "동적 유니버스 수집",
           is_dynamic,
           "CRITICAL",
           f"source={source[:60]}",
           "run_stock_agent_v2.py의 get_kospi_universe() / get_sp500_universe() 확인")

    # U2: KOSPI 커버리지
    kospi_size     = universe.get("kospi_size", 0)
    kospi_analyzed = universe.get("kospi_analyzed", 0)
    kospi_ok = kospi_size >= 50 and kospi_analyzed >= 50
    vr.add(layer, "U2", "KOSPI 커버리지",
           kospi_ok,
           "CRITICAL",
           f"시총 상위 {kospi_analyzed}/{kospi_size}개 분석",
           "KOSPI_TOP_N 값 확인 (최소 50개)")

    # U3: S&P500 커버리지
    sp500_size     = universe.get("sp500_size", 0)
    sp500_analyzed = universe.get("sp500_analyzed", 0)
    sp500_ok = sp500_size >= 100 and sp500_analyzed >= 100
    vr.add(layer, "U3", "S&P500 커버리지",
           sp500_ok,
           "CRITICAL",
           f"{sp500_analyzed}/{sp500_size}개 분석",
           "Wikipedia/FDR S&P500 유니버스 수집 확인")

    # U4: 커버리지 비율 (90% 이상)
    kospi_rate = kospi_analyzed / kospi_size if kospi_size > 0 else 0
    sp500_rate = sp500_analyzed / sp500_size if sp500_size > 0 else 0
    rate_ok = kospi_rate >= 0.9 and sp500_rate >= 0.9
    vr.add(layer, "U4", "커버리지 비율 90% 이상",
           rate_ok,
           "WARNING",
           f"KOSPI {kospi_rate*100:.1f}% / S&P500 {sp500_rate*100:.1f}%",
           "네트워크 상태 확인 또는 재실행")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: 데이터 품질 검증
# ─────────────────────────────────────────────────────────────────────────────

def validate_data_quality(vr: ValidationResult, stock_res: dict, eval_res: dict):
    layer = "L2_데이터품질"

    # D1: KOSPI Top5 교차검증 완료
    kospi_top5 = stock_res.get("f10_kospi_contribution_top5", [])
    unvalidated = [s["name"] for s in kospi_top5 if "불일치" in s.get("data_quality", "")]
    d1_ok = len(unvalidated) == 0
    vr.add(layer, "D1", "KOSPI Top5 교차검증 (FDR+yfinance)",
           d1_ok,
           "WARNING",
           f"불일치 종목: {unvalidated}" if unvalidated else "전항목 일치",
           "해당 종목 데이터 수동 확인")

    # D2: 최소 거래일수 (60일 이상)
    all_stocks = (
        stock_res.get("f09_sp500_contribution_top5", []) +
        stock_res.get("f10_kospi_contribution_top5", [])
    )
    low_days = [s["name"] for s in all_stocks if s.get("period_days", 0) < 60]
    d2_ok = len(low_days) == 0
    vr.add(layer, "D2", "최소 거래일수 (Top5 전항목 ≥60일)",
           d2_ok,
           "WARNING",
           f"부족 종목: {low_days}" if low_days else "전항목 충족",
           "해당 종목 상장일 확인 (신규 상장 가능성)")

    # D3: 시가총액 단위 이상 탐지 (S&P500은 달러, 비정상적 값 검출)
    sp500_caps = [s.get("market_cap_b", 0) for s in stock_res.get("f09_sp500_contribution_top5", [])]
    # S&P500 시총은 $B 단위: 정상 범위 10B~10,000B
    abnormal_caps = [c for c in sp500_caps if c > 0 and (c < 1 or c > 100_000)]
    d3_ok = len(abnormal_caps) == 0
    vr.add(layer, "D3", "시가총액 단위 일관성",
           d3_ok,
           "CRITICAL",
           f"비정상 시총(B$): {abnormal_caps}" if abnormal_caps else "정상 범위",
           "market_cap_b 계산식 단위 확인 ($/KRW 혼동)")

    # D4: 데이터 신선도 (7일 이내)
    freshness = eval_res.get("data_freshness_report", {})
    stale = [ind for ind, f in freshness.items() if f.get("days_since_last", 0) > 7]
    d4_ok = len(stale) <= 3  # 3개 이하 허용
    vr.add(layer, "D4", "데이터 신선도 (7일 초과 ≤3개)",
           d4_ok,
           "WARNING",
           f"신선도 초과: {stale}" if stale else "전항목 7일 이내",
           "run_data_agent_v2.py 재실행")

    # D5: raw 파일 존재 확인
    required_raw = ["SP500", "KOSPI", "NASDAQ100", "HY_SPREAD", "VIX"]
    missing_raw  = [r for r in required_raw if not (RAW_DIR / f"{r}.parquet").exists()]
    d5_ok = len(missing_raw) == 0
    vr.add(layer, "D5", "핵심 raw 데이터 파일 존재",
           d5_ok,
           "CRITICAL",
           f"누락: {missing_raw}" if missing_raw else f"필수 {len(required_raw)}개 존재",
           "run_data_agent_v2.py 실행")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3: 결과 타당성 검증 (확증 편향 방지)
# ─────────────────────────────────────────────────────────────────────────────

def validate_results(vr: ValidationResult, stock_res: dict, eval_res: dict):
    layer = "L3_결과타당성"

    kospi_ben  = stock_res.get("f12_kospi_beneficiary_top5", [])
    sp500_ben  = stock_res.get("f11_sp500_beneficiary_top5", [])
    kospi_con  = stock_res.get("f10_kospi_contribution_top5", [])
    sp500_con  = stock_res.get("f09_sp500_contribution_top5", [])

    # R1: 극단적 수익률 플래그 (±10,000% 이상은 데이터 오류 의심)
    all_returns = [s.get("stock_return_pct", 0) for s in kospi_ben + sp500_ben + kospi_con + sp500_con]
    extreme = [r for r in all_returns if abs(r) > 10_000]
    r1_ok = len(extreme) == 0
    vr.add(layer, "R1", "극단적 수익률 탐지 (±10,000% 초과)",
           r1_ok,
           "CRITICAL",
           f"의심 수익률: {extreme}" if extreme else "정상 범위",
           "해당 종목 FDR/yfinance 원본 데이터 직접 확인")

    # R2: 수혜 점수가 0인 종목이 Top5에 없는지
    zero_benefit = [s["name"] for s in kospi_ben + sp500_ben if s.get("beneficiary_score", 0) <= 0]
    r2_ok = len(zero_benefit) == 0
    vr.add(layer, "R2", "수혜 점수 양수 확인",
           r2_ok,
           "WARNING",
           f"0 이하 종목: {zero_benefit}" if zero_benefit else "전항목 양수",
           "음수 초과수익률 종목이 Top5에 포함된 경우 필터 확인")

    # R3: 기여 점수 상위 1위가 시총 상위에 있는지 (시총 최소 0.1조 이상)
    if kospi_con:
        top_kospi = kospi_con[0]
        top_mc = top_kospi.get("market_cap_b", 0)
        # KOSPI 기여 1위는 일반적으로 대형주 (시총 1조원 이상 = market_cap_b > 1,000,000 in KRW단위)
        # 실제로 market_cap_b는 KRW/1e9 단위이므로 SK하이닉스는 1,507,000 수준
        r3_ok = top_mc > 0
        vr.add(layer, "R3", "기여 1위 시가총액 존재",
               r3_ok,
               "WARNING",
               f"KOSPI 기여1위 {top_kospi['name']}: market_cap_b={top_mc:,.0f}",
               "시가총액 수집 실패 시 contribution_score 과소 계산됨")

    # R4: S&P500 기여 1위가 GOOGL/MSFT/AAPL/NVDA/AMZN 중 하나가 아니어도 설명이 있는지
    if sp500_con:
        top_sp = sp500_con[0]
        expected_giants = {"GOOGL","MSFT","AAPL","NVDA","AMZN","META","AVGO","TSLA"}
        is_expected = top_sp.get("ticker","") in expected_giants
        # 예상 밖이면 WARNING (데이터 오류일 수 있음, 실제 수익률이 높을 수도 있음)
        vr.add(layer, "R4", "S&P500 기여 1위 납득 가능 여부",
               True,  # 항상 PASS, 경고만 출력
               "INFO",
               f"1위: {top_sp['name']} ({top_sp.get('stock_return_pct',0):+.1f}%) "
               f"{'— 예상 종목' if is_expected else '— 비예상 종목(실제 데이터 확인 권장)'}",
               "비예상 종목의 경우 yfinance로 수익률 수동 확인")

    # R5: KOSPI 수혜 1위가 코스피 지수보다 초과수익률이 높은지
    if kospi_ben:
        top_ben = kospi_ben[0]
        excess  = top_ben.get("excess_return_pct", 0)
        r5_ok   = excess > 0
        vr.add(layer, "R5", "코스피 수혜 1위 초과수익률 양수",
               r5_ok,
               "WARNING",
               f"{top_ben['name']}: 초과수익 {excess:+.1f}%p",
               "초과수익률이 음수면 수혜 종목이 아님 — 필터 로직 확인")

    # R6: 동일 종목이 기여 Top5와 수혜 Top5 모두에 있는지 확인 (정합성)
    kospi_con_names = {s["name"] for s in kospi_con}
    kospi_ben_names = {s["name"] for s in kospi_ben}
    overlap = kospi_con_names & kospi_ben_names
    vr.add(layer, "R6", "기여/수혜 Top5 교차 확인",
           True,  # 겹쳐도 괜찮음 — 정보 제공용
           "INFO",
           f"기여+수혜 모두 상위권: {overlap}" if overlap else "기여/수혜 Top5가 완전히 다른 종목",
           "겹치는 종목은 '지수 성장의 핵심 수혜주'로 해석")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4: 방법론 검증
# ─────────────────────────────────────────────────────────────────────────────

def validate_methodology(vr: ValidationResult, stock_res: dict, eval_res: dict):
    layer = "L4_방법론"

    # M1: contribution_score = |corr| × |return| × (mc/단위) — 음수 불가
    all_contrib = (
        stock_res.get("f09_sp500_contribution_top5", []) +
        stock_res.get("f10_kospi_contribution_top5", [])
    )
    neg_scores = [s["name"] for s in all_contrib if s.get("contribution_score", 0) < 0]
    m1_ok = len(neg_scores) == 0
    vr.add(layer, "M1", "contribution_score 음수 없음",
           m1_ok,
           "CRITICAL",
           f"음수 점수: {neg_scores}" if neg_scores else "전항목 양수",
           "compute_contribution() 공식의 절댓값 처리 확인")

    # M2: beneficiary_score = excess_return × |corr| — 상관계수 1 초과 불가
    all_ben = (
        stock_res.get("f11_sp500_beneficiary_top5", []) +
        stock_res.get("f12_kospi_beneficiary_top5", [])
    )
    invalid_corr = [s["name"] for s in all_ben if abs(s.get("correlation", 0)) > 1.001]
    m2_ok = len(invalid_corr) == 0
    vr.add(layer, "M2", "상관계수 [-1, 1] 범위",
           m2_ok,
           "CRITICAL",
           f"범위 초과: {invalid_corr}" if invalid_corr else "전항목 정상",
           "pearsonr 계산 입력값 확인")

    # M3: 분석 기간 일치 (stock_results와 evaluation_results 기간 비교)
    stock_start  = stock_res.get("analysis_period", {}).get("start", "")
    eval_inds    = list(eval_res.get("data_freshness_report", {}).keys())
    # 분석 기간이 1년(250~260거래일)인지 확인
    sample_top5  = stock_res.get("f09_sp500_contribution_top5", [])
    period_days  = [s.get("period_days", 0) for s in sample_top5]
    valid_period = all(200 <= d <= 280 for d in period_days if d > 0)
    m3_ok = valid_period
    vr.add(layer, "M3", "분석 기간 200~280 거래일 (1년)",
           m3_ok,
           "WARNING",
           f"거래일수: {period_days}",
           "START 날짜 설정 확인 (timedelta(days=365))")

    # M4: 동일 기업 복수 클래스 중복 처리 안내
    sp500_tickers = [s.get("ticker", "") for s in stock_res.get("f09_sp500_contribution_top5", [])]
    dual_class = {"GOOGL", "GOOG"}  # Alphabet A/C
    has_dual = len(dual_class & set(sp500_tickers)) >= 2
    vr.add(layer, "M4", "동일 기업 복수 클래스 중복 여부",
           not has_dual,
           "WARNING",
           f"Alphabet 두 클래스 모두 Top5: {has_dual}",
           "GOOGL/GOOG는 동일 기업 — 하나만 포함하도록 중복 제거 로직 추가 고려")

    # M5: p-value 유의성 기준 적용 확인 (유의한 지표가 1개 이상)
    f13 = eval_res.get("f13_summary", {})
    sp_sig = f13.get("sp500_significant_count", 0)
    ksp_sig = f13.get("kospi_significant_count", 0)
    m5_ok = sp_sig >= 3 and ksp_sig >= 3
    vr.add(layer, "M5", "통계적 유의 지표 충분 (SP500/KOSPI 각 ≥3개)",
           m5_ok,
           "WARNING",
           f"SP500 유의: {sp_sig}개 / KOSPI 유의: {ksp_sig}개",
           "데이터 기간 또는 지표 수 확인")

    # M6: 최종 랭킹에 지표가 존재하는지
    valid_ranking = eval_res.get("f14_valid_ranking", [])
    m6_ok = len(valid_ranking) >= 5
    vr.add(layer, "M6", "유효 지표 랭킹 ≥5개",
           m6_ok,
           "CRITICAL",
           f"유효 지표: {len(valid_ranking)}개",
           "run_evaluator_agent_v2.py 재실행")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5: 파이프라인 일관성 검증 (이전 실행과 비교)
# ─────────────────────────────────────────────────────────────────────────────

def validate_pipeline_consistency(vr: ValidationResult, stock_res: dict):
    layer = "L5_파이프라인일관성"

    # P1: generated_at이 24시간 이내인지
    gen_at_str = stock_res.get("generated_at", "")
    try:
        gen_at  = datetime.fromisoformat(gen_at_str)
        age_hrs = (datetime.now() - gen_at).total_seconds() / 3600
        p1_ok   = age_hrs <= 24
        vr.add(layer, "P1", "Stock Agent 실행이 24시간 이내",
               p1_ok,
               "WARNING",
               f"생성: {gen_at_str[:16]} ({age_hrs:.1f}시간 전)",
               "run_stock_agent_v2.py 재실행 권장")
    except Exception:
        vr.add(layer, "P1", "Stock Agent 실행이 24시간 이내",
               False, "WARNING", "generated_at 파싱 실패", "")

    # P2: output/dashboard.html 존재 확인
    dash_path = OUT_DIR / "dashboard.html"
    p2_ok = dash_path.exists()
    size_kb = round(dash_path.stat().st_size / 1024, 1) if p2_ok else 0
    vr.add(layer, "P2", "dashboard.html 존재",
           p2_ok,
           "WARNING",
           f"크기: {size_kb}KB" if p2_ok else "파일 없음",
           "run_ui_agent.py 실행")

    # P3: final_results.json의 PM 조건이 모두 PASS인지
    final_path = OUT_DIR / "final_results.json"
    if final_path.exists():
        try:
            final = json.loads(final_path.read_text(encoding="utf-8"))
            pm = final.get("pm_conditions", {})
            failed_pm = [k for k, v in pm.items() if "PASS" not in str(v)]
            p3_ok = len(failed_pm) == 0
            vr.add(layer, "P3", "PM 조건 A~H 전항목 PASS",
                   p3_ok,
                   "WARNING",
                   f"FAIL 조건: {failed_pm}" if failed_pm else f"{len(pm)}개 전항목 PASS",
                   "실패 조건 해당 에이전트 재실행")
        except Exception as e:
            vr.add(layer, "P3", "PM 조건 A~H 전항목 PASS",
                   False, "WARNING", f"파일 파싱 실패: {e}", "")
    else:
        vr.add(layer, "P3", "PM 조건 A~H 전항목 PASS",
               False, "WARNING", "final_results.json 없음", "run_ui_agent.py 실행")

    # P4: sector_analysis.json 존재
    sector_path = OUT_DIR / "sector_analysis.json"
    p4_ok = sector_path.exists()
    vr.add(layer, "P4", "sector_analysis.json 존재 (Sector Agent 완료)",
           p4_ok,
           "INFO",
           "존재" if p4_ok else "없음 (첫 실행이거나 Sector Agent 미실행)",
           "run_sector_agent.py 실행")


# ─────────────────────────────────────────────────────────────────────────────
# 리포트 출력
# ─────────────────────────────────────────────────────────────────────────────

def print_report(vr: ValidationResult):
    summary = vr.summary()
    line = "=" * 65

    print(f"\n{line}")
    print(f"  VALIDATION REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(line)
    print(f"  총 검증: {summary['total']}개  |  "
          f"PASS: {summary['passed']}  |  "
          f"CRITICAL 실패: {summary['failed_critical']}  |  "
          f"WARNING: {summary['failed_warning']}")

    if summary["pipeline_blocked"]:
        print(f"\n  ⛔ PIPELINE BLOCKED — CRITICAL 실패로 output/ 저장 차단")
    else:
        print(f"\n  ✅ PIPELINE OK — 파이프라인 진행 가능")

    # 레이어별 출력
    layers = {}
    for c in vr.checks:
        layers.setdefault(c["layer"], []).append(c)

    for layer_name, checks in layers.items():
        print(f"\n  ── {layer_name} ──")
        for c in checks:
            icon   = "✓" if c["passed"] else ("✗" if c["severity"] == "CRITICAL" else ("△" if c["severity"] == "WARNING" else "ℹ"))
            sev    = f"[{c['severity']}]" if not c["passed"] else ""
            print(f"    {icon} {c['code']:3s} {c['name']:<38s} {sev}")
            if not c["passed"] or c["severity"] == "INFO":
                print(f"         → {c['detail']}")
            if not c["passed"] and c["fix"]:
                print(f"         수정: {c['fix']}")

    # CRITICAL 실패 요약
    if vr.critical_failures:
        print(f"\n  ⛔ CRITICAL 실패 목록:")
        for c in vr.critical_failures:
            print(f"    [{c['code']}] {c['name']}: {c['detail']}")
            if c["fix"]:
                print(f"         → {c['fix']}")

    print(f"\n{line}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run_validation() -> tuple[ValidationResult, dict]:
    """전체 검증 실행. 결과와 저장용 dict 반환."""
    vr = ValidationResult()

    # 입력 파일 로드
    stock_path = PROC_DIR / "stock_results.json"
    eval_path  = PROC_DIR / "evaluation_results.json"

    if not stock_path.exists():
        print("[ERROR] stock_results.json 없음 — run_stock_agent_v2.py 먼저 실행")
        exit(1)
    if not eval_path.exists():
        print("[ERROR] evaluation_results.json 없음 — run_evaluator_agent_v2.py 먼저 실행")
        exit(1)

    stock_res = json.loads(stock_path.read_text(encoding="utf-8"))
    eval_res  = json.loads(eval_path.read_text(encoding="utf-8"))

    # 5개 레이어 검증 실행
    print("  [L1] 유니버스 검증...")
    validate_universe(vr, stock_res)

    print("  [L2] 데이터 품질 검증...")
    validate_data_quality(vr, stock_res, eval_res)

    print("  [L3] 결과 타당성 검증...")
    validate_results(vr, stock_res, eval_res)

    print("  [L4] 방법론 검증...")
    validate_methodology(vr, stock_res, eval_res)

    print("  [L5] 파이프라인 일관성 검증...")
    validate_pipeline_consistency(vr, stock_res)

    # 리포트 저장
    report = {
        "generated_at":    datetime.now().isoformat(),
        "summary":         vr.summary(),
        "checks":          vr.checks,
        "pipeline_status": "BLOCKED" if vr.critical_failures else "OK",
    }
    report_path = PROC_DIR / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return vr, report


if __name__ == "__main__":
    print("=" * 65)
    print("VALIDATION AGENT — 5-Layer 독립 검증 시스템")
    print("  L1: 유니버스  L2: 데이터품질  L3: 결과타당성")
    print("  L4: 방법론    L5: 파이프라인일관성")
    print("=" * 65)

    vr, report = run_validation()
    print_report(vr)

    summary = report["summary"]
    print(f"검증 리포트 저장: {PROC_DIR / 'validation_report.json'}")
    print(f"상태: {report['pipeline_status']} "
          f"({summary['passed']}/{summary['total']} PASS, "
          f"CRITICAL {summary['failed_critical']}개)")

    # CRITICAL 실패 시 exit code 1 (파이프라인 차단)
    if report["pipeline_status"] == "BLOCKED":
        print("\n⛔ CRITICAL 실패 항목을 수정하고 재실행하십시오.")
        exit(1)
    else:
        print("\n✅ 검증 완료 — UI Agent 실행 가능")
        exit(0)
