"""
Analysis Agent — F06, F07, F08
- F06: 지표별 S&P500 상관관계 분석
- F07: 지표별 코스피 상관관계 분석
- F08: 가중치 랭킹 생성
"""
import utf8_setup  # noqa: F401

import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

INDICATORS = [
    "SP500", "NASDAQ100", "DOW", "KOSPI", "KOSDAQ", "NIKKEI225",
    "US10Y", "DXY", "WTI", "FED_ASSETS", "T10Y2Y", "HY_SPREAD",
    "VIX", "SKEW", "PUT_CALL", "CNN_FG", "MARKET_MOMENTUM", "MARKET_STRENGTH",
    "RSI14", "RSI_SIGNAL", "MA50", "MA200", "MA_SIGNAL", "BETA", "BBAND", "STOCH_RSI",
    "FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET",
]

TARGET_MAP = {
    "SP500": "SP500",
    "KOSPI": "KOSPI",
}


def load_indicator(name: str) -> pd.Series | None:
    path = RAW_DIR / f"{name}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").set_index("date")
        s = df["value"].resample("D").last().ffill()
        return s
    except Exception:
        return None


def compute_corr(x: pd.Series, y: pd.Series) -> dict:
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"pearson_r": None, "pearson_p": None, "spearman_r": None, "spearman_p": None, "n": len(merged)}
    x_vals = merged.iloc[:, 0].values
    y_vals = merged.iloc[:, 1].values
    pr, pp = stats.pearsonr(x_vals, y_vals)
    sr, sp = stats.spearmanr(x_vals, y_vals)
    return {
        "pearson_r": round(float(pr), 4),
        "pearson_p": round(float(pp), 6),
        "spearman_r": round(float(sr), 4),
        "spearman_p": round(float(sp), 6),
        "n": len(merged),
    }


def compute_lag_corr(x: pd.Series, y: pd.Series, max_lag: int = 5) -> dict:
    best = {"lag": 0, "r": 0.0}
    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            shifted = x
        elif lag > 0:
            shifted = x.shift(lag)
        else:
            shifted = x.shift(lag)
        merged = pd.concat([shifted, y], axis=1).dropna()
        if len(merged) < 20:
            continue
        r, _ = stats.pearsonr(merged.iloc[:, 0].values, merged.iloc[:, 1].values)
        if abs(r) > abs(best["r"]):
            best = {"lag": lag, "r": round(float(r), 4)}
    return best


def run_regression(x: pd.Series, y: pd.Series) -> dict:
    merged = pd.concat([x, y], axis=1).dropna()
    if len(merged) < 20:
        return {"slope": None, "intercept": None, "r2": None, "p": None}
    slope, intercept, r, p, se = stats.linregress(merged.iloc[:, 0].values, merged.iloc[:, 1].values)
    return {
        "slope": round(float(slope), 6),
        "intercept": round(float(intercept), 4),
        "r2": round(float(r**2), 4),
        "p": round(float(p), 6),
    }


def analyze_target(target_name: str, target_series: pd.Series) -> dict:
    results = {}
    target_ret = target_series.pct_change().dropna()

    for ind_name in INDICATORS:
        if ind_name == target_name:
            continue
        s = load_indicator(ind_name)
        if s is None:
            results[ind_name] = {"status": "FAILED", "reason": "parquet 없음"}
            continue

        s_ret = s.pct_change().dropna()

        corr = compute_corr(s_ret, target_ret)
        lag = compute_lag_corr(s_ret, target_ret)
        reg = run_regression(s_ret, target_ret)

        results[ind_name] = {
            "status": "ok",
            "corr": corr,
            "best_lag": lag,
            "regression": reg,
        }

    return results


