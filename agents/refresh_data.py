# -*- coding: utf-8 -*-
"""
데이터 갱신 스크립트 - 지연된 지표 새로고침 + 버그 수정
수정사항:
  1. MARKET_STRENGTH 버그 수정:
     기존: RSI14와 동일한 계산식 (SP500 RSI14 proxy) → 완전히 동일한 데이터
     수정: SP500 close / MA200 비율 기반 시장 강도 (0-100, 50=중립)
     의미: 시장이 200일 이평선 대비 얼마나 강한지 측정
  2. DXY 갱신 (9일 지연)
  3. WTI 갱신 (6일 지연)
"""
import utf8_setup  # noqa: F401

import json, os, sys, warnings
import numpy as np
import pandas as pd
import httpx
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

_PARTIAL_FAIL_FLAG = BASE_DIR / ".refresh_partial_failure"

# .env에서 FRED_API_KEY 로드
env_path = BASE_DIR / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

FRED_KEY = os.environ.get("FRED_API_KEY", "")
END   = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")


def save_parquet(df: pd.DataFrame, name: str, source: str):
    df = df.copy()
    df["date"]  = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    path = RAW_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"  [OK] {name}: {len(df)}행  최근={df['date'].iloc[-1].strftime('%Y-%m-%d')}  ({source})")


