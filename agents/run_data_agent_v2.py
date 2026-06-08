# -*- coding: utf-8 -*-
"""
Data Agent v2 - F01~F05 (개선판)
수정사항:
  - US10Y: GS10(월별) -> DGS10(일별)
  - CNN Fear&Greed: alternative.me API (공개, 무료)
  - MARKET_MOMENTUM: rolling(252) -> rolling(63, min_periods=20)
  - pykrx 대안: FDR 수급 데이터 시도
  - 인코딩 명시 (utf-8)
"""

import os, sys, json, httpx, warnings
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# 1년치 (최근 365일)
END   = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - pd.DateOffset(days=400)).strftime("%Y-%m-%d")

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
RESULTS = {}


# ── 공통 유틸 ──────────────────────────────────────────────────────────────

def save_parquet(df: pd.DataFrame, name: str, source: str) -> bool:
    if df is None or df.empty:
        return fail(name, "DataFrame 비어 있음") or False
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date", "Date": "date"})
    if "value" not in df.columns:
        cols = [c for c in df.columns if c != "date"]
        df = df.rename(columns={cols[0]: "value"}) if cols else None
        if df is None:
            return fail(name, "value 컬럼 없음") or False
    df = df[["date", "value", "source"] if "source" in df.columns else ["date", "value"]].copy()
    df["source"] = source
    df["date"]  = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[["date", "value", "source"]].dropna(subset=["value"])
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["value"])
    df = df.sort_values("date").reset_index(drop=True)
    path = RAW_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    # 이전 실패 마커 삭제 (성공 시 _FAILED.txt 잔류 방지)
    failed_path = RAW_DIR / f"{name}_FAILED.txt"
    if failed_path.exists():
        failed_path.unlink()
    RESULTS[name] = {"status": "ok", "rows": len(df), "source": source}
    print(f"  [OK] {name}: {len(df)}rows ({source})")
    return True


def fail(name: str, reason: str) -> None:
    path = RAW_DIR / f"{name}_FAILED.txt"
    path.write_text(reason, encoding="utf-8")
    RESULTS[name] = {"status": "FAILED", "reason": reason}
    print(f"  [FAIL] {name}: {reason[:100]}")


