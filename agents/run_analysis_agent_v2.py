# -*- coding: utf-8 -*-
"""
Analysis Agent v2 - F06, F07, F08 (개선판)
수정사항:
  - 지표 유형별 분석 방법 분리 (level / diff / discrete / return)
  - T10Y2Y 등 금리 계열: pct_change 대신 diff()
  - 이산 지표(RSI_SIGNAL 등): 원값 그대로 상관분석
  - VIX 부호 보존 (signed_r 필드 추가)
  - NaN 정렬 버그 수정
  - 타겟 변수(SP500/KOSPI) 분석 대상에서 제외
"""

import json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

# Fix: 타겟 변수는 분석 대상에서 제외
TARGET_VARS = {"SP500", "KOSPI"}

# Fix: 지표 유형 분류
# return  -> pct_change (주가 계열)
# diff    -> diff() (금리·스프레드·자산 등 절대값 의미있는 계열)
# level   -> 원값 그대로 (RSI, VIX 등 이미 의미있는 단위)
# discrete-> 원값 그대로 (이산 신호값)
INDICATOR_TYPES = {
    "return":   ["NASDAQ100", "DOW", "KOSDAQ", "NIKKEI225"],
    "diff":     ["T10Y2Y", "DXY", "WTI", "FED_ASSETS", "HY_SPREAD", "US10Y"],
    "level":    ["VIX", "SKEW", "CNN_FG", "RSI14", "BBAND", "STOCH_RSI",
                 "MARKET_MOMENTUM", "MARKET_STRENGTH", "BETA"],
    "discrete": ["RSI_SIGNAL", "MA_SIGNAL", "PUT_CALL"],
}

# 분석할 지표 목록 (타겟 제외)
ALL_INDICATORS = (
    INDICATOR_TYPES["return"] +
    INDICATOR_TYPES["diff"] +
    INDICATOR_TYPES["level"] +
    INDICATOR_TYPES["discrete"] +
    ["MA50", "MA200", "FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]
)


def get_indicator_type(name: str) -> str:
    for t, names in INDICATOR_TYPES.items():
        if name in names:
            return t
    return "return"  # 기본값


def load_series(name: str) -> pd.Series | None:
    path = RAW_DIR / f"{name}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").set_index("date")
        s = df["value"].resample("D").last().ffill()
        s = s.replace([np.inf, -np.inf], np.nan).dropna()
        return s
    except Exception:
        return None


def transform_series(s: pd.Series, name: str) -> pd.Series:
    """지표 유형에 따라 변환"""
    ind_type = get_indicator_type(name)
    if ind_type == "return":
        out = s.pct_change().dropna()
    elif ind_type == "diff":
        out = s.diff().dropna()
    else:  # level, discrete
        out = s.dropna()
    # inf 제거 (변환 후 추가 안전장치)
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def compute_corr(x: pd.Series, y: pd.Series, name: str) -> dict:
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"pearson_r": None, "pearson_p": None,
                "spearman_r": None, "spearman_p": None, "n": len(merged)}
    xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
    if np.std(xv) < 1e-10 or np.std(yv) < 1e-10:
        return {"pearson_r": None, "pearson_p": None,
                "spearman_r": None, "spearman_p": None,
                "n": len(merged), "note": "분산 없음"}
    pr, pp = stats.pearsonr(xv, yv)
    sr, sp = stats.spearmanr(xv, yv)
    return {
        "pearson_r":  round(float(pr), 4),  # Fix: 부호 보존 (절대값 X)
        "pearson_p":  round(float(pp), 6),
        "spearman_r": round(float(sr), 4),
        "spearman_p": round(float(sp), 6),
        "n": len(merged),
    }


def compute_lag_corr(x: pd.Series, y: pd.Series, max_lag: int = 5) -> dict:
    best = {"lag": 0, "r": 0.0}
    for lag in range(-max_lag, max_lag + 1):
        shifted = x.shift(lag)
        merged  = pd.concat([shifted, y], axis=1).dropna()
        if len(merged) < 20:
            continue
        xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
        if np.std(xv) < 1e-10:
            continue
        r, _ = stats.pearsonr(xv, yv)
        if abs(r) > abs(best["r"]):
            best = {"lag": lag, "r": round(float(r), 4)}
    return best


