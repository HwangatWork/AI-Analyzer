"""
Data Agent — F01~F05 데이터 수집
수집 기간: 최근 1년 (실행 시점 기준 동적 산출)
"""
import utf8_setup  # noqa: F401

import os
import sys
import json
import httpx
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

END = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

RESULTS = {}


def save_parquet(df: pd.DataFrame, name: str, source: str):
    if df is None or df.empty:
        fail(name, "DataFrame이 비어 있음")
        return False
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date", "Date": "date"})
    if "value" not in df.columns:
        # 단일 값 컬럼이면 value로 rename
        cols = [c for c in df.columns if c != "date"]
        if len(cols) == 1:
            df = df.rename(columns={cols[0]: "value"})
        else:
            df["value"] = df[cols[0]]
    df["source"] = source
    df = df[["date", "value", "source"]].dropna(subset=["value"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    path = RAW_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    RESULTS[name] = {"status": "ok", "rows": len(df), "path": str(path)}
    print(f"  [OK] {name}: {len(df)}행 저장 → {path.name}")
    return True


def fail(name: str, reason: str):
    path = RAW_DIR / f"{name}_FAILED.txt"
    path.write_text(reason, encoding="utf-8")
    RESULTS[name] = {"status": "FAILED", "reason": reason}
    print(f"  [FAIL] {name}: {reason}")


# ──────────────────────────────────────────
# F01: 시장 지수 6개 (FDR)
# ──────────────────────────────────────────
def collect_f01():
    print("\n[F01] 시장 지수 6개 수집 (FDR)")
    import FinanceDataReader as fdr

    tickers = {
        "SP500": "US500",
        "NASDAQ100": "QQQ",
        "DOW": "^DJI",
        "KOSPI": "KS11",
        "KOSDAQ": "KQ11",
        "NIKKEI225": "^N225",
    }

    for name, ticker in tickers.items():
        try:
            df = fdr.DataReader(ticker, start=START, end=END)
            if df.empty:
                fail(name, f"FDR {ticker}: 데이터 없음")
                continue
            # Close 컬럼 우선 사용
            col = "Close" if "Close" in df.columns else df.columns[0]
            out = df[[col]].rename(columns={col: "value"}).reset_index()
            out = out.rename(columns={"Date": "date", "index": "date"})
            save_parquet(out, name, f"FDR:{ticker}")
        except Exception as e:
            fail(name, str(e))


# ──────────────────────────────────────────
# F02: 매크로 지표 6개 (FRED API)
# ──────────────────────────────────────────
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
    return df


def collect_f02():
    print("\n[F02] 매크로 지표 6개 수집 (FRED API)")
    if not FRED_API_KEY:
        print("  [WARN] FRED_API_KEY 없음 — .env 확인 필요")

    series_map = {
        "US10Y": "GS10",          # 미국 10년물 국채금리
        "DXY": "DTWEXBGS",        # 달러인덱스 (무역가중)
        "WTI": "DCOILWTICO",      # WTI 원유
        "FED_ASSETS": "WALCL",    # 연준 총자산
        "T10Y2Y": "T10Y2Y",       # 장단기 금리차 (10Y-2Y)
        "HY_SPREAD": "BAMLH0A0HYM2", # 하이일드 스프레드
    }

    for name, sid in series_map.items():
        try:
            df = fred_series(sid)
            save_parquet(df, name, f"FRED:{sid}")
        except Exception as e:
            fail(name, f"FRED {sid}: {e}")


# ──────────────────────────────────────────
# F03: 시장 심리 지표 (CNN + FDR VIX + SKEW + PutCall)
# ──────────────────────────────────────────
def collect_f03():
    print("\n[F03] 시장 심리 지표 수집")
    import FinanceDataReader as fdr

    # 1) VIX — FDR (^VIX) then FRED VIXCLS fallback
    try:
        df = fdr.DataReader("^VIX", start=START, end=END)
        if df.empty:
            raise ValueError("FDR ^VIX: 데이터 없음")
        col = "Close" if "Close" in df.columns else df.columns[0]
        out = df[[col]].rename(columns={col: "value"}).reset_index()
        out = out.rename(columns={"Date": "date"})
        save_parquet(out, "VIX", "FDR:^VIX")
    except Exception as e:
        try:
            df = fred_series("VIXCLS")
            save_parquet(df, "VIX", "FRED:VIXCLS")
        except Exception as e2:
            fail("VIX", f"FDR:{e} / FRED:{e2}")

    # 2) SKEW — FRED SKEW -> yfinance ^SKEW fallback
    try:
        df = fred_series("SKEW")
        save_parquet(df, "SKEW", "FRED:SKEW")
    except Exception as e:
        try:
            import yfinance as yf
            tk = yf.Ticker("^SKEW")
            df = tk.history(start=START, end=END)[["Close"]].reset_index()
            df = df.rename(columns={"Date": "date", "Close": "value"})
            save_parquet(df, "SKEW", "yfinance:^SKEW")
        except Exception as e2:
            fail("SKEW", f"FRED:{e} / yfinance:{e2}")

    # 3) Put/Call 비율 — yfinance (CBOE PCR)
    try:
        import yfinance as yf
        tk = yf.Ticker("^PCALL")
        df = tk.history(start=START, end=END)[["Close"]].reset_index()
        df = df.rename(columns={"Date": "date", "Close": "value"})
        save_parquet(df, "PUT_CALL", "yfinance:^PCALL")
    except Exception as e:
        fail("PUT_CALL", f"yfinance ^PCALL: {e}")

    # 4) CNN 공포탐욕지수 — API (키 불필요)
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        data = r.json()
        # 최신 단일값
        score = data.get("fear_and_greed", {}).get("score")
        ts = data.get("fear_and_greed", {}).get("timestamp")
        if score is not None:
            rows = []
            # 히스토리
            for item in data.get("fear_and_greed_historical", {}).get("data", []):
                rows.append({"date": pd.to_datetime(item["x"], unit="ms"), "value": item["y"]})
            if not rows:
                rows = [{"date": pd.Timestamp.today(), "value": float(score)}]
            df = pd.DataFrame(rows)
            save_parquet(df, "CNN_FG", "CNN:fearandgreed")
        else:
            fail("CNN_FG", "CNN API 응답에 score 없음")
    except Exception as e:
        fail("CNN_FG", f"CNN API: {e}")

    # 5) 시장 모멘텀 — S&P500 52주 고점 대비 현재 비율 (계산)
    try:
        sp_path = RAW_DIR / "SP500.parquet"
        if sp_path.exists():
            sp = pd.read_parquet(sp_path)
            sp["date"] = pd.to_datetime(sp["date"])
            sp = sp.sort_values("date")
            sp["momentum"] = sp["value"] / sp["value"].rolling(252).max()
            out = sp[["date", "momentum"]].rename(columns={"momentum": "value"})
            save_parquet(out, "MARKET_MOMENTUM", "CALC:SP500_52w")
        else:
            fail("MARKET_MOMENTUM", "SP500.parquet 없음 — F01 먼저 실행 필요")
    except Exception as e:
        fail("MARKET_MOMENTUM", str(e))

    # 6) 주식시장 강도 — FRED ADVN/DECN or SP500 RSI 기반 대체
    try:
        adv = fred_series("ADVN")
        dec = fred_series("DECN")
        adv = adv.rename(columns={"value": "adv"})
        dec = dec.rename(columns={"value": "dec"})
        merged = pd.merge(adv, dec, on="date")
        merged["value"] = merged["adv"].astype(float) / (merged["adv"].astype(float) + merged["dec"].astype(float))
        save_parquet(merged[["date", "value"]], "MARKET_STRENGTH", "FRED:ADVN/DECN")
    except Exception as e:
        # RSI 기반 강도 대체
        try:
            sp_path = RAW_DIR / "SP500.parquet"
            if sp_path.exists():
                sp = pd.read_parquet(sp_path)
                sp["date"] = pd.to_datetime(sp["date"])
                sp = sp.sort_values("date").set_index("date")
                r = rsi(sp["value"])
                out = r.reset_index()
                out.columns = ["date", "value"]
                save_parquet(out, "MARKET_STRENGTH", "CALC:SP500_RSI_STRENGTH")
            else:
                fail("MARKET_STRENGTH", f"FRED ADVN/DECN:{e} / SP500 없음")
        except Exception as e2:
            fail("MARKET_STRENGTH", f"FRED:{e} / CALC:{e2}")


# ──────────────────────────────────────────
# F04: 기술적 지표 8개 (계산)
# ──────────────────────────────────────────
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def stoch_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    r = rsi(series, period)
    min_r = r.rolling(period).min()
    max_r = r.rolling(period).max()
    return (r - min_r) / (max_r - min_r + 1e-10)


def collect_f04():
    print("\n[F04] 기술적 지표 8개 산출 (S&P500 기반)")
    sp_path = RAW_DIR / "SP500.parquet"
    if not sp_path.exists():
        for name in ["RSI14", "RSI_SIGNAL", "MA50", "MA200", "MA_SIGNAL", "BETA", "BBAND", "STOCH_RSI"]:
            fail(name, "SP500.parquet 없음")
        return

    sp = pd.read_parquet(sp_path)
    sp["date"] = pd.to_datetime(sp["date"])
    sp = sp.sort_values("date").set_index("date")
    price = sp["value"]

    # RSI(14일)
    try:
        r = rsi(price)
        df = r.reset_index().rename(columns={"value": "value"})
        df.columns = ["date", "value"]
        save_parquet(df, "RSI14", "CALC:SP500_RSI14")
    except Exception as e:
        fail("RSI14", str(e))

    # RSI 신호 (RSI > 70 과매수=1, < 30 과매도=-1, 나머지 0)
    try:
        r = rsi(price)
        sig = pd.Series(0, index=r.index, dtype=float)
        sig[r > 70] = 1
        sig[r < 30] = -1
        df = sig.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "RSI_SIGNAL", "CALC:SP500_RSI_SIG")
    except Exception as e:
        fail("RSI_SIGNAL", str(e))

    # MA50
    try:
        ma50 = price.rolling(50).mean()
        df = ma50.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "MA50", "CALC:SP500_MA50")
    except Exception as e:
        fail("MA50", str(e))

    # MA200
    try:
        ma200 = price.rolling(200).mean()
        df = ma200.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "MA200", "CALC:SP500_MA200")
    except Exception as e:
        fail("MA200", str(e))

    # MA 신호 (골든/데드크로스): MA50 > MA200 → 1, else -1
    try:
        ma50 = price.rolling(50).mean()
        ma200 = price.rolling(200).mean()
        sig = (ma50 > ma200).astype(float) * 2 - 1
        df = sig.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "MA_SIGNAL", "CALC:SP500_MA_SIG")
    except Exception as e:
        fail("MA_SIGNAL", str(e))

    # Beta (S&P500 대비 자기 자신 = 1.0 기준값, 코스피와의 Beta 사용)
    try:
        ksp_path = RAW_DIR / "KOSPI.parquet"
        if ksp_path.exists():
            ksp = pd.read_parquet(ksp_path)
            ksp["date"] = pd.to_datetime(ksp["date"])
            ksp = ksp.set_index("date")["value"].rename("kospi")
            merged = pd.concat([price, ksp], axis=1).dropna()
            merged.columns = ["sp500", "kospi"]
            ret_sp = merged["sp500"].pct_change().dropna()
            ret_ksp = merged["kospi"].pct_change().dropna()
            aligned = pd.concat([ret_sp, ret_ksp], axis=1).dropna()
            aligned.columns = ["sp500", "kospi"]
            beta = aligned["kospi"].rolling(60).cov(aligned["sp500"]) / aligned["sp500"].rolling(60).var()
            df = beta.reset_index()
            df.columns = ["date", "value"]
            save_parquet(df, "BETA", "CALC:KOSPI_BETA_vs_SP500")
        else:
            fail("BETA", "KOSPI.parquet 없음")
    except Exception as e:
        fail("BETA", str(e))

    # 볼린저밴드 (%B)
    try:
        ma20 = price.rolling(20).mean()
        std20 = price.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        pct_b = (price - lower) / (upper - lower + 1e-10)
        df = pct_b.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "BBAND", "CALC:SP500_BB_PCT")
    except Exception as e:
        fail("BBAND", str(e))

    # Stochastic RSI
    try:
        srsi = stoch_rsi(price)
        df = srsi.reset_index()
        df.columns = ["date", "value"]
        save_parquet(df, "STOCH_RSI", "CALC:SP500_STOCH_RSI")
    except Exception as e:
        fail("STOCH_RSI", str(e))


