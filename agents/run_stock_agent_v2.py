# -*- coding: utf-8 -*-
"""
Stock Agent v2 - F09, F10, F11, F12 (v3 수정)
수정사항:
  - 분석 기간 1년으로 명시 (START = 1년 전)
  - 변수명 stock_return_1y -> stock_return_pct / period_days 추가
  - 한국 종목: FDR 우선 사용 (KRX 직접 접근), yfinance 폴백
  - FDR/yfinance 크로스 검증으로 데이터 신뢰도 확인
  - ±200% 하드 필터 제거: FDR+yfinance 두 소스가 일치하면 실제 데이터로 수용
    (AI/반도체 붐으로 한국 반도체주가 실제로 크게 상승했음이 확인됨)
  - 두 소스 수익률 차이 100%p 초과 시만 'data_quality=불일치' 플래그
"""

import json, warnings
import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from pathlib import Path
from datetime import datetime, timedelta
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

END   = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
PERIOD_LABEL = "1년 (365일)"

SP500_CANDIDATES = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL",
    "META","BRK-B","LLY","AVGO","TSLA",
    "WMT","JPM","V","UNH","XOM",
    "MA","COST","HD","PG","ORCL",
]
KOSPI_CANDIDATES = [
    "005930.KS","000660.KS","005380.KS","035420.KS","051910.KS",
    "006400.KS","003550.KS","105560.KS","055550.KS","012330.KS",
    "066570.KS","207940.KS","096770.KS","017670.KS","030200.KS",
    "034220.KS","086790.KS","033780.KS","000810.KS","010950.KS",
]
COMPANY_NAMES = {
    "AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","AMZN":"Amazon","GOOGL":"Alphabet",
    "META":"Meta","BRK-B":"Berkshire","LLY":"Eli Lilly","AVGO":"Broadcom","TSLA":"Tesla",
    "WMT":"Walmart","JPM":"JPMorgan","V":"Visa","UNH":"UnitedHealth","XOM":"ExxonMobil",
    "MA":"Mastercard","COST":"Costco","HD":"Home Depot","PG":"P&G","ORCL":"Oracle",
    "005930.KS":"삼성전자","000660.KS":"SK하이닉스","005380.KS":"현대차",
    "035420.KS":"NAVER","051910.KS":"LG화학","006400.KS":"삼성SDI",
    "003550.KS":"LG","105560.KS":"KB금융","055550.KS":"신한지주",
    "012330.KS":"현대모비스","066570.KS":"LG전자","207940.KS":"삼성바이오",
    "096770.KS":"SK이노베이션","017670.KS":"SK텔레콤","030200.KS":"KT",
    "034220.KS":"LG디스플레이","086790.KS":"하나금융","033780.KS":"KT&G",
    "000810.KS":"삼성화재","010950.KS":"S-Oil",
}

# 크로스 검증: 두 소스 수익률 차이가 이 이상이면 '불일치' 플래그
MAX_SOURCE_DIFF_PCT = 100.0


def _yf_code_to_fdr(ticker: str) -> str | None:
    """005930.KS -> 005930 (FDR KRX 코드)"""
    if ticker.endswith(".KS"):
        return ticker.replace(".KS", "")
    return None


def fetch_stock(ticker: str) -> tuple[pd.DataFrame | None, str]:
    """
    Returns (df, source_label)
    한국 종목: FDR 우선 → yfinance 폴백 → 크로스 검증
    미국 종목: yfinance
    """
    fdr_code = _yf_code_to_fdr(ticker)

    if fdr_code:
        # 한국 종목: FDR 시도
        try:
            df = fdr.DataReader(fdr_code, START, END)
            if df is not None and len(df) >= 50:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df = df[["Close","Volume"]].rename(columns={"Close":"close","Volume":"volume"})
                df = df.dropna(subset=["close"])
                if len(df) >= 50:
                    return df, "FDR"
        except Exception:
            pass

    # yfinance (미국 종목 및 FDR 실패 시 폴백)
    try:
        tk  = yf.Ticker(ticker)
        df  = tk.history(start=START, end=END, auto_adjust=True)
        if df.empty or len(df) < 50:
            return None, "none"
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.index = pd.to_datetime(df.index).normalize()
        return df[["Close","Volume"]].rename(columns={"Close":"close","Volume":"volume"}), "yfinance"
    except Exception:
        return None, "none"