def run_regression(x: pd.Series, y: pd.Series) -> dict:
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"slope": None, "intercept": None, "r2": None, "p": None}
    xv, yv = merged.iloc[:, 0].values, merged.iloc[:, 1].values
    if np.std(xv) < 1e-10:
        return {"slope": None, "intercept": None, "r2": None, "p": None,
                "note": "분산 없음"}
    slope, intercept, r, p, _ = stats.linregress(xv, yv)
    return {
        "slope":     round(float(slope), 6),
        "intercept": round(float(intercept), 4),
        "r2":        round(float(r**2), 4),
        "p":         round(float(p), 6),
    }


def analyze_target(target_name: str, target_series: pd.Series) -> dict:
    target_ret = target_series.pct_change().dropna()
    results = {}

    for ind_name in ALL_INDICATORS:
        if ind_name in TARGET_VARS:  # Fix: 타겟 변수 제외
            continue
        s = load_series(ind_name)
        if s is None:
            results[ind_name] = {"status": "FAILED", "reason": "parquet 없음",
                                  "ind_type": get_indicator_type(ind_name)}
            continue

        s_transformed = transform_series(s, ind_name)
        corr = compute_corr(s_transformed, target_ret, ind_name)
        lag  = compute_lag_corr(s_transformed, target_ret)
        reg  = run_regression(s_transformed, target_ret)

        results[ind_name] = {
            "status":   "ok",
            "ind_type": get_indicator_type(ind_name),
            "corr":     corr,
            "best_lag": lag,
            "regression": reg,
        }
    return results


def compute_weight_ranking(sp500: dict, kospi: dict) -> list:
    all_inds = set(list(sp500.keys()) + list(kospi.keys()))
    rows = []

    for ind in all_inds:
        sp  = sp500.get(ind, {})
        ksp = kospi.get(ind, {})

        # Fix: 부호 보존 - abs는 가중치 계산에만, 출력에는 signed_r 사용
        sp_r_signed  = sp.get("corr", {}).get("pearson_r")   # None 가능
        ksp_r_signed = ksp.get("corr", {}).get("pearson_r")
        sp_r_abs     = abs(sp_r_signed)  if sp_r_signed  is not None else None
        ksp_r_abs    = abs(ksp_r_signed) if ksp_r_signed is not None else None
        sp_p         = sp.get("corr", {}).get("pearson_p")
        ksp_p        = ksp.get("corr", {}).get("pearson_p")
        sp_r2        = sp.get("regression", {}).get("r2")  or 0
        ksp_r2       = ksp.get("regression", {}).get("r2") or 0

        def weight(r_abs, p, r2):
            if r_abs is None or p is None or p >= 0.05:
                return 0.0
            return r_abs * 0.5 + r2 * 0.5

        sp_w  = weight(sp_r_abs,  sp_p,  sp_r2)
        ksp_w = weight(ksp_r_abs, ksp_p, ksp_r2)
        combined = (sp_w + ksp_w) / 2

        rows.append({
            "indicator":          ind,
            "ind_type":           sp.get("ind_type") or ksp.get("ind_type", "unknown"),
            # Fix: signed_r (방향 정보 보존)
            "sp500_signed_r":     round(sp_r_signed,  4) if sp_r_signed  is not None else None,
            "sp500_abs_r":        round(sp_r_abs,     4) if sp_r_abs     is not None else None,
            "sp500_p":            round(sp_p,         6) if sp_p         is not None else None,
            "sp500_r2":           round(sp_r2,        4),
            "sp500_weight":       round(sp_w,         4),
            "sp500_significant":  sp_p is not None and sp_p < 0.05,
            "kospi_signed_r":     round(ksp_r_signed, 4) if ksp_r_signed is not None else None,
            "kospi_abs_r":        round(ksp_r_abs,    4) if ksp_r_abs    is not None else None,
            "kospi_p":            round(ksp_p,        6) if ksp_p        is not None else None,
            "kospi_r2":           round(ksp_r2,       4),
            "kospi_weight":       round(ksp_w,        4),
            "kospi_significant":  ksp_p is not None and ksp_p < 0.05,
            "combined_weight":    round(combined,     4),
        })

    # Fix: NaN 정렬 버그 수정 - NaN/None을 -1로 치환 후 정렬
    rows.sort(
        key=lambda x: x["combined_weight"] if (
            x["combined_weight"] is not None and not np.isnan(x["combined_weight"])
        ) else -1.0,
        reverse=True
    )
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