# ──────────────────────────────────────────
# F05: 수급 3개 (pykrx)
# ──────────────────────────────────────────
def collect_f05():
    print("\n[F05] 수급 3개 수집 (pykrx)")
    try:
        from pykrx import stock
        start_str = START.replace("-", "")
        end_str = END.replace("-", "")

        # 투자자별 순매수 (로그인 불필요 함수 우선 시도)
        df = None
        errors = []

        # 방법 1: get_market_net_purchases_of_equities_by_ticker (전체 종목 합산)
        try:
            df = stock.get_market_net_purchases_of_equities_by_ticker(start_str, end_str, "KOSPI")
            print(f"  pykrx net_purchases 컬럼: {list(df.columns)}")
        except Exception as e1:
            errors.append(f"net_purchases: {e1}")

        # 방법 2: get_market_trading_value_by_date (거래대금 기준)
        if df is None or df.empty:
            try:
                df = stock.get_market_trading_value_by_date(start_str, end_str, "KOSPI")
                print(f"  pykrx trading_value 컬럼: {list(df.columns)}")
            except Exception as e2:
                errors.append(f"trading_value: {e2}")

        if df is None or df.empty:
            raise ValueError(" / ".join(errors))

        df.index = pd.to_datetime(df.index)
        df.index.name = "date"

        label_keywords = {
            "FOREIGN_NET": ["외국인", "외국", "foreign"],
            "INSTITUTION_NET": ["기관", "institution"],
            "INDIVIDUAL_NET": ["개인", "individual", "retail"],
        }

        for target, kws in label_keywords.items():
            matched = None
            for col in df.columns:
                if any(kw in str(col).lower() for kw in kws):
                    matched = col
                    break
            if matched:
                out = df[[matched]].rename(columns={matched: "value"}).reset_index()
                save_parquet(out, target, "pykrx:KOSPI")
            else:
                fail(target, f"pykrx 컬럼 미매핑 (available: {list(df.columns)[:5]})")

    except Exception as e:
        for name in ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]:
            fail(name, f"pykrx: {e}")


