# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — data_loader: FinanceDataReader 전용 PIT 피처 로더.

- pykrx 사용 금지 (환경 파손) — FinanceDataReader ONLY.
- per_trailing / consensus_gap 은 Phase A 설계상 None (Phase B에서 공급).
- PIT 규칙: asof 종가까지의 데이터만 사용 (zero lookahead). 모든 rolling
  지표는 trailing-only 연산으로 구성된다.
- 알려진 한계 (리포트 S2 기록 대상): 섹터·상장주식수는 '현재' 리스팅 기준
  (과거 시점 아님), 유니버스는 현재 상장 종목만 포함 → 생존편향 존재.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
OHLCV_DIR = CACHE_DIR / "ohlcv"
META_PATH = CACHE_DIR / "download_meta.json"
SNAPSHOT_CACHE = CACHE_DIR / "features_snapshots.parquet"

DOWNLOAD_START = "2021-07-01"  # 2023-01 스냅샷의 trailing 1yr + vol_z 워밍업 확보
RETRY = 3
RETRY_BACKOFF_SEC = 2.0
SLEEP_BETWEEN_SEC = 0.1        # polite batching
BATCH_PAUSE_EVERY = 200
BATCH_PAUSE_SEC = 3.0

# 최소 이력 요건 (미달 시 해당 피처 None — 분류기의 결측 인지에 위임)
MIN_DAYS_POS = 200      # 52주 극값 신뢰 하한 (거래일)
MIN_DAYS_RSI = 30
MIN_OBS_VOLZ = 252      # rv20 관측치 252개 → 총 ~272 거래일 필요

FEATURE_COLS = ["pos_low", "pos_high", "per_trailing", "consensus_gap",
                "rsi14", "vol_z20"]


def _fdr():
    import FinanceDataReader as fdr
    return fdr


# ── 유니버스 ─────────────────────────────────────────────────────────────

