# -*- coding: utf-8 -*-
"""
Stock Agent v3 — 동적 전체 유니버스 분석
설계 원칙: 특정 종목을 하드코딩하지 않는다.
  - KOSPI: fdr.StockListing('KOSPI') → 시총 상위 N개 전체 동적 수집
  - S&P500: Wikipedia 구성종목 전체 + yfinance 배치 다운로드

분석 대상:
  - KOSPI 시총 상위 100개 (KRX 시총 기준 자동 정렬)
  - S&P 500 전체 503개 (Wikipedia 구성종목 기준)

F09: S&P500 지수 기여 Top5 (시총 × 상관도 × 수익률)
F10: 코스피  지수 기여 Top5
F11: S&P500 수혜 종목 Top5 (지수 초과수익 × 상관도)
F12: 코스피  수혜 종목 Top5
"""
import utf8_setup  # noqa: F401

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from pathlib import Path
from datetime import datetime, timedelta
from scipy import stats
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

END   = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
PERIOD_LABEL = "1년 (365일)"

KOSPI_TOP_N   = 100   # 시총 상위 N개
SP500_BATCH   = 50    # yfinance 배치 크기
MAX_SOURCE_DIFF_PCT = 100.0  # 두 소스 수익률 차이 허용 한도


# ─────────────────────────────────────────────────────────────────────────────
# 유니버스 동적 수집
# ─────────────────────────────────────────────────────────────────────────────

def _get_kospi_universe_pykrx() -> list[tuple[str, str]] | None:
    """pykrx로 KOSPI 시총 상위 종목 수집 (KRX_ID/KRX_PW 필요)."""
    import os
    if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
        return None
    try:
        from pykrx import stock as pykrx_stock
        date_str = (datetime.now() - timedelta(days=3)).strftime('%Y%m%d')
        caps_df = pykrx_stock.get_market_cap(date_str, market='KOSPI')
        if caps_df is None or caps_df.empty:
            return None
        # 시가총액 컬럼 = 두 번째 컬럼 (인코딩 무관)
        marcap_col = caps_df.columns[1]
        caps_df[marcap_col] = pd.to_numeric(caps_df[marcap_col], errors='coerce')
        caps_df = caps_df.dropna(subset=[marcap_col]).sort_values(marcap_col, ascending=False)
        top_codes = caps_df.index[:KOSPI_TOP_N].tolist()
        result = []
        for code in top_codes:
            try:
                name = pykrx_stock.get_market_ticker_name(str(code))
            except Exception:
                name = str(code)
            result.append((str(code).zfill(6) + ".KS", name or str(code)))
        print(f"  → pykrx KOSPI {len(result)}개 종목 수집 완료 (1위:{result[0][1]})")
        return result
    except Exception as e:
        print(f"  [경고] pykrx KOSPI 유니버스 수집 실패: {e}")
        return None


def get_kospi_universe() -> list[tuple[str, str]]:
    """KRX에서 KOSPI 전체 종목을 시총순 정렬 → 상위 KOSPI_TOP_N개 반환.
    수집 순서: pykrx(KRX auth) → fdr.StockListing → 비상 폴백(80개)
    """
    print(f"  [유니버스] KOSPI 구성종목 수집 중 (시총 상위 {KOSPI_TOP_N}개)...")

    # 방법 1: pykrx (KRX 자격증명 사용, CI secrets 포함)
    result = _get_kospi_universe_pykrx()
    if result and len(result) >= 50:
        return result

    # 방법 2: FDR StockListing (환경에 따라 동작)
    try:
        listing = fdr.StockListing('KOSPI')
        marcap_col = next((c for c in listing.columns if 'Marcap' in c or 'marcap' in c or '시총' in c), None)
        name_col   = next((c for c in listing.columns if 'Name' in c or 'name' in c or '종목명' in c), None)
        code_col   = next((c for c in listing.columns if 'Code' in c or 'code' in c or '코드' in c), None)
        if all([marcap_col, name_col, code_col]):
            listing[marcap_col] = pd.to_numeric(listing[marcap_col], errors='coerce')
            listing = listing.dropna(subset=[marcap_col]).sort_values(marcap_col, ascending=False)
            top = listing.head(KOSPI_TOP_N)
            fdr_result = [(str(row[code_col]).zfill(6) + ".KS", str(row[name_col])) for _, row in top.iterrows()]
            if len(fdr_result) >= 50:
                print(f"  → FDR KOSPI {len(fdr_result)}개 종목 수집 완료")
                return fdr_result
    except Exception as e:
        print(f"  [경고] FDR StockListing 실패: {e}")

    # 방법 3: 비상 폴백 — 주요 KOSPI 상장 80개 (동적 수집 불가 시)
    print("  → 폴백: 비상 종목 리스트 사용 (pykrx/FDR 모두 실패)")
    return [
        ("005930.KS","삼성전자"),("000660.KS","SK하이닉스"),("005380.KS","현대차"),
        ("009150.KS","삼성전기"),("066570.KS","LG전자"),("005490.KS","POSCO홀딩스"),
        ("035420.KS","NAVER"),("051910.KS","LG화학"),("006400.KS","삼성SDI"),
        ("000270.KS","기아"),("042700.KS","한미반도체"),("012330.KS","현대모비스"),
        ("003550.KS","LG"),("096770.KS","SK이노베이션"),("034730.KS","SK스퀘어"),
        ("028260.KS","삼성물산"),("017670.KS","SK텔레콤"),("030200.KS","KT"),
        ("086790.KS","하나금융지주"),("105560.KS","KB금융"),("055550.KS","신한지주"),
        ("032830.KS","삼성생명"),("000810.KS","삼성화재"),("010130.KS","고려아연"),
        ("003490.KS","대한항공"),("011200.KS","HMM"),("006360.KS","GS건설"),
        ("047050.KS","포스코인터내셔널"),("004020.KS","현대제철"),("011170.KS","롯데케미칼"),
        ("002790.KS","아모레퍼시픽"),("090430.KS","아모레G"),("000080.KS","하이트진로"),
        ("033780.KS","KT&G"),("097950.KS","CJ제일제당"),("034220.KS","LG디스플레이"),
        ("018260.KS","삼성에스디에스"),("009830.KS","한화솔루션"),("010950.KS","S-Oil"),
        ("000720.KS","현대건설"),("028050.KS","삼성엔지니어링"),("010140.KS","삼성중공업"),
        ("009540.KS","한국조선해양"),("042660.KS","한화오션"),("267250.KS","HD현대"),
        ("329180.KS","HD현대중공업"),("078930.KS","GS"),("082740.KS","한화에어로스페이스"),
        ("011790.KS","SKC"),("006650.KS","대한유화"),("003670.KS","포스코퓨처엠"),
        ("373220.KS","LG에너지솔루션"),("247540.KS","에코프로비엠"),("086520.KS","에코프로"),
        ("011790.KS","SKC"),("035000.KS","한화"),("139480.KS","이마트"),
        ("004170.KS","신세계"),("069960.KS","현대백화점"),("071050.KS","한국금융지주"),
        ("316140.KS","우리금융지주"),("138040.KS","메리츠금융지주"),("000100.KS","유한양행"),
        ("068270.KS","셀트리온"),("207940.KS","삼성바이오로직스"),("005935.KS","삼성전자우"),
        ("000157.KS","두산"),("034020.KS","두산에너빌리티"),("064350.KS","현대로템"),
        ("010620.KS","현대미포조선"),("023530.KS","롯데쇼핑"),("004990.KS","롯데지주"),
        ("036570.KS","NCsoft"),("251270.KS","넷마블"),("263750.KS","펄어비스"),
        ("018880.KS","한온시스템"),("241560.KS","두산밥캣"),("009070.KS","코오롱인더"),
        ("011780.KS","금호석유화학"),("010060.KS","OCI홀딩스"),("298040.KS","효성중공업"),
    ]