def fred_series(series_id: str) -> pd.DataFrame:
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&observation_start={START}"
           f"&observation_end={END}&api_key={FRED_KEY}&file_type=json")
    r = httpx.get(url, timeout=20)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    rows = [(o["date"], o["value"]) for o in obs if o["value"] != "."]
    df = pd.DataFrame(rows, columns=["date", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()


def _verify_done_criteria(output_path: str, date_col: str, min_rows: int = 1) -> None:
    """Done Criteria block. Any failure → sys.exit(1)."""
    errors = []

    # DC-1: output file exists
    if not os.path.exists(output_path):
        errors.append(f"DC-1 FAIL: {output_path} not found")

    # DC-2: output file not empty
    elif os.path.getsize(output_path) == 0:
        errors.append(f"DC-2 FAIL: {output_path} is empty")

    else:
        try:
            if output_path.endswith(".csv"):
                df = pd.read_csv(output_path)
            elif output_path.endswith(".parquet"):
                df = pd.read_parquet(output_path)
            else:
                df = pd.read_json(output_path)

            # DC-3: row count threshold
            if len(df) < min_rows:
                errors.append(f"DC-3 FAIL: row count {len(df)} < {min_rows}")

            # DC-4: no stale data (newest row within 7 days)
            if date_col in df.columns:
                latest = pd.to_datetime(df[date_col]).max()
                age_days = (pd.Timestamp.now() - latest).days
                if age_days > 7:
                    errors.append(f"DC-4 FAIL: newest row is {age_days} days old")

        except Exception as e:
            errors.append(f"DC-3 FAIL: could not read output — {e}")

    # DC-5: no partial failure flag
    if _PARTIAL_FAIL_FLAG.exists():
        errors.append("DC-5 FAIL: partial failure flag exists")

    if errors:
        for e in errors:
            print(f"[DONE CRITERIA] {e}", file=sys.stderr)
        print("DONE_CRITERIA: FAIL — " + " | ".join(errors))
        sys.exit(1)

    print(f"[DONE CRITERIA] {output_path} — DC-1~DC-5 all PASS")
    print("DONE_CRITERIA: PASS")


if __name__ == "__main__":
    # Clean up any stale partial failure flag from previous runs
    if _PARTIAL_FAIL_FLAG.exists():
        _PARTIAL_FAIL_FLAG.unlink()

    print("=" * 55)
    print("데이터 갱신 & 버그 수정")
    print("=" * 55)

    # ──────────────────────────────────────────────
    # 1. MARKET_STRENGTH 재계산 (MA200 기반 시장 강도)
    # ──────────────────────────────────────────────
    print("\n[Fix 1] MARKET_STRENGTH - MA200 기반 시장 강도 재계산")
    try:
        sp_path = RAW_DIR / "SP500.parquet"
        sp = pd.read_parquet(sp_path)
        sp["date"]  = pd.to_datetime(sp["date"]).dt.tz_localize(None)
        sp = sp.sort_values("date").set_index("date")
        price = sp["value"]

        ma200 = price.rolling(200, min_periods=100).mean()

        # MARKET_STRENGTH = 50 + (close - MA200) / MA200 * 100
        # 50=중립, 60=10% 위, 40=10% 아래  → clamp 0~100
        strength = 50 + (price - ma200) / ma200 * 100
        strength = strength.clip(0, 100)

        out = strength.reset_index()
        out.columns = ["date", "value"]
        out = out.dropna()
        save_parquet(out, "MARKET_STRENGTH", "CALC:SP500/MA200_normalized")

        # 기존 값과 비교
        old_path = RAW_DIR / "RSI14.parquet"
        rsi14 = pd.read_parquet(old_path)
        rsi14["date"] = pd.to_datetime(rsi14["date"]).dt.tz_localize(None)
        rsi14 = rsi14.sort_values("date")
        last_rsi = rsi14["value"].iloc[-1]
        last_ms  = strength.iloc[-1]
        print(f"  수정 전 MARKET_STRENGTH(=RSI14): {last_rsi:.2f}")
        print(f"  수정 후 MARKET_STRENGTH(MA200기반): {last_ms:.2f}")
        print(f"  → SP500이 MA200({ma200.iloc[-1]:,.0f}) 대비 {(price.iloc[-1]/ma200.iloc[-1]-1)*100:+.1f}% 위치")
    except Exception as e:
        print(f"  [ERROR] {e}")
        _PARTIAL_FAIL_FLAG.write_text(f"Fix1 failed: {e}")

    # ──────────────────────────────────────────────
    # 2. DXY 갱신 (FRED: DTWEXBGS)
    # ──────────────────────────────────────────────
    print("\n[Fix 2] DXY 갱신 (FRED: DTWEXBGS)")
    if not FRED_KEY:
        print("  [SKIP] FRED_API_KEY 없음")
    else:
        try:
            df = fred_series("DTWEXBGS")
            save_parquet(df, "DXY", "FRED:DTWEXBGS")
        except Exception as e:
            print(f"  [ERROR] {e}")
            # yfinance 폴백
            try:
                import yfinance as yf
                df = yf.download("DX-Y.NYB", start=START, end=END, progress=False)
                if not df.empty:
                    df = df[["Close"]].reset_index()
                    df.columns = ["date", "value"]
                    save_parquet(df, "DXY", "yfinance:DX-Y.NYB")
            except Exception as e2:
                print(f"  [ERROR yf fallback] {e2}")

    # ──────────────────────────────────────────────
    # 3. WTI 갱신 (FRED: DCOILWTICO)
    # ──────────────────────────────────────────────
    print("\n[Fix 3] WTI 갱신 (FRED: DCOILWTICO)")
    if not FRED_KEY:
        print("  [SKIP] FRED_API_KEY 없음")
    else:
        try:
            df = fred_series("DCOILWTICO")
            save_parquet(df, "WTI", "FRED:DCOILWTICO")
        except Exception as e:
            print(f"  [ERROR] {e}")

    # ──────────────────────────────────────────────
    # 4. 갱신 후 데이터 신선도 재확인
    # ──────────────────────────────────────────────
    print("\n=== 갱신 후 신선도 확인 ===")
    TODAY = pd.Timestamp.now().normalize()
    targets = [
        ("MARKET_STRENGTH", "MA200기반 시장강도 (수정)"),
        ("RSI14",           "SP500 RSI14 (별도 유지)"),
        ("DXY",             "달러인덱스"),
        ("WTI",             "WTI 원유"),
    ]
    for name, desc in targets:
        p = RAW_DIR / f"{name}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            last = df.sort_values("date")["date"].iloc[-1]
            val  = df.sort_values("date")["value"].iloc[-1]
            days = (TODAY - last).days
            flag = "OK" if days <= 3 else ("WARN" if days <= 7 else "OLD")
            print(f"  [{flag:4}] {name:20s} {val:>12.4f}  {last.strftime('%Y-%m-%d')} ({days}일전)  - {desc}")
        else:
            print(f"  [MISS] {name:20s} 파일 없음")

    print("\n완료")

    # ──────────────────────────────────────────────
    # Done Criteria: DC-1~DC-5 자체검증
    # ──────────────────────────────────────────────
    _verify_done_criteria(
        str(RAW_DIR / "MARKET_STRENGTH.parquet"),
        date_col="date",
        min_rows=50,
    )