def load_universe(refresh: bool = False) -> pd.DataFrame:
    """KOSPI+KOSDAQ 리스팅 (Code, Name, Market, Marcap, Stocks, Sector).

    섹터는 KRX-DESC의 'Industry'(KRX 산업분류) 사용 — DESC의 'Sector' 컬럼은
    KOSPI 전 종목 NaN(코스닥은 소속부 값)이라 산업분류가 아님 (2026-07-04 실측).
    '현재' 분류 기준 (PIT 아님, S2 한계).
    """
    cache = CACHE_DIR / "universe.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    fdr = _fdr()
    krx = fdr.StockListing("KRX")
    krx = krx[krx["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])].copy()
    keep = [c for c in ["Code", "Name", "Market", "Marcap", "Stocks"] if c in krx.columns]
    krx = krx[keep]
    try:
        desc = fdr.StockListing("KRX-DESC")
        krx = krx.merge(desc[["Code", "Industry"]], on="Code", how="left")
        krx = krx.rename(columns={"Industry": "Sector"})
    except Exception:
        krx["Sector"] = None
    if "Sector" not in krx.columns:
        krx["Sector"] = None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    krx.to_parquet(cache)
    return krx


# ── OHLCV 캐시 ───────────────────────────────────────────────────────────

_MEM_CACHE: dict[str, pd.DataFrame | None] = {}


def load_ohlcv(ticker: str, refresh: bool = False) -> pd.DataFrame | None:
    """단일 종목 일봉 (DOWNLOAD_START~현재). 메모리 → parquet 캐시 → FDR."""
    if not refresh and ticker in _MEM_CACHE:
        return _MEM_CACHE[ticker]
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    path = OHLCV_DIR / f"{ticker}.parquet"
    if path.exists() and not refresh:
        df = pd.read_parquet(path)
        res = df if not df.empty else None
        _MEM_CACHE[ticker] = res
        return res
    fdr = _fdr()
    last_err = None
    for attempt in range(RETRY):
        try:
            df = fdr.DataReader(ticker, DOWNLOAD_START)
            if df is None:
                df = pd.DataFrame()
            df.to_parquet(path)  # 빈 결과도 캐시 (재시도 폭주 방지)
            res = df if not df.empty else None
            _MEM_CACHE[ticker] = res
            return res
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    pd.DataFrame().to_parquet(path)
    _MEM_CACHE[ticker] = None
    return None


def download_universe(tickers: list[str]) -> dict:
    """전 종목 다운로드. wall-clock과 빈 티커 수를 meta에 기록."""
    t0 = time.time()
    n_ok, n_empty = 0, 0
    empty_tickers: list[str] = []
    for i, tk in enumerate(tickers):
        df = load_ohlcv(tk)
        if df is None or df.empty:
            n_empty += 1
            empty_tickers.append(tk)
        else:
            n_ok += 1
        time.sleep(SLEEP_BETWEEN_SEC)
        if (i + 1) % BATCH_PAUSE_EVERY == 0:
            time.sleep(BATCH_PAUSE_SEC)
            print(f"[data_loader] {i+1}/{len(tickers)} done "
                  f"(ok={n_ok} empty={n_empty}, {time.time()-t0:.0f}s)", flush=True)
    meta = {
        "n_tickers": len(tickers),
        "n_ok": n_ok,
        "n_empty": n_empty,
        "empty_tickers": empty_tickers,
        "wall_clock_sec": round(time.time() - t0, 1),
        "download_start": DOWNLOAD_START,
        "finished_at": pd.Timestamp.now().isoformat(),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return meta


# ── PIT 피처 ─────────────────────────────────────────────────────────────

def _wilder_rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss > 0, 100.0)
    rsi[avg_gain.isna() | avg_loss.isna()] = np.nan
    return rsi


def _vol_z20(close: pd.Series) -> pd.Series:
    ret = np.log(close).diff()
    rv20 = ret.rolling(20, min_periods=20).std()
    mu = rv20.rolling(MIN_OBS_VOLZ, min_periods=MIN_OBS_VOLZ).mean()
    sd = rv20.rolling(MIN_OBS_VOLZ, min_periods=MIN_OBS_VOLZ).std()
    return (rv20 - mu) / sd.replace(0.0, np.nan)


def compute_feature_series(px: pd.DataFrame) -> pd.DataFrame:
    """전 기간 trailing-only 피처 시계열 (asof 인덱싱으로 PIT 보장).

    pos_low/pos_high 는 종가 기준 trailing 365 calendar-day 극값 사용
    (장중 고저가 이상치 회피 — 선택 사항으로 문서화).
    """
    close = px["Close"].astype(float)
    idx = close.index
    win_min = close.rolling("365D").min()
    win_max = close.rolling("365D").max()
    win_cnt = close.rolling("365D").count()
    pos_low = close / win_min - 1.0
    pos_high = close / win_max - 1.0
    pos_low[win_cnt < MIN_DAYS_POS] = np.nan
    pos_high[win_cnt < MIN_DAYS_POS] = np.nan
    rsi = _wilder_rsi14(close)
    rsi[np.arange(len(idx)) < MIN_DAYS_RSI] = np.nan
    volz = _vol_z20(close)
    out = pd.DataFrame({
        "close": close,
        "pos_low": pos_low,
        "pos_high": pos_high,
        "rsi14": rsi,
        "vol_z20": volz,
    }, index=idx)
    return out


def _asof_row(feat: pd.DataFrame, asof: pd.Timestamp) -> pd.Series | None:
    sub = feat.loc[:asof]
    if sub.empty:
        return None
    row = sub.iloc[-1]
    # 스냅샷일과 마지막 거래일 간 15일 초과 괴리 → 거래정지 등 — 제외
    if (asof - sub.index[-1]).days > 15:
        return None
    return row


def build_snapshot(asof: date | str, universe: pd.DataFrame | None = None,
                   feature_store: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """단일 스냅샷 PIT 피처 프레임. 대량 실행은 build_all_snapshots 권장."""
    return build_all_snapshots([asof], universe, feature_store)


def build_all_snapshots(dates: list, universe: pd.DataFrame | None = None,
                        feature_store: dict[str, pd.DataFrame] | None = None,
                        use_cache: bool = True) -> pd.DataFrame:
    """월말 스냅샷 전체를 티커당 1회 로드로 계산. 결과 parquet 캐시."""
    dates = [pd.Timestamp(d) for d in dates]
    if use_cache and SNAPSHOT_CACHE.exists():
        cached = pd.read_parquet(SNAPSHOT_CACHE)
        have = set(pd.to_datetime(cached["asof"]).unique())
        if all(d in have for d in dates):
            return cached[pd.to_datetime(cached["asof"]).isin(dates)].copy()
    if universe is None:
        universe = load_universe()
    rows = []
    t0 = time.time()
    for n, (_, u) in enumerate(universe.iterrows()):
        tk = u["Code"]
        if feature_store is not None and tk in feature_store:
            feat = feature_store[tk]
        else:
            px = load_ohlcv(tk)
            if px is None or "Close" not in px.columns or len(px) < MIN_DAYS_RSI:
                continue
            feat = compute_feature_series(px)
            if feature_store is not None:
                feature_store[tk] = feat
        stocks = u.get("Stocks")
        for d in dates:
            row = _asof_row(feat, d)
            if row is None:
                continue
            mcap = float(stocks) * float(row["close"]) if pd.notna(stocks) else None
            rows.append({
                "asof": d, "ticker": tk, "name": u.get("Name"),
                "market": u.get("Market"), "sector": u.get("Sector"),
                "close": float(row["close"]),
                "market_cap_krw": mcap,
                "pos_low": _nan_to_none(row["pos_low"]),
                "pos_high": _nan_to_none(row["pos_high"]),
                "per_trailing": None,      # Phase A: 설계상 결측
                "consensus_gap": None,     # Phase A: 설계상 결측
                "rsi14": _nan_to_none(row["rsi14"]),
                "vol_z20": _nan_to_none(row["vol_z20"]),
            })
        if (n + 1) % 500 == 0:
            print(f"[snapshot] {n+1}/{len(universe)} tickers "
                  f"({time.time()-t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    if use_cache and not df.empty:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(SNAPSHOT_CACHE)
    return df


def _nan_to_none(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


# ── 가격 조회 (백테스트 지원) ────────────────────────────────────────────

def price_asof(ticker: str, asof: date | str,
               feature_store: dict | None = None) -> float | None:
    px = load_ohlcv(ticker)
    if px is None:
        return None
    sub = px.loc[:pd.Timestamp(asof)]
    if sub.empty or (pd.Timestamp(asof) - sub.index[-1]).days > 15:
        return None
    return float(sub["Close"].iloc[-1])


def forward_return(ticker: str, asof: date | str, days: int = 90) -> float | None:
    """asof 종가 → asof+days(달력일) 이내 마지막 거래일 종가 수익률."""
    px = load_ohlcv(ticker)
    if px is None:
        return None
    t = pd.Timestamp(asof)
    base = px.loc[:t]
    if base.empty or (t - base.index[-1]).days > 15:
        return None
    end = t + timedelta(days=days)
    fwd = px.loc[:end]
    if fwd.index[-1] <= base.index[-1]:
        return None
    # 전방 구간에 실제 거래가 있어야 함 (최소 30일 커버)
    if (fwd.index[-1] - base.index[-1]).days < 30:
        return None
    p0 = float(base["Close"].iloc[-1])
    p1 = float(fwd["Close"].iloc[-1])
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def month_end_snapshots(start: str = "2023-01", end: str = "2025-12") -> list[pd.Timestamp]:
    return list(pd.date_range(start=start, end=pd.Period(end).end_time.normalize(),
                              freq="ME"))