if __name__ == "__main__":
    print("=" * 60)
    print("ANALYSIS AGENT v2 - Phase 3 (F06, F07, F08)")
    print("=" * 60)

    sp500 = load_series("SP500")
    kospi = load_series("KOSPI")

    if sp500 is None:
        print("[ERROR] SP500 없음"); exit(1)
    if kospi is None:
        print("[ERROR] KOSPI 없음"); exit(1)

    print(f"\n[F06] S&P500 상관관계 분석 ({len(ALL_INDICATORS)}개 지표)")
    a_sp500 = analyze_target("SP500", sp500)
    ok_sp   = sum(1 for v in a_sp500.values() if v.get("status") == "ok")
    print(f"  성공: {ok_sp}/{len(a_sp500)}개")

    print(f"\n[F07] 코스피 상관관계 분석 ({len(ALL_INDICATORS)}개 지표)")
    a_kospi = analyze_target("KOSPI", kospi)
    ok_ksp  = sum(1 for v in a_kospi.values() if v.get("status") == "ok")
    print(f"  성공: {ok_ksp}/{len(a_kospi)}개")

    print("\n[F08] 가중치 랭킹 생성")
    ranking = compute_weight_ranking(a_sp500, a_kospi)

    print("\n  === 가중치 랭킹 Top 10 ===")
    print(f"  {'#':>3} {'지표':22} {'SP500 r':>9} {'KOSPI r':>9} {'가중치':>8} {'유형':>10}")
    for r in ranking[:10]:
        sp_r  = f"{r['sp500_signed_r']:+.3f}{'*' if r['sp500_significant'] else ' '}" if r['sp500_signed_r'] is not None else "  N/A "
        ksp_r = f"{r['kospi_signed_r']:+.3f}{'*' if r['kospi_significant'] else ' '}" if r['kospi_signed_r'] is not None else "  N/A "
        print(f"  #{r['rank']:2d} {r['indicator']:22} {sp_r:>9} {ksp_r:>9} {r['combined_weight']:8.3f} {r['ind_type']:>10}")

    sig_sp  = sum(1 for r in ranking if r["sp500_significant"])
    sig_ksp = sum(1 for r in ranking if r["kospi_significant"])
    valid   = [r for r in ranking if r["sp500_significant"] or r["kospi_significant"]]
    print(f"\n  유의 지표: SP500={sig_sp}개, KOSPI={sig_ksp}개, 합계={len(valid)}개")

    results = {
        "generated_at":       datetime.now().isoformat(),
        "data_freshness":     {"start": None, "end": datetime.now().strftime("%Y-%m-%d")},
        "f06_sp500_analysis": a_sp500,
        "f07_kospi_analysis": a_kospi,
        "f08_weight_ranking": ranking,
        "summary": {
            "sp500_significant_count": sig_sp,
            "kospi_significant_count": sig_ksp,
            "valid_indicators":        len(valid),
            "top5": [r["indicator"] for r in ranking[:5]],
        }
    }

    out = PROC_DIR / "analysis_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n분석 결과 저장: {out}")

    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for f in fl["features"]:
        if f["id"] in ("F06", "F07", "F08"):
            f["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Analysis Agent v2 완료")
