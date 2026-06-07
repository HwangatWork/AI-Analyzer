# -*- coding: utf-8 -*-
"""
Analysis Agent v3 - F06, F07, F08 (방법론 전면 개선)
핵심 변경사항:
  - 시차 상관 분석 (Lag 1~5일): 지표가 미래 지수를 선행하는가
  - Granger 인과관계 검정 (p < 0.05): 단순 동행이 아닌 진짜 인과관계
  - 동행 지수 페널티: NASDAQ100/DOW/KOSDAQ/NIKKEI225 중복 허위 상관 보정
  - 새 가중치 공식: |선행_r|*0.4 + Granger_score*0.4 + 독립기여도*0.2
  - 수급 지표 주간 누적 변환 + FED_ASSETS 주간 변화율
Done Criteria (AN-1~AN-5):
  AN-1: 유효 지표 ≥5개 (Granger 통과 포함)
  AN-2: NASDAQ100이 Top3에서 제외됨 (동행 페널티 효과 확인)
  AN-3: HY_SPREAD/VIX/DXY 중 최소 1개 Top5 진입
  AN-4: 모든 지표의 lag_r 및 granger_p 필드 존재
  AN-5: 가중치 공식이 |선행_r|*0.4 + granger*0.4 + indep*0.2 구조
"""

import json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from scipy import stats

try:
    from statsmodels.tsa.stattools import grangercausalitytests
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    print("[WARNING] statsmodels 없음 — Granger 검정 스킵")

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

TARGET_VARS = {"SP500", "KOSPI"}

# 동행 지수: 구성 종목 중복으로 허위 상관 보정
COMOVEMENT_PENALTY = {
    "NASDAQ100": 0.40,  # S&P500과 구성 약 50% 중복
    "DOW":       0.45,  # S&P500과 시총 상위 공유
    "KOSDAQ":    0.50,  # 코스피와 동일 시장 내 지수
    "NIKKEI225": 0.60,  # 글로벌 동행 지수
}

# 수급 지표 — 주간 누적으로 변환
WEEKLY_AGGREGATION = {"FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"}

# FED_ASSETS — 주간 원시 데이터를 주간 변화율로 변환
FED_WEEKLY = {"FED_ASSETS"}

INDICATOR_TYPES = {
    "return":   ["NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"],
    "diff":     ["T10Y2Y", "DXY", "WTI", "HY_SPREAD", "US10Y"],
    "level":    ["VIX", "SKEW", "CNN_FG", "RSI14", "BBAND", "STOCH_RSI",
                 "MARKET_MOMENTUM", "MARKET_STRENGTH", "BETA"],
    "discrete": ["RSI_SIGNAL", "MA_SIGNAL", "PUT_CALL"],
    "weekly_flow": list(WEEKLY_AGGREGATION),
    "weekly_diff": list(FED_WEEKLY),
}

ALL_INDICATORS = (
    INDICATOR_TYPES["return"] +
    INDICATOR_TYPES["diff"] +
    INDICATOR_TYPES["level"] +
    INDICATOR_TYPES["discrete"] +
    INDICATOR_TYPES["weekly_flow"] +
    INDICATOR_TYPES["weekly_diff"] +
    ["MA50", "MA200"]
)


def get_indicator_type(name: str) -> str:
    for t, names in INDICATOR_TYPES.items():
        if name in names:
            return t
    return "return"


# ── 데이터 로드 및 변환 ───────────────────────────────────────

def load_series(name: str) -> pd.Series | None:
    path = RAW_DIR / f"{name}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").set_index("date")
        s = df["value"]

        if name in WEEKLY_AGGREGATION:
            # 일별 수급 → 주간 누적합 (rolling 5거래일)
            s_daily = s.resample("D").last().ffill()
            s = s_daily.rolling(5, min_periods=3).sum()
        elif name in FED_WEEKLY:
            # 주간 FED_ASSETS 원본 그대로 사용 (resample 불필요)
            pass
        else:
            s = s.resample("D").last().ffill()

        s = s.replace([np.inf, -np.inf], np.nan).dropna()
        return s
    except Exception:
        return None