def fred_series(series_id: str) -> pd.DataFrame:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "observation_start": START,
        "observation_end": END,
        "api_key": FRED_API_KEY,
        "file_type": "json",
    }
    r = httpx.get(url, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    df = pd.DataFrame(obs)[["date", "value"]]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"])


# ── F01: 시장 지수 6개 (FDR) ───────────────────────────────────────────────

def collect_f01():
    print("\n[F01] 시장 지수 6개 (FDR)")
    import FinanceDataReader as fdr

    tickers = {
        "SP500":    "US500",
        "NASDAQ100":"QQQ",
        "DOW":      "^DJI",
        "KOSPI":    "KS11",
        "KOSDAQ":   "KQ11",
        "NIKKEI225":"^N225",
    }
    for name, ticker in tickers.items():
        try:
            df = fdr.DataReader(ticker, start=START, end=END)
            if df.empty:
                fail(name, f"FDR {ticker}: 빈 데이터"); continue
            col = "Close" if "Close" in df.columns else df.columns[0]
            out = df[[col]].rename(columns={col: "value"}).reset_index()
            out = out.rename(columns={"Date": "date"})
            save_parquet(out, name, f"FDR:{ticker}")
        except Exception as e:
            fail(name, str(e))


# ── F02: 매크로 지표 6개 (FRED + yfinance fallback) ────────────────────────

def _yf_macro_fallback(name: str) -> bool:
    """FRED 실패 시 yfinance로 매크로 지표 수집. 성공 시 True 반환."""
    import yfinance as yf
    yf_map = {
        "WTI":   ("CL=F",      1.0),    # 원유 선물 ($/barrel)
        "DXY":   ("DX-Y.NYB",  1.0),    # 달러인덱스
        "US10Y": ("^TNX",      1.0),    # 10년물 금리 (%, FRED와 단위 동일)
        "T10Y2Y": None,                  # ^TNX - ^IRX 계산
    }
    if name not in yf_map:
        return False
    try:
        entry = yf_map[name]
        if name == "T10Y2Y":
            t10 = yf.Ticker("^TNX").history(start=START, end=END)[["Close"]]
            t2  = yf.Ticker("^IRX").history(start=START, end=END)[["Close"]]
            merged = t10.join(t2, how="inner", lsuffix="_10", rsuffix="_2")
            out = merged.reset_index().rename(columns={"Date": "date"})
            out["value"] = out["Close_10"] - out["Close_2"]
            out = out[["date", "value"]].dropna()
        else:
            ticker, scale = entry
            hist = yf.Ticker(ticker).history(start=START, end=END)[["Close"]]
            out = hist.reset_index().rename(columns={"Date": "date", "Close": "value"})
            out["value"] = out["value"] * scale
            out = out[["date", "value"]].dropna()
        if out.empty:
            return False
        save_parquet(out, name, f"yfinance:{yf_map[name][0] if entry else 'computed'}")
        return True
    except Exception:
        return False


def collect_f02():
    print("\n[F02] 매크로 지표 6개 (FRED API + yfinance fallback)")
    series_map = {
        "US10Y":      "DGS10",
        "DXY":        "DTWEXBGS",
        "WTI":        "DCOILWTICO",
        "FED_ASSETS": "WALCL",
        "T10Y2Y":     "T10Y2Y",
        "HY_SPREAD":  "BAMLH0A0HYM2",
    }
    for name, sid in series_map.items():
        try:
            df = fred_series(sid)
            save_parquet(df, name, f"FRED:{sid}")
        except Exception as e:
            if _yf_macro_fallback(name):
                print(f"  [{name}] FRED 실패 → yfinance fallback 성공")
            else:
                fail(name, f"FRED {sid}: {e}")


# ── F03: 시장 심리 지표 ────────────────────────────────────────────────────

def collect_f03():
    print("\n[F03] 시장 심리 지표 수집")
    import FinanceDataReader as fdr

    # VIX
    try:
        df = fdr.DataReader("^VIX", start=START, end=END)
        col = "Close" if "Close" in df.columns else df.columns[0]
        out = df[[col]].rename(columns={col: "value"}).reset_index().rename(columns={"Date": "date"})
        save_parquet(out, "VIX", "FDR:^VIX")
    except Exception as e:
        try:
            df = fred_series("VIXCLS")
            save_parquet(df, "VIX", "FRED:VIXCLS")
        except Exception as e2:
            fail("VIX", f"FDR:{e} | FRED:{e2}")

    # SKEW
    try:
        df = fred_series("SKEW")
        save_parquet(df, "SKEW", "FRED:SKEW")
    except Exception as e:
        try:
            import yfinance as yf
            df = yf.Ticker("^SKEW").history(start=START, end=END)[["Close"]].reset_index()
            df = df.rename(columns={"Date": "date", "Close": "value"})
            save_parquet(df, "SKEW", "yfinance:^SKEW")
        except Exception as e2:
            fail("SKEW", f"FRED:{e} | yf:{e2}")

    # Put/Call 비율 - yfinance ^PCALL 대신 FRED DPCREDIT 또는 산출 스킵
    try:
        # CBOE Total Put/Call: 공개 소스 없음 -> FAILED 처리
        fail("PUT_CALL", "공개 API 없음 - CBOE 직접 접근 필요 (데이터 없음 처리)")
    except Exception:
        pass

    # CNN Fear & Greed -> Fix: alternative.me API (공개, 무료)
    try:
        url = "https://api.alternative.me/fng/?limit=400&format=json"
        r = httpx.get(url, timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise ValueError("응답 데이터 없음")
        rows = [{"date": pd.to_datetime(int(d["timestamp"]), unit="s"), "value": float(d["value"])}
                for d in data]
        df = pd.DataFrame(rows)
        df = df[df["date"] >= pd.Timestamp(START)]
        save_parquet(df, "CNN_FG", "alternative.me:FnG")
    except Exception as e:
        fail("CNN_FG", f"alternative.me: {e}")

    # 시장 모멘텀 - Fix: rolling(63) min_periods=20
    try:
        sp_path = RAW_DIR / "SP500.parquet"
        if sp_path.exists():
            sp = pd.read_parquet(sp_path)
            sp["date"] = pd.to_datetime(sp["date"]).dt.tz_localize(None)
            sp = sp.sort_values("date")
            sp["momentum"] = sp["value"] / sp["value"].rolling(63, min_periods=20).max()
            out = sp[["date", "momentum"]].rename(columns={"momentum": "value"}).dropna()
            save_parquet(out, "MARKET_MOMENTUM", "CALC:SP500_13w_momentum")
        else:
            fail("MARKET_MOMENTUM", "SP500.parquet 없음")
    except Exception as e:
        fail("MARKET_MOMENTUM", str(e))

    # 시장 강도
    try:
        adv = fred_series("ADVN")
        dec = fred_series("DECN")
        adv = adv.rename(columns={"value": "adv"})
        dec = dec.rename(columns={"value": "dec"})
        merged = pd.merge(adv, dec, on="date")
        merged["value"] = merged["adv"].astype(float) / (merged["adv"].astype(float) + merged["dec"].astype(float))
        save_parquet(merged[["date", "value"]], "MARKET_STRENGTH", "FRED:ADVN/DECN")
    except Exception as e:
        sp_path = RAW_DIR / "SP500.parquet"
        if sp_path.exists():
            sp = pd.read_parquet(sp_path)
            sp["date"] = pd.to_datetime(sp["date"]).dt.tz_localize(None)
            sp = sp.sort_values("date").set_index("date")
            delta = sp["value"].diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
            out   = rsi.reset_index(); out.columns = ["date", "value"]
            save_parquet(out, "MARKET_STRENGTH", "CALC:SP500_RSI14_proxy")
        else:
            fail("MARKET_STRENGTH", f"FRED:{e} | SP500 없음")


# ── F04: 기술적 지표 8개 ──────────────────────────────────────────────────

def rsi_calc(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def collect_f04():
    print("\n[F04] 기술적 지표 8개 산출")
    sp_path = RAW_DIR / "SP500.parquet"
    if not sp_path.exists():
        for n in ["RSI14","RSI_SIGNAL","MA50","MA200","MA_SIGNAL","BETA","BBAND","STOCH_RSI"]:
            fail(n, "SP500.parquet 없음")
        return

    sp = pd.read_parquet(sp_path)
    sp["date"] = pd.to_datetime(sp["date"]).dt.tz_localize(None)
    sp = sp.sort_values("date").set_index("date")
    price = sp["value"]

    specs = [
        ("RSI14",      lambda p: rsi_calc(p, 14),                     "CALC:RSI14"),
        ("RSI_SIGNAL", lambda p: rsi_calc(p, 14).apply(
                        lambda v: 1.0 if v > 70 else (-1.0 if v < 30 else 0.0)),
                        "CALC:RSI_SIG"),
        ("MA50",       lambda p: p.rolling(50).mean(),                "CALC:MA50"),
        ("MA200",      lambda p: p.rolling(200).mean(),               "CALC:MA200"),
        ("MA_SIGNAL",  lambda p: (p.rolling(50).mean() > p.rolling(200).mean()).astype(float) * 2 - 1,
                        "CALC:MA_SIG"),
        ("BBAND",      lambda p: (p - (p.rolling(20).mean() - 2*p.rolling(20).std()))
                        / ((p.rolling(20).mean() + 2*p.rolling(20).std())
                        - (p.rolling(20).mean() - 2*p.rolling(20).std()) + 1e-10),
                        "CALC:BBAND_pctB"),
    ]
    for name, fn, src in specs:
        try:
            s = fn(price).dropna()
            df = s.reset_index(); df.columns = ["date", "value"]
            save_parquet(df, name, src)
        except Exception as e:
            fail(name, str(e))

    # Beta (KOSPI vs SP500)
    try:
        ksp_path = RAW_DIR / "KOSPI.parquet"
        if ksp_path.exists():
            ksp = pd.read_parquet(ksp_path)
            ksp["date"] = pd.to_datetime(ksp["date"]).dt.tz_localize(None)
            ksp = ksp.set_index("date")["value"]
            merged = pd.concat([price, ksp], axis=1).dropna()
            merged.columns = ["sp", "ksp"]
            ret_sp  = merged["sp"].pct_change().dropna()
            ret_ksp = merged["ksp"].pct_change().dropna()
            al = pd.concat([ret_sp, ret_ksp], axis=1).dropna()
            al.columns = ["sp", "ksp"]
            beta = al["ksp"].rolling(60).cov(al["sp"]) / al["sp"].rolling(60).var()
            df = beta.dropna().reset_index(); df.columns = ["date", "value"]
            save_parquet(df, "BETA", "CALC:KOSPI_BETA_60d")
        else:
            fail("BETA", "KOSPI.parquet 없음")
    except Exception as e:
        fail("BETA", str(e))

    # Stochastic RSI
    try:
        r  = rsi_calc(price, 14)
        lo = r.rolling(14).min(); hi = r.rolling(14).max()
        sr = (r - lo) / (hi - lo + 1e-10)
        df = sr.dropna().reset_index(); df.columns = ["date", "value"]
        save_parquet(df, "STOCH_RSI", "CALC:STOCH_RSI")
    except Exception as e:
        fail("STOCH_RSI", str(e))


# ── F05: 수급 (pykrx KRX 로그인) ──────────────────────────────────────────

def collect_f05():
    print("\n[F05] 수급 3개 수집 (pykrx KRX 로그인)")

    KRX_ID = os.getenv("KRX_ID", "")
    KRX_PW = os.getenv("KRX_PW", "")

    if not KRX_ID or not KRX_PW:
        for name in ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]:
            fail(name, "KRX_ID/KRX_PW 환경변수 미등록 - .env에 추가 필요")
        return

    try:
        from pykrx import stock as pykrx_stock
        start_str = START.replace("-", "")
        end_str   = END.replace("-", "")

        df = pykrx_stock.get_market_trading_value_by_date(start_str, end_str, "KOSPI")

        if df is None or df.empty:
            for name in ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]:
                fail(name, "pykrx 응답 비어있음")
            return

        # 인덱스 정리
        if df.index.name in ("날짜", "date", None):
            df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "date"
        print(f"  수신 컬럼: {df.columns.tolist()}")

        # 컬럼 매핑 (KRX 반환 컬럼: 기관합계, 개인, 외국인합계)
        col_map = {
            "FOREIGN_NET":     ["외국인합계", "외국인", "foreign"],
            "INSTITUTION_NET": ["기관합계",   "기관",   "institution"],
            "INDIVIDUAL_NET":  ["개인",        "individual", "retail"],
        }

        for target, keywords in col_map.items():
            matched = next(
                (c for c in df.columns if any(kw in str(c) for kw in keywords)),
                None
            )
            if matched:
                out = df[[matched]].rename(columns={matched: "value"}).reset_index()
                # 단위: 원 → 억원 (가독성)
                out["value"] = out["value"] / 1e8
                save_parquet(out, target, "pykrx:KOSPI")
                print(f"  {target}: {matched} → 저장 완료 ({len(out)}행, 단위:억원)")
            else:
                fail(target, f"컬럼 매핑 실패. 수신 컬럼: {list(df.columns)}")

    except Exception as e:
        print(f"  pykrx 오류: {e}")
        for name in ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]:
            fail(name, f"pykrx 예외: {str(e)[:60]}")