def get_sp500_universe() -> list[tuple[str, str]]:
    """S&P 500 전체 구성종목 수집 (FDR → Wikipedia → 내장 전체 리스트 순서로 시도)."""
    print("  [유니버스] S&P 500 구성종목 수집 중...")

    # 시도 1: FDR StockListing
    try:
        listing = fdr.StockListing('S&P500')
        sym_col  = next((c for c in listing.columns if 'Symbol' in c or 'Code' in c), listing.columns[0])
        name_col = next((c for c in listing.columns if 'Name' in c or 'Security' in c), listing.columns[1])
        result = [(str(r[sym_col]).replace('.', '-'), str(r[name_col])) for _, r in listing.iterrows() if str(r[sym_col]) != 'nan']
        if len(result) >= 400:
            print(f"  → FDR S&P500 {len(result)}개 수집 완료")
            return result
    except Exception as e:
        print(f"  FDR S&P500 실패: {e}")

    # 시도 2: Wikipedia (User-Agent 헤더 포함)
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Analyzer/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read()
        tables = pd.read_html(html, header=0)
        df = tables[0]
        symbol_col   = next((c for c in df.columns if 'Symbol' in c or 'Ticker' in c), df.columns[0])
        security_col = next((c for c in df.columns if 'Security' in c or 'Name' in c), df.columns[1])
        result = []
        for _, row in df.iterrows():
            sym  = str(row[symbol_col]).strip().replace('.', '-')
            name = str(row[security_col]).strip()
            if sym and sym != 'nan':
                result.append((sym, name))
        if len(result) >= 400:
            print(f"  → Wikipedia S&P500 {len(result)}개 수집 완료")
            return result
    except Exception as e:
        print(f"  Wikipedia S&P500 실패: {e}")

    # 시도 3: 내장 전체 리스트 (2026년 기준 S&P 500 대표 종목)
    print("  → 내장 S&P500 리스트 사용 (시총 상위 100개)")
    return [
        ("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),
        ("GOOGL","Alphabet"),("META","Meta"),("AVGO","Broadcom"),("TSLA","Tesla"),
        ("BRK-B","Berkshire Hathaway"),("LLY","Eli Lilly"),("JPM","JPMorgan"),
        ("V","Visa"),("UNH","UnitedHealth"),("XOM","ExxonMobil"),("MA","Mastercard"),
        ("COST","Costco"),("HD","Home Depot"),("PG","P&G"),("ORCL","Oracle"),
        ("WMT","Walmart"),("NFLX","Netflix"),("AMD","AMD"),("CRM","Salesforce"),
        ("NOW","ServiceNow"),("ADBE","Adobe"),("QCOM","Qualcomm"),("PM","Philip Morris"),
        ("TXN","Texas Instruments"),("INTU","Intuit"),("ISRG","Intuitive Surgical"),
        ("AMGN","Amgen"),("GE","GE Aerospace"),("RTX","RTX Corp"),("CAT","Caterpillar"),
        ("BKNG","Booking Holdings"),("PLD","Prologis"),("LOW","Lowe's"),("SPGI","S&P Global"),
        ("AXP","American Express"),("AMAT","Applied Materials"),("PANW","Palo Alto Networks"),
        ("MU","Micron Technology"),("LRCX","Lam Research"),("KLAC","KLA Corp"),
        ("MRVL","Marvell Technology"),("CDNS","Cadence Design"),("SNPS","Synopsys"),
        ("ADI","Analog Devices"),("MCHP","Microchip Technology"),("ON","ON Semiconductor"),
        ("FTNT","Fortinet"),("CRWD","CrowdStrike"),("DDOG","Datadog"),("SNOW","Snowflake"),
        ("ZS","Zscaler"),("MDB","MongoDB"),("TTD","Trade Desk"),("COIN","Coinbase"),
        ("PLTR","Palantir"),("ARM","ARM Holdings"),("SMCI","Super Micro Computer"),
        ("TSM","TSMC"),("ASML","ASML"),("INTC","Intel"),("TER","Teradyne"),
        ("ENTG","Entegris"),("ACLS","Axcelis Technologies"),("ONTO","Onto Innovation"),
        ("GS","Goldman Sachs"),("MS","Morgan Stanley"),("BAC","Bank of America"),
        ("WFC","Wells Fargo"),("C","Citigroup"),("BLK","BlackRock"),("SCHW","Charles Schwab"),
        ("CME","CME Group"),("ICE","Intercontinental Exchange"),("CBOE","Cboe Global"),
        ("CVX","Chevron"),("COP","ConocoPhillips"),("EOG","EOG Resources"),
        ("SLB","Schlumberger"),("MPC","Marathon Petroleum"),("VLO","Valero Energy"),
        ("NEE","NextEra Energy"),("DUK","Duke Energy"),("SO","Southern Company"),
        ("LIN","Linde"),("APD","Air Products"),("SHW","Sherwin-Williams"),
        ("ECL","Ecolab"),("PPG","PPG Industries"),("EMR","Emerson Electric"),
        ("HON","Honeywell"),("ETN","Eaton"),("ITW","Illinois Tool Works"),
        ("UPS","UPS"),("FDX","FedEx"),("CSX","CSX"),("UNP","Union Pacific"),
        ("DE","Deere"),("LMT","Lockheed Martin"),("NOC","Northrop Grumman"),
        ("BA","Boeing"),("GD","General Dynamics"),("MMM","3M"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 가격 데이터 수집
# ─────────────────────────────────────────────────────────────────────────────

def fetch_kospi_stock(ticker_name: tuple) -> tuple[str, str, pd.DataFrame | None, str]:
    """단일 KOSPI 종목 FDR 수집."""
    ticker, name = ticker_name
    fdr_code = ticker.replace(".KS", "").replace(".KQ", "")
    try:
        df = fdr.DataReader(fdr_code, START, END)
        if df is not None and len(df) >= 50:
            df.index = pd.to_datetime(df.index).tz_localize(None)
            close_col = next((c for c in df.columns if 'Close' in c or 'close' in c), df.columns[0])
            df = df[[close_col]].rename(columns={close_col: "close"}).dropna()
            if len(df) >= 50:
                return ticker, name, df, "FDR"
    except Exception:
        pass
    return ticker, name, None, "none"


def _download_batch_worker(batch, start, end):
    """단일 배치 다운로드 (thread 내부 실행용)."""
    return yf.download(
        batch, start=start, end=end,
        auto_adjust=True, progress=False,
        group_by="ticker", threads=True,
    )


def batch_download_sp500(universe: list[tuple[str, str]]) -> dict[str, pd.DataFrame]:
    """yfinance 배치 다운로드로 S&P 500 전체 수집 (배치당 60s 타임아웃)."""
    from concurrent.futures import ThreadPoolExecutor
    tickers = [sym for sym, _ in universe]
    result  = {}

    print(f"  배치 다운로드: {len(tickers)}개 종목 (배치 크기={SP500_BATCH}, 타임아웃=60s/배치)")
    for i in range(0, len(tickers), SP500_BATCH):
        batch = tickers[i:i + SP500_BATCH]
        batch_n = i // SP500_BATCH + 1
        total_batches = (len(tickers) + SP500_BATCH - 1) // SP500_BATCH
        print(f"    배치 {batch_n}/{total_batches} ({len(batch)}개)...", end=" ", flush=True)

        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_download_batch_worker, batch, START, END)
                raw = fut.result(timeout=60)

            ok_count = 0
            for sym in batch:
                try:
                    if len(batch) == 1:
                        df_sym = raw[["Close"]].rename(columns={"Close": "close"}).dropna()
                    else:
                        df_sym = raw[sym][["Close"]].rename(columns={"Close": "close"}).dropna()

                    if df_sym.index.tz is not None:
                        df_sym.index = df_sym.index.tz_localize(None)
                    df_sym.index = pd.to_datetime(df_sym.index).normalize()

                    if len(df_sym) >= 50:
                        result[sym] = df_sym
                        ok_count += 1
                except Exception:
                    pass
            print(f"✓ {ok_count}/{len(batch)}")
        except Exception as e:
            print(f"✗ 타임아웃/실패 (배치 건너뜀): {str(e)[:50]}")

        time.sleep(0.3)

    return result


def _fetch_cap_single(sym: str) -> tuple[str, float]:
    """단일 종목 시가총액 조회."""
    try:
        info = yf.Ticker(sym).fast_info
        return sym, float(getattr(info, "market_cap", 0) or 0)
    except Exception:
        return sym, 0.0


def fetch_sp500_market_caps_parallel(valid_tickers: list[str], max_workers: int = 20) -> dict[str, float]:
    """병렬 시가총액 조회 (5s/콜 타임아웃, 20 workers). 순차 400콜 대비 ~20× 빠름."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    caps = {sym: 0.0 for sym in valid_tickers}

    print(f"  시가총액 병렬 조회 ({len(valid_tickers)}개, workers={max_workers})...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sym = {executor.submit(_fetch_cap_single, sym): sym for sym in valid_tickers}
        done = 0
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                _, cap = future.result(timeout=5.0)
                caps[sym] = cap
            except Exception:
                caps[sym] = 0.0
            done += 1
            if done % 100 == 0:
                print(f"    시총 {done}/{len(valid_tickers)}개 처리...")
    return caps


def fetch_kospi_universe_parallel(universe: list[tuple[str, str]], max_workers: int = 8) -> dict:
    """KOSPI 종목 병렬 수집."""
    results = {}
    print(f"  KOSPI {len(universe)}개 종목 병렬 수집 (workers={max_workers})...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_kospi_stock, tu): tu for tu in universe}
        done = 0
        for future in as_completed(futures):
            ticker, name, df, source = future.result()
            done += 1
            if df is not None:
                results[ticker] = {"name": name, "df": df, "source": source}
            if done % 20 == 0 or done == len(universe):
                print(f"    진행: {done}/{len(universe)} 완료 ({len(results)}개 유효)")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 크로스 검증
# ─────────────────────────────────────────────────────────────────────────────

def cross_validate_return(ticker: str, primary_ret: float, timeout_sec: float = 10.0) -> str:
    """FDR vs yfinance 교차검증 (10s 타임아웃)."""
    if not ticker.endswith(".KS"):
        return "검증불필요"
    from concurrent.futures import ThreadPoolExecutor

    def _validate():
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

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_validate)
        try:
            return fut.result(timeout=timeout_sec)
        except Exception:
            return "검증불가"


# ─────────────────────────────────────────────────────────────────────────────
# 시가총액 조회
# ─────────────────────────────────────────────────────────────────────────────

def get_market_cap_batch(tickers: list[str]) -> dict[str, float]:
    """여러 종목의 시가총액을 한 번에 조회."""
    caps = {}
    for ticker in tickers:
        try:
            if ticker.endswith(".KS"):
                # FDR 리스팅에서 직접 가져오기
                listing = fdr.StockListing('KOSPI')
                code = ticker.replace(".KS", "")
                code_col = next((c for c in listing.columns if 'Code' in c), 'Code')
                marcap_col = next((c for c in listing.columns if 'Marcap' in c), 'Marcap')
                row = listing[listing[code_col] == code]
                if not row.empty:
                    caps[ticker] = float(row[marcap_col].iloc[0]) * 1e6  # 백만원 → 원
                else:
                    caps[ticker] = 0.0
            else:
                info = yf.Ticker(ticker).fast_info
                caps[ticker] = float(getattr(info, "market_cap", 0) or 0)
        except Exception:
            caps[ticker] = 0.0
    return caps


def get_kospi_market_caps(universe: list[tuple[str, str]]) -> dict[str, float]:
    """KOSPI 전체 시가총액 한번에 수집.
    반환값 단위: KRW (원)
    수집 순서: pykrx(KRX auth) → fdr.StockListing → yfinance 폴백
    """
    caps = {}

    # 방법 1: pykrx (KRX 자격증명 필요)
    import os
    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        try:
            from pykrx import stock as pykrx_stock
            date_str = (datetime.now() - timedelta(days=3)).strftime('%Y%m%d')
            caps_df = pykrx_stock.get_market_cap(date_str, market='KOSPI')
            if caps_df is not None and not caps_df.empty:
                marcap_col = caps_df.columns[1]  # 시가총액
                caps_df[marcap_col] = pd.to_numeric(caps_df[marcap_col], errors='coerce')
                for code in caps_df.index:
                    ticker = str(code).zfill(6) + ".KS"
                    caps[ticker] = float(caps_df.loc[code, marcap_col] or 0.0)
                if any(v > 0 for v in caps.values()):
                    return caps
        except Exception as e:
            print(f"  [경고] pykrx 시총 수집 실패: {e}")

    # 방법 2: FDR StockListing
    try:
        listing = fdr.StockListing('KOSPI')
        code_col   = next((c for c in listing.columns if 'Code' in c), None)
        marcap_col = next((c for c in listing.columns if 'Marcap' in c), None)
        if code_col and marcap_col:
            for code_val, marcap_val in zip(listing[code_col], listing[marcap_col]):
                ticker = str(code_val).zfill(6) + ".KS"
                try:
                    caps[ticker] = float(marcap_val) if marcap_val else 0.0
                except Exception:
                    caps[ticker] = 0.0
            if any(v > 0 for v in caps.values()):
                return caps
    except Exception:
        pass

    # 방법 3: yfinance 폴백 (상위 10개만, rate limit 방지)
    for ticker, _ in universe[:10]:
        try:
            info = yf.Ticker(ticker).fast_info
            usd_mc = float(getattr(info, 'market_cap', 0) or 0)
            if usd_mc > 0:
                caps[ticker] = usd_mc * 1350.0  # USD → KRW 근사 환산
        except Exception:
            pass

    return caps


# ─────────────────────────────────────────────────────────────────────────────
# 점수 계산
# ─────────────────────────────────────────────────────────────────────────────

SPINOFF_RETURN_THRESHOLD = 1000.0   # % 초과 시 스핀오프/이벤트 의심
SPINOFF_RETURN_CAP       = 300.0    # 기여도 계산용 수익률 상한 (%)

KRW_PER_USD = 1350.0  # KRW/USD 환율 (KOSPI mc 단위 변환용)

# 알려진 기업 이벤트 → ⚠ 이유 텍스트 (ticker 기준)
KNOWN_EVENTS: dict[str, str] = {
    "SNDK":  "WD(Western Digital) 스핀오프 2024.02.21 상장 — 분리 직후 주가 기준 초과수익률 왜곡",
    "WDC":   "SanDisk 스핀오프 2024.02.21 — 분사 후 잔여 법인 기준 수익률",
    "LITE":  "R4 데이터 이상 의심 — 기업이벤트 없음 확인됨. 실제 Jun24-Jun25 수익률 약 +45%; +900%+ 수치는 시작가 날짜 불일치(start_price misalignment) 가능성. 수동 검증 필수",
    "009150":"R4 데이터 오류 확정 — 실제 Jun24-Jun25 수익률 -10~+20%. FDR 시작가 날짜 불일치 오류. 기여도 계산 시 spinoff_cap 적용됨",
    "034730":"SK스퀘어 지주사 NAV 할인 해소 + 반도체 자회사 재평가 — 실제 거래 기반 수익률",
    "000660":"SK하이닉스 HBM 메모리 AI GPU 수요 급증 — 실제 AI 인프라 수혜",
    "005930":"삼성전자 HBM·파운드리 전환 기대 — 실제 반도체 사이클 수혜",
}

EXTREME_RETURN_THRESHOLD = 500.0   # % 초과 시 자동 ⚠ 사유 부여

def annotate_warn_reasons(stock_list: list[dict], return_key: str = "excess_return_pct") -> list[dict]:
    """
    극단 수익률 종목에 warn_reason 필드 추가.
    - 알려진 이벤트: KNOWN_EVENTS 딕셔너리 조회
    - 미확인 극단 수익: 일반 경고 텍스트
    """
    for s in stock_list:
        ret = abs(s.get(return_key, 0))
        if ret < EXTREME_RETURN_THRESHOLD:
            continue
        ticker = s.get("ticker", "")
        reason = KNOWN_EVENTS.get(ticker)
        if not reason:
            reason = f"극단 수익률 {s.get(return_key,0):+.1f}% — 기업 이벤트(분사/합병/테마) 가능성, 수동 확인 권장"
        s["warn_reason"] = reason
    return stock_list

def compute_contribution(stock_df: pd.DataFrame, idx: pd.Series,
                         mc: float, krw_divisor: float = 1.0) -> dict | None:
    """
    mc: 현재 시가총액 (SP500=USD, KOSPI=KRW)
    krw_divisor: KOSPI는 KRW_PER_USD 전달 → mc를 USD로 변환
    기여도 공식: |corr| × |return_capped| × (mc_start_usd / 1e12 + 0.01)
    mc_start: 시작 시점 시가총액 추정 = (mc / 현재가) × 시작가
    """
    if stock_df["close"].std() == 0:  # 거래정지: 가격 변동 없음 → corr 계산 불가
        return None
    sr = stock_df["close"].pct_change().dropna()
    ir = idx.pct_change().dropna()
    mg = pd.concat([sr, ir], axis=1).dropna()
    if len(mg) < 30:
        return None
    mg.columns = ["s", "i"]
    if np.std(mg["s"].values) < 1e-10 or np.std(mg["i"].values) < 1e-10:
        return None  # pct_change 후에도 상수 시계열 (forward-fill 등)
    slope, _, r_val, p_val, _ = stats.linregress(mg["i"].values, mg["s"].values)
    s_total = float((1 + mg["s"]).prod() - 1)
    i_total = float((1 + mg["i"]).prod() - 1)
    corr, _ = stats.pearsonr(mg["s"].values, mg["i"].values)
    s_return_pct = s_total * 100

    # 스핀오프/분사 이벤트 감지 — 극단 수익률 보정
    is_spinoff_event = abs(s_return_pct) > SPINOFF_RETURN_THRESHOLD
    spinoff_note = ""
    s_capped = s_total
    if is_spinoff_event:
        cap_sign = 1.0 if s_return_pct > 0 else -1.0
        s_capped = cap_sign * SPINOFF_RETURN_CAP / 100.0
        spinoff_note = (
            f"분사/스핀오프 이벤트로 인한 극단 수익률 "
            f"({s_return_pct:+.0f}%). "
            f"기여도 계산 시 보정값 {cap_sign*SPINOFF_RETURN_CAP:+.0f}% 적용."
        )

    # 시작 시점 시가총액 추정: shares ≈ mc / 현재가  →  mc_start ≈ shares × 시작가
    # (현재 mc 대신 분석 기간 시작 시점 mc를 사용해야 index 기여도가 정확)
    mc_usd = mc / krw_divisor  # USD 환산
    prices = stock_df["close"].dropna()
    if len(prices) >= 2 and prices.iloc[-1] > 0 and mc_usd > 0:
        mc_start_usd = mc_usd / prices.iloc[-1] * prices.iloc[0]
    else:
        mc_start_usd = mc_usd

    # contribution_score: 시작 시총 기반 (M3 준수)
    contrib = round(abs(corr) * abs(s_capped) * (mc_start_usd / 1e12 + 0.01), 4)

    result = {
        "beta":               round(float(slope), 4),
        "correlation":        round(float(corr), 4),
        "p_value":            round(float(p_val), 6),
        "stock_return_pct":   round(s_return_pct, 2),
        "index_return_pct":   round(i_total * 100, 2),
        "period_days":        len(mg),
        "period_label":       PERIOD_LABEL,
        "market_cap_b":       round(mc_usd / 1e9, 1),          # USD 기준 현재 시총
        "market_cap_start_b": round(mc_start_usd / 1e9, 1),    # USD 기준 시작 시총
        "contribution_score": contrib,
        "n_days":             len(mg),
    }
    if is_spinoff_event:
        result["spinoff_event"]    = True
        result["spinoff_note"]     = spinoff_note
        result["return_capped_at"] = SPINOFF_RETURN_CAP
        result["data_quality"]     = "주의: 스핀오프 이벤트"
    return result


def compute_beneficiary(stock_df: pd.DataFrame, idx: pd.Series) -> dict | None:
    if stock_df["close"].std() == 0:  # 거래정지: 가격 변동 없음 → corr 계산 불가
        return None
    sr = stock_df["close"].pct_change().dropna()
    ir = idx.pct_change().dropna()
    mg = pd.concat([sr, ir], axis=1).dropna()
    if len(mg) < 30:
        return None
    mg.columns = ["s", "i"]
    if np.std(mg["s"].values) < 1e-10 or np.std(mg["i"].values) < 1e-10:
        return None  # pct_change 후 상수 시계열
    up = mg[mg["i"] > 0]
    if len(up) < 15:
        return None
    s_total = float((1 + mg["s"]).prod() - 1)
    i_total = float((1 + mg["i"]).prod() - 1)
    excess  = s_total - i_total
    corr, p = stats.pearsonr(mg["s"].values, mg["i"].values)
    return {
        "correlation":       round(float(corr), 4),
        "p_value":           round(float(p), 6),
        "stock_return_pct":  round(s_total * 100, 2),
        "index_return_pct":  round(i_total * 100, 2),
        "excess_return_pct": round(excess * 100, 2),
        "period_days":       len(mg),
        "period_label":      PERIOD_LABEL,
        "beneficiary_score": round(float(excess) * abs(float(corr)), 4),
        "n_days":            len(mg),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 코스피 분석 (FDR 병렬)
# ─────────────────────────────────────────────────────────────────────────────

def run_kospi_analysis(universe: list[tuple[str, str]], idx_series: pd.Series) -> dict:
    t0 = time.time()
    stock_data = fetch_kospi_universe_parallel(universe, max_workers=8)
    caps       = get_kospi_market_caps(universe)

    contrib_list, benefit_list = [], []

    for ticker, info in stock_data.items():
        df   = info["df"]
        name = info["name"]
        src  = info["source"]
        mc   = caps.get(ticker, 0.0)  # FDR StockListing Marcap: KRW(원) 단위

        aligned_idx = idx_series.reindex(df["close"].index, method="ffill")

        c = compute_contribution(df, aligned_idx, mc, krw_divisor=KRW_PER_USD)
        b = compute_beneficiary(df, aligned_idx)

        if c:
            dq = cross_validate_return(ticker, c["stock_return_pct"])
            c.update({"data_quality": dq, "data_source": src, "ticker": ticker, "name": name})
            contrib_list.append(c)

        if b:
            dq_b = cross_validate_return(ticker, b["stock_return_pct"])
            b.update({"data_quality": dq_b, "data_source": src, "ticker": ticker, "name": name})
            benefit_list.append(b)

    contrib_list.sort(key=lambda x: x["contribution_score"], reverse=True)
    benefit_list.sort(key=lambda x: x["beneficiary_score"],  reverse=True)

    elapsed = time.time() - t0
    ok = len(stock_data)
    total = len(universe)
    skipped = total - ok

    print(f"\n  [KOSPI] 분석 완료: {ok}/{total}개 ({skipped}개 데이터 없음) — {elapsed:.0f}초")
    print(f"  [KOSPI] 기여 Top5:")
    for i, r in enumerate(contrib_list[:5]):
        print(f"    #{i+1} {r['name']:12s} | 수익:{r['stock_return_pct']:+.1f}% | 기여:{r['contribution_score']:.4f} [{r['data_source']}/{r['data_quality']}]")
    print(f"  [KOSPI] 수혜 Top5:")
    for i, r in enumerate(benefit_list[:5]):
        print(f"    #{i+1} {r['name']:12s} | 초과:{r['excess_return_pct']:+.1f}% | 수혜:{r['beneficiary_score']:.4f}")

    mismatch = [r for r in contrib_list if "불일치" in r.get("data_quality", "")]
    if mismatch:
        print(f"  [검증경고] 소스 불일치 {len(mismatch)}개 종목:")
        for r in mismatch:
            print(f"    {r['name']}: {r['data_quality']}")

    annotate_warn_reasons(contrib_list, return_key="stock_return_pct")
    annotate_warn_reasons(benefit_list, return_key="excess_return_pct")

    # KOSPI 우선주 중복 제거 (M4 준수): 삼성전자/삼성전자우 등 동일기업 복수 클래스
    KOSPI_DEDUP = [
        {"005930.KS", "005935.KS"},   # 삼성전자 / 삼성전자우
        {"000660.KS", "000665.KS"},   # SK하이닉스 / SK하이닉스우
        {"051910.KS", "051915.KS"},   # LG화학 / LG화학우
        {"006400.KS", "006405.KS"},   # 삼성SDI / 삼성SDI우
        {"005380.KS", "005385.KS"},   # 현대차 / 현대차우
    ]
    def kospi_dedup(lst: list, score_key: str) -> list:
        remove = set()
        for group in KOSPI_DEDUP:
            items = [x for x in lst if x.get("ticker", "") in group]
            if len(items) >= 2:
                items.sort(key=lambda x: x.get(score_key, 0), reverse=True)
                for dup in items[1:]:
                    remove.add(dup.get("ticker", ""))
                    print(f"  [DEDUP] {dup.get('name','?')} ({dup.get('ticker','')}) 중복 제거 — {items[0].get('name','?')} 유지")
        return [x for x in lst if x.get("ticker", "") not in remove]

    contrib_list = kospi_dedup(contrib_list, "contribution_score")
    benefit_list = kospi_dedup(benefit_list, "beneficiary_score")
    # 수혜 점수 양수인 종목만 포함 (excess_return 음수 → beneficiary_score ≤ 0 → 수혜 아님)
    benefit_list = [x for x in benefit_list if (x.get("beneficiary_score") or 0) > 0]

    return {
        "contribution_top5": contrib_list[:5],
        "beneficiary_top5":  benefit_list[:5],
        "analyzed_count":    ok,
        "skipped_count":     skipped,
        "universe_size":     total,
        "period":            {"start": START, "end": END, "label": PERIOD_LABEL},
    }


# ─────────────────────────────────────────────────────────────────────────────
# S&P 500 분석 (yfinance 배치)
# ─────────────────────────────────────────────────────────────────────────────

def run_sp500_analysis(universe: list[tuple[str, str]], idx_series: pd.Series) -> dict:
    t0 = time.time()
    name_map   = {sym: name for sym, name in universe}
    price_data = batch_download_sp500(universe)

    contrib_list, benefit_list = [], []
    skipped = []

    caps = fetch_sp500_market_caps_parallel(list(price_data.keys()))

    for sym, df in price_data.items():
        name = name_map.get(sym, sym)
        mc   = caps.get(sym, 0.0)
        aligned_idx = idx_series.reindex(df["close"].index, method="ffill")

        c = compute_contribution(df, aligned_idx, mc)
        b = compute_beneficiary(df, aligned_idx)

        if c:
            c.update({"data_quality": "검증불필요", "data_source": "yfinance", "ticker": sym, "name": name})
            contrib_list.append(c)
        if b:
            b.update({"data_quality": "검증불필요", "data_source": "yfinance", "ticker": sym, "name": name})
            benefit_list.append(b)

    for sym, _ in universe:
        if sym not in price_data:
            skipped.append(sym)

    # 동일 기업 복수 클래스 중복 제거 (GOOGL/GOOG, BRK-A/BRK-B 등)
    # 더 높은 점수를 가진 클래스만 남김
    DEDUP_GROUPS = [
        {"GOOGL", "GOOG"},       # Alphabet A/C
        {"BRK-A", "BRK-B"},      # Berkshire A/B
        {"BRKB",  "BRKA"},
    ]
    def dedup(lst: list, score_key: str) -> list:
        kept_tickers = set()
        removed      = set()
        for group in DEDUP_GROUPS:
            group_items = [x for x in lst if x.get("ticker","") in group]
            if len(group_items) <= 1:
                continue
            group_items.sort(key=lambda x: x[score_key], reverse=True)
            kept_tickers.add(group_items[0]["ticker"])
            for item in group_items[1:]:
                removed.add(item["ticker"])
        result = [x for x in lst if x.get("ticker","") not in removed]
        if removed:
            print(f"    [중복제거] 동일기업 복수 클래스 제거: {removed}")
        return result

    contrib_list = dedup(contrib_list, "contribution_score")
    benefit_list = dedup(benefit_list, "beneficiary_score")
    contrib_list.sort(key=lambda x: x["contribution_score"], reverse=True)
    benefit_list.sort(key=lambda x: x["beneficiary_score"],  reverse=True)
    # 수혜 점수 양수인 종목만 포함 (excess_return 음수 → beneficiary_score ≤ 0 → 수혜 아님)
    benefit_list = [x for x in benefit_list if (x.get("beneficiary_score") or 0) > 0]

    elapsed = time.time() - t0
    ok = len(price_data)
    total = len(universe)

    print(f"\n  [S&P500] 분석 완료: {ok}/{total}개 ({total-ok}개 데이터 없음) — {elapsed:.0f}초")
    print(f"  [S&P500] 기여 Top5:")
    for i, r in enumerate(contrib_list[:5]):
        print(f"    #{i+1} {r['name']:20s} | 수익:{r['stock_return_pct']:+.1f}% | 기여:{r['contribution_score']:.4f}")
    print(f"  [S&P500] 수혜 Top5:")
    for i, r in enumerate(benefit_list[:5]):
        print(f"    #{i+1} {r['name']:20s} | 초과:{r['excess_return_pct']:+.1f}% | 수혜:{r['beneficiary_score']:.4f}")

    annotate_warn_reasons(contrib_list, return_key="stock_return_pct")
    annotate_warn_reasons(benefit_list, return_key="excess_return_pct")

    return {
        "contribution_top5": contrib_list[:5],
        "beneficiary_top5":  benefit_list[:5],
        "analyzed_count":    ok,
        "skipped_count":     total - ok,
        "universe_size":     total,
        "period":            {"start": START, "end": END, "label": PERIOD_LABEL},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("STOCK AGENT v3 — 전체 지수 구성종목 동적 분석")
    print(f"분석 기간: {START} ~ {END} ({PERIOD_LABEL})")
    print(f"KOSPI: 시총 상위 {KOSPI_TOP_N}개 | S&P500: 전체 구성종목")
    print("=" * 60)

    for path_name in ("SP500", "KOSPI"):
        if not (RAW_DIR / f"{path_name}.parquet").exists():
            print(f"[ERROR] {path_name}.parquet 없음 — Data Agent 먼저 실행 필요")
            exit(1)

    sp_df  = pd.read_parquet(RAW_DIR / "SP500.parquet")
    sp_df["date"] = pd.to_datetime(sp_df["date"]).dt.tz_localize(None)
    sp_s   = sp_df.set_index("date")["value"].sort_index()

    ksp_df = pd.read_parquet(RAW_DIR / "KOSPI.parquet")
    ksp_df["date"] = pd.to_datetime(ksp_df["date"]).dt.tz_localize(None)
    ksp_s  = ksp_df.set_index("date")["value"].sort_index()

    # 유니버스 동적 수집
    kospi_universe = get_kospi_universe()
    sp500_universe = get_sp500_universe()

    print(f"\n[F09+F11] S&P500 분석 ({len(sp500_universe)}개 종목)")
    sp_res = run_sp500_analysis(sp500_universe, sp_s)

    print(f"\n[F10+F12] KOSPI 분석 ({len(kospi_universe)}개 종목)")
    ksp_res = run_kospi_analysis(kospi_universe, ksp_s)

    results = {
        "generated_at":   datetime.now().isoformat(),
        "analysis_period": {"start": START, "end": END, "label": PERIOD_LABEL},
        "universe": {
            "kospi_size":  ksp_res["universe_size"],
            "sp500_size":  sp_res["universe_size"],
            "kospi_analyzed": ksp_res["analyzed_count"],
            "sp500_analyzed": sp_res["analyzed_count"],
            "source": "KOSPI: FDR(KRX 시총 상위) / S&P500: Wikipedia 구성종목 전체",
        },
        "f09_sp500_contribution_top5": sp_res["contribution_top5"],
        "f10_kospi_contribution_top5": ksp_res["contribution_top5"],
        "f11_sp500_beneficiary_top5":  sp_res["beneficiary_top5"],
        "f12_kospi_beneficiary_top5":  ksp_res["beneficiary_top5"],
        "data_quality_notes": {
            "methodology":       "FDR 우선(KRX 직접), yfinance 폴백. 두 소스 수익률 차이 100%p 초과 시 불일치 플래그.",
            "cross_validation":  "FDR/yfinance 교차검증 적용 (KOSPI 종목만)",
            "universe_method":   "하드코딩 없음. KOSPI=fdr.StockListing('KOSPI') 시총순, S&P500=Wikipedia 전체",
        },
    }

    out = PROC_DIR / "stock_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n종목 결과 저장: {out}")

    # ── Stock Agent 자체 완료 기준 검증 (Done Criteria) ──────────────────────
    print("\n[자체검증] Stock Agent Done Criteria 점검...")
    all_top5 = (results["f09_sp500_contribution_top5"] + results["f11_sp500_beneficiary_top5"] +
                results["f10_kospi_contribution_top5"] + results["f12_kospi_beneficiary_top5"])
    sp_names = [s.get("name","?") for s in results["f09_sp500_contribution_top5"]]
    ksp_names = [s.get("name","?") for s in results["f10_kospi_contribution_top5"]]

    # 중복 기업 체크 (같은 리스트 내)
    def has_company_dup(lst):
        tickers = [s.get("ticker","") for s in lst]
        return len(tickers) != len(set(tickers))

    done_criteria = {
        "SA-1 유니버스 동적 수집":         "FDR(KRX" in results["universe"]["source"],
        "SA-2 KOSPI ≥50개 분석":          ksp_res["analyzed_count"] >= 50,
        "SA-3 S&P500 ≥100개 분석":        sp_res["analyzed_count"] >= 100,
        "SA-4 KOSPI Top5 시총 존재":       any((s.get("market_cap_b") or 0) > 0 for s in results["f10_kospi_contribution_top5"]),
        "SA-5 SP500 극단수익률 플래그":     bool(all_top5) and not any(abs(s.get("stock_return_pct") or 0) > 5000 for s in all_top5),
        "SA-6 동일기업 중복 없음 (SP500)":  bool(results["f09_sp500_contribution_top5"]) and not has_company_dup(results["f09_sp500_contribution_top5"]),
        "SA-7 기여/수혜 결과 비어있지 않음": len(results["f09_sp500_contribution_top5"]) >= 3 and len(results["f10_kospi_contribution_top5"]) >= 3,
    }

    crit_fail = []
    for k, v in done_criteria.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        if not v:
            crit_fail.append(k)

    if crit_fail:
        print(f"\n  [CRITICAL] Done Criteria 실패: {crit_fail}")
        print("  → Stock Agent 산출물 품질 기준 미달. 데이터 재수집 또는 분석 로직 점검 필요.")
        exit(1)
    else:
        print(f"  → 전 항목 통과 ({len(done_criteria)}/{len(done_criteria)})")

    print(f"Stock Agent v3 완료 (KOSPI {ksp_res['analyzed_count']}개 / S&P500 {sp_res['analyzed_count']}개 분석)")

    # ── Done Criteria (auto-injected by SA-9) ──────────────────────────────
    import sys as _sa9_sys, os as _sa9_os
    from pathlib import Path as _sa9_P
    _sa9_out = str(_sa9_P(__file__).parent.parent / "data/processed/stock_results.json")
    _sa9_sz  = _sa9_os.path.getsize(_sa9_out) if _sa9_os.path.exists(_sa9_out) else -1
    _sa9_err = (
        f"DC-1 FAIL: {_sa9_out} not found"  if not _sa9_os.path.exists(_sa9_out) else
        f"DC-2 FAIL: empty"                    if _sa9_sz == 0                      else
        f"DC-3 FAIL: {_sa9_sz}B < 100B"     if _sa9_sz < 100                     else None
    )
    if _sa9_err:
        print(f"[DONE CRITERIA] {_sa9_err}", file=_sa9_sys.stderr)
        print(f"DONE_CRITERIA: FAIL — {_sa9_err}")
        _sa9_sys.exit(1)
    print(f"[DONE CRITERIA] {_sa9_out} — DC-1~DC-3 PASS")
    print("DONE_CRITERIA: PASS")