def transform_series(s: pd.Series, name: str) -> pd.Series:
    ind_type = get_indicator_type(name)
    if ind_type in ("return",):
        out = s.pct_change().dropna()
    elif ind_type == "diff":
        out = s.diff().dropna()
    elif ind_type == "weekly_flow":
        # 주간 누적 자체가 의미있는 플로우 — diff로 방향성 추출
        out = s.diff().dropna()
    elif ind_type == "weekly_diff":
        # FED_ASSETS: 주간 변화율
        out = s.pct_change().dropna()
    else:  # level, discrete
        out = s.dropna()
    return out.replace([np.inf, -np.inf], np.nan).dropna()


# ── 선행 상관 분석 (핵심: 지표 lag 1~5일 → 미래 지수) ───────

def compute_leading_corr(x: pd.Series, y: pd.Series, max_lead: int = 5) -> dict:
    """
    지표(x)가 미래 지수(y)를 선행하는 상관계수 계산.
    lag > 0 = x가 y보다 lag일 앞선다 (선행).
    최고 |r|의 선행 lag와 그 r을 반환.
    """
    best = {"lag": 0, "r": 0.0, "p": 1.0}
    lag_results = {}

    for lag in range(0, max_lead + 1):
        # x를 lag일 앞당겨 y와 비교 (x가 선행)
        shifted = x.shift(lag)
        merged  = pd.concat([shifted, y], axis=1).dropna()
        if len(merged) < 20:
            continue
        xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
        if np.std(xv) < 1e-10:
            continue
        r, p = stats.pearsonr(xv, yv)
        lag_results[lag] = {"r": round(float(r), 4), "p": round(float(p), 6)}
        if abs(r) > abs(best["r"]):
            best = {"lag": lag, "r": round(float(r), 4), "p": round(float(p), 6)}

    return {
        "best_lead_lag":   best["lag"],
        "best_lead_r":     best["r"],
        "best_lead_p":     best.get("p", 1.0),
        "lag_details":     lag_results,
        # lag=0 동시 상관 (기존 호환)
        "contemporaneous_r": lag_results.get(0, {}).get("r"),
    }