# ── 메인 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("DATA AGENT v2 - Phase 2 (F01~F05)")
    print(f"수집 기간: {START} ~ {END}")
    print("=" * 60)

    collect_f01()
    collect_f02()
    collect_f03()
    collect_f04()
    collect_f05()

    ok     = [k for k, v in RESULTS.items() if v["status"] == "ok"]
    failed = [k for k, v in RESULTS.items() if v["status"] == "FAILED"]

    print("\n" + "=" * 60)
    print(f"DATA AGENT v2 완료: 성공 {len(ok)}/{len(RESULTS)}개")
    if failed:
        print(f"실패: {failed}")

    # ── Done Criteria 자체검증 (exit(1) on failure) ─────────────
    import sys as _sys

    F01_OK = all(k in ok for k in ["SP500","NASDAQ100","DOW","KOSPI","KOSDAQ","NIKKEI225"])
    F02_OK = all(k in ok for k in ["US10Y","DXY","WTI","FED_ASSETS","T10Y2Y","HY_SPREAD"])
    # F03: VIX 필수 + 심리 지표 최소 4개 (PUT_CALL 영구 수집불가 허용)
    F03_CORE = all(k in ok for k in ["VIX","MARKET_MOMENTUM","MARKET_STRENGTH"])
    F03_OK   = F03_CORE and ("SKEW" in ok or "CNN_FG" in ok)
    # F04: 핵심 기술 지표 4개 필수 + 전체 6개 이상
    F04_CORE = all(k in ok for k in ["RSI14","MA50","MA200","MA_SIGNAL"])
    F04_OK   = F04_CORE and sum(1 for k in ["RSI14","RSI_SIGNAL","MA50","MA200","MA_SIGNAL","BBAND","BETA","STOCH_RSI"] if k in ok) >= 6
    # F05: 수급 3개 전원 필수
    F05_OK   = all(k in ok for k in ["FOREIGN_NET","INSTITUTION_NET","INDIVIDUAL_NET"])
    TOTAL_MIN = 22

    done_checks = {
        "DC-1 F01 시장지수 6/6":       F01_OK,
        "DC-2 F02 매크로 6/6":         F02_OK,
        "DC-3 F03 심리 VIX+핵심4개+":  F03_OK,
        "DC-4 F04 기술 핵심4개+6개+":  F04_OK,
        "DC-5 F05 수급 3/3":           F05_OK,
        f"DC-6 전체 ≥{TOTAL_MIN}개":   len(ok) >= TOTAL_MIN,
    }

    print("\n[Done Criteria] 자체검증:")
    hard_fails = []
    for check, passed in done_checks.items():
        print(f"  {'✓' if passed else '✗'} {check}")
        if not passed:
            hard_fails.append(check)

    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    f_done = {
        "F01": F01_OK, "F02": F02_OK, "F03": F03_OK,
        "F04": F04_OK, "F05": F05_OK,
    }
    for feat in fl["features"]:
        if feat["id"] in f_done:
            feat["status"] = "done" if f_done[feat["id"]] else "partial"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    # 결과 저장
    (BASE_DIR / "data" / "collection_report_v2.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if hard_fails:
        print(f"\n[FAIL] Done Criteria 미충족 — 파이프라인 중단: {hard_fails}")
        _sys.exit(1)
    print(f"\n[PASS] Done Criteria 전항목 통과 ({len(ok)}/{len(RESULTS)}개 수집 완료)")