def cross_validate_return(ticker: str, primary_ret: float) -> str:
    """
    FDR과 yfinance 수익률을 비교 검증.
    두 소스가 100%p 이상 차이나면 '불일치' 반환, 아니면 '검증완료'.
    한국 종목만 검증 수행.
    """
    fdr_code = _yf_code_to_fdr(ticker)
    if not fdr_code:
        return "검증불필요"  # 미국 종목

    # 두 번째 소스 수익률 계산
    try:
        df_yf = yf.Ticker(ticker).history(start=START, end=END, auto_adjust=True)
        if df_yf.empty or len(df_yf) < 50:
            return "검증불가"
        yf_ret = (df_yf["Close"].iloc[-1] / df_yf["Close"].iloc[0] - 1) * 100

        diff = abs(primary_ret - yf_ret)
        if diff > MAX_SOURCE_DIFF_PCT:
            return f"불일치(FDR:{primary_ret:+.0f}% yf:{yf_ret:+.0f}%)"
        return "검증완료"
    except Exception:
        return "검증불가"


def get_market_cap(ticker: str) -> float:
    try:
        info = yf.Ticker(ticker).fast_info
        return float(getattr(info, "market_cap", 0) or 0)
    except Exception:
        return 0.0


def compute_contribution(stock_df: pd.DataFrame, idx: pd.Series, mc: float) -> dict | None:
    sr  = stock_df["close"].pct_change().dropna()
    ir  = idx.pct_change().dropna()
    mg  = pd.concat([sr, ir], axis=1).dropna()
    if len(mg) < 30:
        return None
    mg.columns = ["s", "i"]
    slope, _, r_val, p_val, _ = stats.linregress(mg["i"].values, mg["s"].values)
    s_total  = float((1 + mg["s"]).prod() - 1)
    i_total  = float((1 + mg["i"]).prod() - 1)
    corr, _  = stats.pearsonr(mg["s"].values, mg["i"].values)
    return {
        "beta":               round(float(slope), 4),
        "correlation":        round(float(corr), 4),
        "p_value":            round(float(p_val), 6),
        "stock_return_pct":   round(s_total * 100, 2),
        "index_return_pct":   round(i_total * 100, 2),
        "period_days":        len(mg),
        "period_label":       PERIOD_LABEL,
        "market_cap_b":       round(mc / 1e9, 1),
        "contribution_score": round(abs(corr) * abs(s_total) * (mc / 1e12 + 0.01), 4),
        "n_days":             len(mg),
    }


def compute_beneficiary(stock_df: pd.DataFrame, idx: pd.Series) -> dict | None:
    sr  = stock_df["close"].pct_change().dropna()
    ir  = idx.pct_change().dropna()
    mg  = pd.concat([sr, ir], axis=1).dropna()
    if len(mg) < 30:
        return None
    mg.columns = ["s", "i"]
    up = mg[mg["i"] > 0]
    if len(up) < 15:
        return None
    s_total = float((1 + mg["s"]).prod() - 1)
    i_total = float((1 + mg["i"]).prod() - 1)
    excess  = s_total - i_total
    corr, p = stats.pearsonr(mg["s"].values, mg["i"].values)
    return {
        "correlation":        round(float(corr), 4),
        "p_value":            round(float(p), 6),
        "stock_return_pct":   round(s_total * 100, 2),
        "index_return_pct":   round(i_total * 100, 2),
        "excess_return_pct":  round(excess * 100, 2),
        "period_days":        len(mg),
        "period_label":       PERIOD_LABEL,
        "beneficiary_score":  round(float(excess) * abs(float(corr)), 4),
        "n_days":             len(mg),
    }