# ──────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────
def update_progress(statuses: dict):
    prog_path = BASE_DIR / "claude-progress.txt"
    lines = prog_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        if "F01" in line and "F01" in statuses:
            line = line.replace("- 없음", "").strip()
        new_lines.append(line)
    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    status_map = {"ok": "done", "FAILED": "failed"}
    for feat in fl["features"]:
        fid = feat["id"]
        if fid in statuses:
            feat["status"] = status_map.get(statuses[fid], "done")
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    print("=" * 60)
    print("DATA AGENT 시작 - Phase 2 (F01~F05)")
    print(f"수집 기간: {START} ~ {END}")
    print("=" * 60)

    collect_f01()
    collect_f02()
    collect_f03()
    collect_f04()
    collect_f05()

    # 결과 요약
    print("\n" + "=" * 60)
    print("DATA AGENT 완료 — 결과 요약")
    ok = [k for k, v in RESULTS.items() if v["status"] == "ok"]
    failed = [k for k, v in RESULTS.items() if v["status"] == "FAILED"]
    print(f"성공: {len(ok)}/{len(RESULTS)}개")
    if failed:
        print(f"실패: {failed}")

    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    f01_done = all(RESULTS.get(k, {}).get("status") == "ok"
                   for k in ["SP500", "NASDAQ100", "DOW", "KOSPI", "KOSDAQ", "NIKKEI225"])
    f02_done = all(RESULTS.get(k, {}).get("status") == "ok"
                   for k in ["US10Y", "DXY", "WTI", "FED_ASSETS", "T10Y2Y", "HY_SPREAD"])
    f03_done = any(RESULTS.get(k, {}).get("status") == "ok"
                   for k in ["VIX", "SKEW", "PUT_CALL", "CNN_FG"])
    f04_done = any(RESULTS.get(k, {}).get("status") == "ok"
                   for k in ["RSI14", "MA50", "MA200", "BBAND"])
    f05_done = any(RESULTS.get(k, {}).get("status") == "ok"
                   for k in ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"])

    feat_status = {"F01": f01_done, "F02": f02_done, "F03": f03_done, "F04": f04_done, "F05": f05_done}
    for feat in fl["features"]:
        if feat["id"] in feat_status:
            feat["status"] = "done" if feat_status[feat["id"]] else "partial"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    # claude-progress.txt 업데이트
    prog = f"""# AI Analyzer 진행 상황

## 프로젝트 시작일: 2026-06-07
## 현재 단계: Phase 2 완료 — Phase 3 대기

## 완료된 작업
- [x] 프로젝트 구조 생성
- [x] CLAUDE.md 작성
- [x] feature_list.json 작성
- [x] Agent Teams 활성화
- [{'x' if f01_done else ' '}] F01 시장 지수 6개 수집
- [{'x' if f02_done else ' '}] F02 매크로 지표 6개 수집
- [{'x' if f03_done else ' '}] F03 시장 심리 지표 수집
- [{'x' if f04_done else ' '}] F04 기술적 지표 8개 산출
- [{'x' if f05_done else ' '}] F05 수급 3개 수집

## 수집 결과
- 성공: {len(ok)}/{len(RESULTS)}개
- 실패 목록: {failed if failed else '없음'}

## 진행 중
- Phase 3 Analysis Agent + Stock Agent 대기 중

## 데이터 수집 기간
시작: {START}
종료: {END} (최근 1년)

## 주요 이슈
{chr(10).join([f'- {k}: {RESULTS[k]["reason"]}' for k in failed]) if failed else '- 없음'}
"""
    (BASE_DIR / "claude-progress.txt").write_text(prog, encoding="utf-8")
    print("\nclaude-progress.txt 업데이트 완료")

    # 결과 JSON 저장
    result_path = BASE_DIR / "data" / "collection_report.json"
    result_path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"수집 리포트 저장: {result_path}")

    # ── Done Criteria 자체검증 (DC-1~DC-6) ───────────────────────────────────
    import sys
    _F02_KEYS = ["US10Y", "DXY", "WTI", "FED_ASSETS", "T10Y2Y", "HY_SPREAD"]
    _F05_KEYS = ["FOREIGN_NET", "INSTITUTION_NET", "INDIVIDUAL_NET"]
    _F01_KEYS = ["SP500", "NASDAQ100", "DOW", "KOSPI", "KOSDAQ", "NIKKEI225"]
    done_criteria = {
        "DC-1 F01 시장지수 수집":   all(RESULTS.get(k, {}).get("status") == "ok" for k in _F01_KEYS),
        "DC-2 F02 매크로 6/6":      all(RESULTS.get(k, {}).get("status") == "ok" for k in _F02_KEYS),
        "DC-3 F03 심리지표 ≥1":     any(RESULTS.get(k, {}).get("status") == "ok" for k in ["VIX", "SKEW", "PUT_CALL", "CNN_FG"]),
        "DC-4 F04 기술지표 ≥1":     any(RESULTS.get(k, {}).get("status") == "ok" for k in ["RSI14", "MA50", "MA200", "BBAND"]),
        "DC-5 F05 수급 3/3":        all(RESULTS.get(k, {}).get("status") == "ok" for k in _F05_KEYS),
        "DC-6 수집 파일 저장 확인":  result_path.exists() and result_path.stat().st_size > 50,
    }
    _dc_fails = [k for k, v in done_criteria.items() if not v]
    print("\n[Done Criteria]")
    for k, v in done_criteria.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    if _dc_fails:
        print(f"\n[DATA AGENT] Done Criteria FAIL: {_dc_fails}")
        sys.exit(1)