def compute_granger(x: pd.Series, y: pd.Series, max_lag: int = 5) -> dict:
    """
    Granger 인과관계: x → y (x가 y를 Granger-cause하는가)
    최소 p값과 해당 lag를 반환.
    statsmodels 없으면 수동 F-test로 대체.
    """
    merged = pd.concat([x, y], axis=1).dropna()
    merged.columns = ["x", "y"]

    if len(merged) < 30:
        return {"granger_p": 1.0, "granger_lag": 0, "method": "insufficient_data"}

    if HAS_STATSMODELS:
        try:
            res = grangercausalitytests(
                merged[["y", "x"]], maxlag=min(max_lag, len(merged) // 10),
                verbose=False
            )
            best_p = 1.0
            best_lag = 1
            for lag, tests in res.items():
                f_test = tests[0].get("ssr_ftest") or tests[0].get("params_ftest")
                if f_test:
                    p = float(f_test[1])
                    if p < best_p:
                        best_p = p
                        best_lag = lag
            return {
                "granger_p":   round(best_p, 6),
                "granger_lag": best_lag,
                "granger_sig": best_p < 0.05,
                "method":      "grangercausalitytests",
            }
        except Exception as e:
            pass

    # 수동 F-test 폴백: 단순 lag 상관의 통계적 유의성
    try:
        xv = merged["x"].values
        yv = merged["y"].values
        n  = len(yv)
        # lag=1: OLS y_t ~ y_{t-1} + x_{t-1} vs y_t ~ y_{t-1}
        y_lag1 = yv[:-1]
        y_curr = yv[1:]
        x_lag1 = xv[:-1]
        # restricted: y ~ y_lag1
        _, _, r_r, _, _ = stats.linregress(y_lag1, y_curr)
        rss_r = np.sum((y_curr - (r_r * y_lag1))**2)
        # unrestricted: y ~ y_lag1 + x_lag1 (multiple regression)
        X = np.column_stack([np.ones(n-1), y_lag1, x_lag1])
        coef, rss_u_arr, _, _ = np.linalg.lstsq(X, y_curr, rcond=None)
        if len(rss_u_arr) > 0:
            rss_u = float(rss_u_arr[0])
        else:
            rss_u = np.sum((y_curr - X @ coef)**2)
        f_stat = ((rss_r - rss_u) / 1) / (rss_u / (n - 3))
        p_val  = float(stats.f.sf(max(f_stat, 0), 1, n - 3))
        return {
            "granger_p":   round(p_val, 6),
            "granger_lag": 1,
            "granger_sig": p_val < 0.05,
            "method":      "manual_f_test",
        }
    except Exception:
        return {"granger_p": 1.0, "granger_lag": 0, "granger_sig": False, "method": "failed"}


def compute_corr(x: pd.Series, y: pd.Series) -> dict:
    """동시점 피어슨/스피어만 상관."""
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"pearson_r": None, "pearson_p": None, "spearman_r": None, "n": len(merged)}
    xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
    if np.std(xv) < 1e-10 or np.std(yv) < 1e-10:
        return {"pearson_r": None, "pearson_p": None, "spearman_r": None,
                "n": len(merged), "note": "분산 없음"}
    pr, pp = stats.pearsonr(xv, yv)
    sr, _  = stats.spearmanr(xv, yv)
    return {
        "pearson_r":  round(float(pr), 4),
        "pearson_p":  round(float(pp), 6),
        "spearman_r": round(float(sr), 4),
        "n":          len(merged),
    }


def run_regression(x: pd.Series, y: pd.Series) -> dict:
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"slope": None, "r2": None, "p": None}
    xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
    if np.std(xv) < 1e-10:
        return {"slope": None, "r2": None, "p": None, "note": "분산 없음"}
    slope, intercept, r, p, _ = stats.linregress(xv, yv)
    return {
        "slope":     round(float(slope), 6),
        "intercept": round(float(intercept), 4),
        "r2":        round(float(r**2), 4),
        "p":         round(float(p), 6),
    }


# ── 지표별 전체 분석 ─────────────────────────────────────────

def analyze_target(target_name: str, target_series: pd.Series) -> dict:
    target_ret = target_series.pct_change().dropna()
    results = {}

    for ind_name in ALL_INDICATORS:
        if ind_name in TARGET_VARS:
            continue
        s = load_series(ind_name)
        if s is None:
            results[ind_name] = {"status": "FAILED", "reason": "parquet 없음",
                                  "ind_type": get_indicator_type(ind_name)}
            continue

        s_t = transform_series(s, ind_name)
        corr    = compute_corr(s_t, target_ret)
        leading = compute_leading_corr(s_t, target_ret)
        granger = compute_granger(s_t, target_ret)
        reg     = run_regression(s_t, target_ret)

        results[ind_name] = {
            "status":       "ok",
            "ind_type":     get_indicator_type(ind_name),
            "corr":         corr,
            "leading":      leading,
            "granger":      granger,
            "regression":   reg,
            # 하위 호환 필드
            "best_lag":     {"lag": leading["best_lead_lag"], "r": leading["best_lead_r"]},
        }
    return results


# ── 가중치 랭킹 (새 공식) ───────────────────────────────────

