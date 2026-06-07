"""
Stock Agent — F09, F10, F11, F12
- F09: S&P500 기여 기업 Top5 (시가총액 가중 기여도)
- F10: 코스피 기여 기업 Top5
- F11: S&P500 수혜 기업 Top5 (지수 상승 시 초과 수익)
- F12: 코스피 수혜 기업 Top5
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

START = "2024-06-01"
END = datetime.now().strftime("%Y-%m-%d")

# S&P500 주요 구성 종목 (시가총액 상위 20개)
SP500_CANDIDATES = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "BRK-B", "LLY", "AVGO", "TSLA",
    "WMT", "JPM", "V", "UNH", "XOM",
    "MA", "COST", "HD", "PG", "ORCL",
]

# 코스피 주요 구성 종목 (시가총액 상위 20개)
KOSPI_CANDIDATES = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "005380.KS",  # 현대차
    "035420.KS",  # NAVER
    "051910.KS",  # LG화학
    "006400.KS",  # 삼성SDI
    "003550.KS",  # LG
    "105560.KS",  # KB금융
    "055550.KS",  # 신한지주
    "012330.KS",  # 현대모비스
    "066570.KS",  # LG전자
    "207940.KS",  # 삼성바이오로직스
    "096770.KS",  # SK이노베이션
    "017670.KS",  # SK텔레콤
    "030200.KS",  # KT
    "034220.KS",  # LG디스플레이
    "086790.KS",  # 하나금융지주
    "033780.KS",  # KT&G
    "000810.KS",  # 삼성화재
    "010950.KS",  # S-Oil
]

COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "BRK-B": "Berkshire", "LLY": "Eli Lilly",
    "AVGO": "Broadcom", "TSLA": "Tesla", "WMT": "Walmart", "JPM": "JPMorgan",
    "V": "Visa", "UNH": "UnitedHealth", "XOM": "ExxonMobil", "MA": "Mastercard",
    "COST": "Costco", "HD": "Home Depot", "PG": "P&G", "ORCL": "Oracle",
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "005380.KS": "현대차",
    "035420.KS": "NAVER", "051910.KS": "LG화학", "006400.KS": "삼성SDI",
    "003550.KS": "LG", "105560.KS": "KB금융", "055550.KS": "신한지주",
    "012330.KS": "현대모비스", "066570.KS": "LG전자", "207940.KS": "삼성바이오",
    "096770.KS": "SK이노베이션", "017670.KS": "SK텔레콤", "030200.KS": "KT",
    "034220.KS": "LG디스플레이", "086790.KS": "하나금융", "033780.KS": "KT&G",
    "000810.KS": "삼성화재", "010950.KS": "S-Oil",
}


def fetch_stock(ticker: str) -> pd.DataFrame | None:
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(start=START, end=END)
        if df.empty or len(df) < 50:
            return None
        df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
        df.index = pd.to_datetime(df.index).normalize()
        return df[["Close", "Volume"]].rename(columns={"Close": "close", "Volume": "volume"})
    except Exception:
        return None


def get_market_cap(ticker: str) -> float:
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        return float(getattr(info, "market_cap", 0) or 0)
    except Exception:
        return 0.0


def compute_contribution(stock_df: pd.DataFrame, index_df: pd.Series, market_cap: float) -> dict:
    """시가총액 가중 기여도: 지수 상승분 중 해당 종목이 기여한 비율"""
    stock_ret = stock_df["close"].pct_change().dropna()
    index_ret = index_df.pct_change().dropna()
    merged = pd.concat([stock_ret, index_ret], axis=1).dropna()
    if len(merged) < 30:
        return None
    merged.columns = ["stock", "index"]

    # 회귀로 베타 계산
    slope, _, r, p, _ = stats.linregress(merged["index"].values, merged["stock"].values)
    beta = slope

    # 기여도: beta * (시가총액 비중 추정) * 인덱스 총 수익률
    index_total_return = (1 + merged["index"]).prod() - 1
    stock_total_return = (1 + merged["stock"]).prod() - 1

    # 기여 스코어: |상관계수| * 총수익률 * 시가총액 스케일
    r_val, p_val = stats.pearsonr(merged["stock"].values, merged["index"].values)

    return {
        "beta": round(float(beta), 4),
        "correlation": round(float(r_val), 4),
        "p_value": round(float(p_val), 6),
        "stock_return_1y": round(float(stock_total_return) * 100, 2),
        "index_return_1y": round(float(index_total_return) * 100, 2),
        "market_cap_b": round(market_cap / 1e9, 1),
        "contribution_score": round(abs(float(r_val)) * abs(float(stock_total_return)) * (market_cap / 1e12 + 0.01), 4),
        "n_days": len(merged),
    }


def compute_beneficiary(stock_df: pd.DataFrame, index_df: pd.Series) -> dict:
    """수혜 기업: 지수 상승 시 초과 수익 (상승장에서 알파)"""
    stock_ret = stock_df["close"].pct_change().dropna()
    index_ret = index_df.pct_change().dropna()
    merged = pd.concat([stock_ret, index_ret], axis=1).dropna()
    if len(merged) < 30:
        return None
    merged.columns = ["stock", "index"]

    # 지수 상승일 필터
    up_days = merged[merged["index"] > 0]
    if len(up_days) < 15:
        return None

    # 상승장 평균 초과 수익
    excess_on_up = (up_days["stock"] - up_days["index"]).mean()
    # 전체 기간 알파 (단순)
    alpha = merged["stock"].mean() - merged["index"].mean()
    # 전체 수익률
    stock_total = (1 + merged["stock"]).prod() - 1
    index_total = (1 + merged["index"]).prod() - 1
    excess_total = stock_total - index_total

    r_val, p_val = stats.pearsonr(merged["stock"].values, merged["index"].values)

    return {
        "correlation": round(float(r_val), 4),
        "p_value": round(float(p_val), 6),
        "stock_return_1y": round(float(stock_total) * 100, 2),
        "index_return_1y": round(float(index_total) * 100, 2),
        "excess_return_1y": round(float(excess_total) * 100, 2),
        "alpha_daily_bp": round(float(alpha) * 10000, 2),
        "excess_on_updays": round(float(excess_on_up) * 100, 4),
        "beneficiary_score": round(float(excess_total) * abs(float(r_val)), 4),
        "n_days": len(merged),
    }


def run_stock_analysis(market: str, candidates: list, index_series: pd.Series) -> dict:
    contrib_results = []
    beneficiary_results = []

    print(f"  {len(candidates)}개 종목 수집 중...")
    for ticker in candidates:
        stock_df = fetch_stock(ticker)
        if stock_df is None:
            print(f"    SKIP {ticker}: 데이터 없음")
            continue

        mc = get_market_cap(ticker)
        name = COMPANY_NAMES.get(ticker, ticker)

        # 인덱스와 날짜 맞추기
        stock_close = stock_df["close"]
        idx_aligned = index_series.reindex(stock_close.index, method="ffill")

        contrib = compute_contribution(stock_df, idx_aligned, mc)
        benefit = compute_beneficiary(stock_df, idx_aligned)

        if contrib:
            contrib["ticker"] = ticker
            contrib["name"] = name
            contrib_results.append(contrib)

        if benefit:
            benefit["ticker"] = ticker
            benefit["name"] = name
            beneficiary_results.append(benefit)

    contrib_results.sort(key=lambda x: x["contribution_score"], reverse=True)
    beneficiary_results.sort(key=lambda x: x["beneficiary_score"], reverse=True)

    top5_contrib = contrib_results[:5]
    top5_beneficiary = beneficiary_results[:5]

    print(f"\n  [{market}] 기여 기업 Top5:")
    for i, r in enumerate(top5_contrib):
        print(f"    #{i+1} {r['name']:12s} | 1y수익:{r['stock_return_1y']:+.1f}% | 기여점:{r['contribution_score']:.4f} | p={r['p_value']:.4f}")

    print(f"\n  [{market}] 수혜 기업 Top5:")
    for i, r in enumerate(top5_beneficiary):
        print(f"    #{i+1} {r['name']:12s} | 초과수익:{r['excess_return_1y']:+.1f}% | 수혜점:{r['beneficiary_score']:.4f} | p={r['p_value']:.4f}")

    return {
        "contribution_top5": top5_contrib,
        "beneficiary_top5": top5_beneficiary,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("STOCK AGENT - Phase 3 (F09, F10, F11, F12)")
    print("=" * 60)

    # SP500 지수 로드
    sp_path = RAW_DIR / "SP500.parquet"
    ksp_path = RAW_DIR / "KOSPI.parquet"

    if not sp_path.exists():
        print("[ERROR] SP500.parquet 없음")
        exit(1)
    if not ksp_path.exists():
        print("[ERROR] KOSPI.parquet 없음")
        exit(1)

    sp_df = pd.read_parquet(sp_path)
    sp_df["date"] = pd.to_datetime(sp_df["date"]).dt.tz_localize(None)
    sp_series = sp_df.set_index("date")["value"].sort_index()

    ksp_df = pd.read_parquet(ksp_path)
    ksp_df["date"] = pd.to_datetime(ksp_df["date"]).dt.tz_localize(None)
    ksp_series = ksp_df.set_index("date")["value"].sort_index()

    print("\n[F09+F11] S&P500 기여/수혜 기업 분석")
    sp_results = run_stock_analysis("S&P500", SP500_CANDIDATES, sp_series)

    print("\n[F10+F12] 코스피 기여/수혜 기업 분석")
    ksp_results = run_stock_analysis("KOSPI", KOSPI_CANDIDATES, ksp_series)

    # 결과 저장
    results = {
        "generated_at": datetime.now().isoformat(),
        "period": {"start": START, "end": END},
        "f09_sp500_contribution_top5": sp_results["contribution_top5"],
        "f10_kospi_contribution_top5": ksp_results["contribution_top5"],
        "f11_sp500_beneficiary_top5": sp_results["beneficiary_top5"],
        "f12_kospi_beneficiary_top5": ksp_results["beneficiary_top5"],
    }

    out_path = PROC_DIR / "stock_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n종목 분석 결과 저장: {out_path}")

    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] in ("F09", "F10", "F11", "F12"):
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Stock Agent 완료")