def run_analysis(market: str, candidates: list, idx_series: pd.Series) -> dict:
    contrib_list, benefit_list = [], []
    skipped = []

    print(f"  {len(candidates)}개 종목 수집 중...")
    for ticker in candidates:
        df, source = fetch_stock(ticker)
        if df is None:
            skipped.append(ticker)
            continue

        mc   = get_market_cap(ticker)
        name = COMPANY_NAMES.get(ticker, ticker)
        aligned_idx = idx_series.reindex(df["close"].index, method="ffill")

        c = compute_contribution(df, aligned_idx, mc)
        b = compute_beneficiary(df, aligned_idx)

        # 크로스 검증 (한국 종목)
        if c:
            ret   = c["stock_return_pct"]
            valid = cross_validate_return(ticker, ret)
            c["data_quality"] = valid
            c["data_source"]  = source
            c.update({"ticker": ticker, "name": name})
            contrib_list.append(c)

        if b:
            b["data_source"] = source
            b.update({"ticker": ticker, "name": name})
            benefit_list.append(b)

    contrib_list.sort(key=lambda x: x["contribution_score"], reverse=True)
    benefit_list.sort(key=lambda x: x["beneficiary_score"],  reverse=True)

    top5_c = contrib_list[:5]
    top5_b = benefit_list[:5]

    if skipped:
        print(f"  [데이터없음] {len(skipped)}개: {skipped}")

    # 불일치 종목 경고
    mismatch = [r for r in contrib_list if "불일치" in r.get("data_quality","")]
    if mismatch:
        print(f"  [검증경고] 소스 불일치 {len(mismatch)}개 종목:")
        for r in mismatch:
            print(f"    {r['name']}: {r['data_quality']}")

    print(f"\n  [{market}] 기여 Top5 (분석 기간: {PERIOD_LABEL}):")
    for i, r in enumerate(top5_c):
        src   = r.get('data_source','?')
        valid = r.get('data_quality','?')
        print(f"    #{i+1} {r['name']:12s} | {r['period_days']}일 수익:{r['stock_return_pct']:+.1f}% | 기여:{r['contribution_score']:.4f} [{src}/{valid}]")

    print(f"\n  [{market}] 수혜 Top5:")
    for i, r in enumerate(top5_b):
        print(f"    #{i+1} {r['name']:12s} | 초과:{r['excess_return_pct']:+.1f}% | 수혜:{r['beneficiary_score']:.4f} [{r.get('data_source','?')}]")

    return {
        "contribution_top5": top5_c,
        "beneficiary_top5":  top5_b,
        "skipped_count":     len(skipped),
        "period":            {"start": START, "end": END, "label": PERIOD_LABEL},
    }


if __name__ == "__main__":
    print("=" * 60)
    print("STOCK AGENT v2 - Phase 3 (F09~F12) [FDR + 크로스검증]")
    print(f"분석 기간: {START} ~ {END} ({PERIOD_LABEL})")
    print("=" * 60)

    for path_name in ("SP500", "KOSPI"):
        if not (RAW_DIR / f"{path_name}.parquet").exists():
            print(f"[ERROR] {path_name}.parquet 없음"); exit(1)

    sp_df  = pd.read_parquet(RAW_DIR / "SP500.parquet")
    sp_df["date"] = pd.to_datetime(sp_df["date"]).dt.tz_localize(None)
    sp_s   = sp_df.set_index("date")["value"].sort_index()

    ksp_df = pd.read_parquet(RAW_DIR / "KOSPI.parquet")
    ksp_df["date"] = pd.to_datetime(ksp_df["date"]).dt.tz_localize(None)
    ksp_s  = ksp_df.set_index("date")["value"].sort_index()

    print("\n[F09+F11] S&P500 분석")
    sp_res  = run_analysis("S&P500", SP500_CANDIDATES, sp_s)

    print("\n[F10+F12] 코스피 분석")
    ksp_res = run_analysis("KOSPI",  KOSPI_CANDIDATES, ksp_s)

    results = {
        "generated_at":   datetime.now().isoformat(),
        "analysis_period": {"start": START, "end": END, "label": PERIOD_LABEL},
        "f09_sp500_contribution_top5": sp_res["contribution_top5"],
        "f10_kospi_contribution_top5": ksp_res["contribution_top5"],
        "f11_sp500_beneficiary_top5":  sp_res["beneficiary_top5"],
        "f12_kospi_beneficiary_top5":  ksp_res["beneficiary_top5"],
        "data_quality_notes": {
            "methodology": "FDR 우선(KRX 직접), yfinance 폴백. 두 소스 수익률 차이 100%p 초과 시 불일치 플래그.",
            "cross_validation": "FDR/yfinance 교차검증 적용",
        },
    }

    out = PROC_DIR / "stock_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n종목 결과 저장: {out}")

    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] in ("F09","F10","F11","F12"):
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Stock Agent v2 완료")