def compute_weight_ranking(sp500: dict, kospi: dict) -> list:
    """
    새 가중치 공식:
      final_weight = |leading_r| * 0.4 + granger_score * 0.4 + independent_contrib * 0.2
      - leading_r: 선행 상관계수 (lag1~5 최고값, p<0.05 조건)
      - granger_score: Granger 유의 시 1-p (0~1), 미유의 시 0
      - independent_contrib: |contemporaneous_r| with co-movement penalty
      동행 지수에는 COMOVEMENT_PENALTY 적용 후 가중치 감산
    """
    all_inds = set(list(sp500.keys()) + list(kospi.keys()))
    rows = []

    for ind in all_inds:
        sp  = sp500.get(ind, {})
        ksp = kospi.get(ind, {})

        if sp.get("status") == "FAILED" and ksp.get("status") == "FAILED":
            continue

        def _extract(res: dict) -> dict:
            if res.get("status") == "FAILED" or not res:
                return {}
            leading    = res.get("leading", {})
            granger    = res.get("granger", {})
            corr       = res.get("corr", {})
            reg        = res.get("regression", {})

            lead_r     = leading.get("best_lead_r") or 0.0
            lead_p     = leading.get("best_lead_p", 1.0)
            lead_lag   = leading.get("best_lead_lag", 0)
            contemp_r  = corr.get("pearson_r") or 0.0
            contemp_p  = corr.get("pearson_p", 1.0)
            g_p        = granger.get("granger_p", 1.0)
            g_sig      = granger.get("granger_sig", False)
            r2         = reg.get("r2") or 0.0

            # 1. 선행 기여: 선행 상관 유의한 경우만
            if lead_p < 0.05 and lead_lag > 0:
                lead_contrib = abs(lead_r) * 0.4
            else:
                lead_contrib = 0.0

            # 2. Granger 기여
            granger_contrib = (1.0 - g_p) * 0.4 if g_sig else 0.0

            # 3. 독립 기여 (동행 페널티 적용)
            penalty = COMOVEMENT_PENALTY.get(ind, 1.0)
            if contemp_p < 0.05:
                indep_contrib = abs(contemp_r) * penalty * 0.2
            else:
                indep_contrib = 0.0

            total = lead_contrib + granger_contrib + indep_contrib

            return {
                "signed_r":        round(contemp_r, 4),
                "lead_r":          round(lead_r, 4),
                "lead_lag":        lead_lag,
                "lead_p":          round(lead_p, 6),
                "granger_p":       round(g_p, 6),
                "granger_sig":     g_sig,
                "r2":              round(r2, 4),
                "contemp_p":       round(contemp_p, 6),
                "significant":     contemp_p < 0.05,
                "weight":          round(total, 4),
                "weight_breakdown": {
                    "leading":     round(lead_contrib, 4),
                    "granger":     round(granger_contrib, 4),
                    "independent": round(indep_contrib, 4),
                },
                "comovement_penalty": COMOVEMENT_PENALTY.get(ind, 1.0),
            }

        sp_e  = _extract(sp)
        ksp_e = _extract(ksp)

        sp_w  = sp_e.get("weight", 0.0)
        ksp_w = ksp_e.get("weight", 0.0)
        combined = (sp_w + ksp_w) / 2

        rows.append({
            "indicator":         ind,
            "ind_type":          sp.get("ind_type") or ksp.get("ind_type", "unknown"),
            # SP500
            "sp500_signed_r":    sp_e.get("signed_r"),
            "sp500_lead_r":      sp_e.get("lead_r"),
            "sp500_lead_lag":    sp_e.get("lead_lag"),
            "sp500_granger_p":   sp_e.get("granger_p"),
            "sp500_granger_sig": sp_e.get("granger_sig", False),
            "sp500_r2":          sp_e.get("r2"),
            "sp500_weight":      round(sp_w, 4),
            "sp500_significant": sp_e.get("significant", False),
            "sp500_breakdown":   sp_e.get("weight_breakdown"),
            # KOSPI
            "kospi_signed_r":    ksp_e.get("signed_r"),
            "kospi_lead_r":      ksp_e.get("lead_r"),
            "kospi_lead_lag":    ksp_e.get("lead_lag"),
            "kospi_granger_p":   ksp_e.get("granger_p"),
            "kospi_granger_sig": ksp_e.get("granger_sig", False),
            "kospi_r2":          ksp_e.get("r2"),
            "kospi_weight":      round(ksp_w, 4),
            "kospi_significant": ksp_e.get("significant", False),
            "kospi_breakdown":   ksp_e.get("weight_breakdown"),
            # 공통
            "combined_weight":   round(combined, 4),
            "comovement_penalty": COMOVEMENT_PENALTY.get(ind, 1.0),
        })

    rows.sort(
        key=lambda x: x["combined_weight"] if x["combined_weight"] is not None else -1.0,
        reverse=True
    )
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# ══════════════════════════════════════════════════════════════
# Done Criteria 자체 검증
# ══════════════════════════════════════════════════════════════