def compute_weight_ranking(analysis_sp500: dict, analysis_kospi: dict) -> list:
    rows = []
    all_inds = set(list(analysis_sp500.keys()) + list(analysis_kospi.keys()))

    for ind in all_inds:
        sp = analysis_sp500.get(ind, {})
        ksp = analysis_kospi.get(ind, {})

        sp_r = abs(sp.get("corr", {}).get("pearson_r") or 0)
        sp_p = sp.get("corr", {}).get("pearson_p")
        ksp_r = abs(ksp.get("corr", {}).get("pearson_r") or 0)
        ksp_p = ksp.get("corr", {}).get("pearson_p")

        sp_r2 = sp.get("regression", {}).get("r2") or 0
        ksp_r2 = ksp.get("regression", {}).get("r2") or 0

        # 가중치: |pearson_r| * 0.5 + r2 * 0.5 (유의한 경우만)
        def weighted(r, p, r2):
            if p is None or p >= 0.05:
                return 0.0
            return r * 0.5 + r2 * 0.5

        sp_weight = weighted(sp_r, sp_p, sp_r2)
        ksp_weight = weighted(ksp_r, ksp_p, ksp_r2)
        combined = (sp_weight + ksp_weight) / 2

        rows.append({
            "indicator": ind,
            "sp500_r": round(sp_r, 4),
            "sp500_p": round(sp_p, 6) if sp_p else None,
            "sp500_r2": round(sp_r2, 4),
            "sp500_weight": round(sp_weight, 4),
            "kospi_r": round(ksp_r, 4),
            "kospi_p": round(ksp_p, 6) if ksp_p else None,
            "kospi_r2": round(ksp_r2, 4),
            "kospi_weight": round(ksp_weight, 4),
            "combined_weight": round(combined, 4),
            "sp500_significant": sp_p is not None and sp_p < 0.05,
            "kospi_significant": ksp_p is not None and ksp_p < 0.05,
        })

    rows.sort(key=lambda x: x["combined_weight"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return rows


if __name__ == "__main__":
    print("=" * 60)
    print("ANALYSIS AGENT - Phase 3 (F06, F07, F08)")
    print("=" * 60)

    sp500 = load_indicator("SP500")
    kospi = load_indicator("KOSPI")

    if sp500 is None:
        print("[ERROR] SP500 데이터 없음 — 분석 불가")
        exit(1)
    if kospi is None:
        print("[ERROR] KOSPI 데이터 없음 — 분석 불가")
        exit(1)

    print(f"\n[F06] S&P500 상관관계 분석 ({len(INDICATORS)-1}개 지표)")
    analysis_sp500 = analyze_target("SP500", sp500)
    sp_ok = sum(1 for v in analysis_sp500.values() if v.get("status") == "ok")
    print(f"  완료: {sp_ok}/{len(analysis_sp500)}개 성공")

    print(f"\n[F07] 코스피 상관관계 분석 ({len(INDICATORS)-1}개 지표)")
    analysis_kospi = analyze_target("KOSPI", kospi)
    ksp_ok = sum(1 for v in analysis_kospi.values() if v.get("status") == "ok")
    print(f"  완료: {ksp_ok}/{len(analysis_kospi)}개 성공")

    print("\n[F08] 가중치 랭킹 생성")
    ranking = compute_weight_ranking(analysis_sp500, analysis_kospi)

    print("\n  === 가중치 랭킹 Top 10 ===")
    for r in ranking[:10]:
        sig_sp = "(*)" if r["sp500_significant"] else "   "
        sig_ksp = "(*)" if r["kospi_significant"] else "   "
        print(f"  #{r['rank']:2d} {r['indicator']:20s} | SP500:{r['sp500_r']:.3f}{sig_sp} | KOSPI:{r['kospi_r']:.3f}{sig_ksp} | 가중:{r['combined_weight']:.3f}")

    # 결과 저장
    results = {
        "generated_at": datetime.now().isoformat(),
        "f06_sp500_analysis": analysis_sp500,
        "f07_kospi_analysis": analysis_kospi,
        "f08_weight_ranking": ranking,
        "summary": {
            "sp500_significant_count": sum(1 for r in ranking if r["sp500_significant"]),
            "kospi_significant_count": sum(1 for r in ranking if r["kospi_significant"]),
            "top5": [r["indicator"] for r in ranking[:5]],
        }
    }

    out_path = PROC_DIR / "analysis_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n분석 결과 저장: {out_path}")

    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] in ("F06", "F07", "F08"):
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Analysis Agent 완료")