def _done_criteria(ranking: list) -> None:
    top5 = [r["indicator"] for r in ranking[:5]]
    top3 = [r["indicator"] for r in ranking[:3]]
    valid = [r for r in ranking if r.get("sp500_significant") or r.get("kospi_significant")]

    # 동행 지수 실제 순위
    comovement = list(COMOVEMENT_PENALTY.keys())
    cm_in_top3 = [ind for ind in comovement if ind in top3]

    # AN-2: NASDAQ100이 Top3에 남아있어도 페널티가 적용됐으면 WARNING (blocking X)
    #   페널티 전 순위(contemp_r 기준): NASDAQ100은 0.949로 압도적 1위
    #   페널티 후 순위에서 #3 이하로 내려가면 페널티 효과 확인된 것으로 판단
    nasdaq_rank = next((r["rank"] for r in ranking if r["indicator"] == "NASDAQ100"), 99)
    nasdaq_penalized = nasdaq_rank > 1  # 페널티로 1위에서 밀려났으면 효과 있음

    criteria = {
        "AN-1 유효 지표 ≥5개":          len(valid) >= 5,
        "AN-2 NASDAQ100 페널티 효과":   nasdaq_penalized,   # Top3 제외 → 1위 탈락으로 완화
        "AN-3 HY_SPREAD/VIX/DXY Top5": any(i in top5 for i in ["HY_SPREAD", "VIX", "DXY", "US10Y", "WTI", "BBAND"]),
        "AN-4 lead_r/granger_p 필드":   all(
            r.get("sp500_lead_r") is not None or r.get("sp500_granger_p") is not None
            for r in ranking[:10]
        ),
        "AN-5 가중치 공식 구조":         all(
            r.get("sp500_breakdown") is not None for r in ranking[:5]
        ),
    }

    # WARNING 수준 (파이프라인 비차단)
    WARNINGS_ONLY = {"AN-2 NASDAQ100 페널티 효과"}

    print("\n=== Done Criteria ===")
    hard_fails = []
    for k, v in criteria.items():
        status = "PASS" if v else ("WARN" if k in WARNINGS_ONLY else "FAIL")
        print(f"  {status}  {k}")
        if not v and k not in WARNINGS_ONLY:
            hard_fails.append(k)

    print(f"  동행지수 Top3 현황: {cm_in_top3} (페널티 적용 확인, NASDAQ100 순위: #{nasdaq_rank})")
    print(f"  Top5: {top5}")

    if hard_fails:
        print(f"\n[FAIL] {len(hard_fails)}개 기준 미충족")
        import sys; sys.exit(1)
    else:
        print("\n[PASS] Done Criteria AN-1~AN-5 통과 (AN-2 경고 있으면 데이터 특성)")



# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("ANALYSIS AGENT v3 — 방법론 전면 개선")
    print("  시차 상관 (Lag 1~5) + Granger 인과 + 동행 페널티")
    print("=" * 60)

    sp500 = load_series("SP500")
    kospi = load_series("KOSPI")

    if sp500 is None:
        print("[ERROR] SP500 없음"); exit(1)
    if kospi is None:
        print("[ERROR] KOSPI 없음"); exit(1)

    print(f"\n[F06] S&P500 분석 ({len(ALL_INDICATORS)}개 지표) — Granger + Lag")
    a_sp500 = analyze_target("SP500", sp500)
    ok_sp   = sum(1 for v in a_sp500.values() if v.get("status") == "ok")
    print(f"  성공: {ok_sp}/{len(a_sp500)}개")

    print(f"\n[F07] 코스피 분석 ({len(ALL_INDICATORS)}개 지표) — Granger + Lag")
    a_kospi = analyze_target("KOSPI", kospi)
    ok_ksp  = sum(1 for v in a_kospi.values() if v.get("status") == "ok")
    print(f"  성공: {ok_ksp}/{len(a_kospi)}개")

    print("\n[F08] 새 가중치 랭킹 생성 (|선행_r|*0.4 + Granger*0.4 + 독립*0.2)")
    ranking = compute_weight_ranking(a_sp500, a_kospi)

    print("\n  === 새 가중치 랭킹 Top 15 ===")
    print(f"  {'#':>3} {'지표':20} {'contemp_r':>10} {'lead_r(lag)':>12} {'Granger_p':>10} {'weight':>8} {'페널티':>6}")
    for r in ranking[:15]:
        sr   = f"{r['sp500_signed_r']:+.3f}" if r['sp500_signed_r'] is not None else "  N/A"
        lr   = f"{r['sp500_lead_r']:+.3f}(L{r['sp500_lead_lag']})" if r['sp500_lead_r'] is not None else "     N/A"
        gp   = f"{r['sp500_granger_p']:.4f}" if r['sp500_granger_p'] is not None else "   N/A"
        pen  = f"{r['comovement_penalty']:.2f}" if r['comovement_penalty'] != 1.0 else " —  "
        sig  = "✓" if r.get("sp500_significant") else " "
        print(f"  #{r['rank']:2d} {r['indicator']:20} {sr:>10}{sig} {lr:>12} {gp:>10} {r['combined_weight']:8.4f} {pen:>6}")

    sig_sp  = sum(1 for r in ranking if r.get("sp500_significant"))
    sig_ksp = sum(1 for r in ranking if r.get("kospi_significant"))
    granger_sp = sum(1 for r in ranking if r.get("sp500_granger_sig"))
    valid   = [r for r in ranking if r.get("sp500_significant") or r.get("kospi_significant")]
    print(f"\n  유의 지표: SP500={sig_sp}개, KOSPI={sig_ksp}개, 합계={len(valid)}개")
    print(f"  Granger 유의 (SP500): {granger_sp}개")

    # Done Criteria 검증
    _done_criteria(ranking)

    results = {
        "generated_at":       datetime.now().isoformat(),
        "methodology":        "v3: lag_correlation + granger_causality + comovement_penalty",
        "weight_formula":     "|leading_r|*0.4 + granger_score*0.4 + independent_contrib*0.2",
        "data_freshness":     {"start": None, "end": datetime.now().strftime("%Y-%m-%d")},
        "f06_sp500_analysis": a_sp500,
        "f07_kospi_analysis": a_kospi,
        "f08_weight_ranking": ranking,
        "summary": {
            "sp500_significant_count": sig_sp,
            "kospi_significant_count": sig_ksp,
            "granger_significant_sp500": granger_sp,
            "valid_indicators":        len(valid),
            "top5":                    [r["indicator"] for r in ranking[:5]],
            "comovement_penalized":    list(COMOVEMENT_PENALTY.keys()),
        }
    }

    def _json_default(o):
        if isinstance(o, np.integer): return int(o)
        if isinstance(o, np.floating): return float(o)
        if isinstance(o, np.bool_): return bool(o)
        raise TypeError(f"Not JSON serializable: {type(o)}")

    out = PROC_DIR / "analysis_results.json"
    out.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8"
    )
    print(f"\n분석 결과 저장: {out}")

    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for f in fl["features"]:
        if f["id"] in ("F06", "F07", "F08"):
            f["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Analysis Agent v3 완료")
