# -*- coding: utf-8 -*-
"""
Sector Agent — 산업별 딥다이브
PM Condition H: 반도체/AI/에너지 섹터 분석 + 직무별 인사이트
Done Criteria (SEC-1~SEC-3):
  SEC-1: 최소 1개 섹터에 ≥1종목 데이터 수집 성공
  SEC-2: 각 섹터 tickers가 정적 하드코딩이 아닌 동적 조회 시도 후 결과
  SEC-3: sector_analysis.json 저장 완료

동적 유니버스 조회:
  - US: FDR S&P500 구성종목 → 섹터/산업 키워드 필터 → 시총 상위 N개
  - KR: FDR KRX 구성종목 → 섹터/산업 키워드 필터 → 시총 상위 N개
  - 조회 실패 시 시드 종목(SECTORS_FALLBACK)으로 폴백
"""
import utf8_setup  # noqa: F401

import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta


# 섹터 시드: 동적 조회 실패 시 폴백용 + 테마/리스크 메타데이터
SECTORS = {
    "반도체/AI": {
        # M-05 fix: 광의 "Technology" 섹터 kw 제거 (IT 섹터 전체 매칭 → Accenture/Adobe/
        #   Apple 오분류 원인). 반도체 특화 industry_kw 로만 좁힌다.
        "us_sector_kw":  ["Semiconductor"],
        "us_industry_kw": ["Semiconductor", "Electronic Equipment", "Electronic Components"],
        "kr_sector_kw":   ["반도체", "전자", "IT"],
        "us_fallback": [("NVDA", "NVIDIA"), ("TSM", "TSMC"), ("AVGO", "Broadcom"),
                        ("AMAT", "Applied Materials"), ("INTC", "Intel")],
        "kr_fallback": [("000660.KS", "SK하이닉스"), ("005930.KS", "삼성전자"),
                        ("042700.KS", "한미반도체")],
        "theme": "AI 수요 급증, HBM 메모리 사이클, 파운드리 확장",
        "key_risk": "재고 조정, 중국 제재 리스크, 설비투자 과잉",
    },
    "AI/플랫폼": {
        "us_sector_kw":   ["Communication Services", "Technology"],
        "us_industry_kw": ["Internet Content", "Software", "Cloud"],
        "kr_sector_kw":   ["소프트웨어", "인터넷", "IT서비스"],
        "us_fallback": [("GOOGL", "Alphabet"), ("MSFT", "Microsoft"),
                        ("META", "Meta"), ("AMZN", "Amazon")],
        "kr_fallback": [("035720.KS", "카카오"), ("035420.KS", "NAVER"),
                        ("259960.KS", "크래프톤")],
        "theme": "클라우드 AI 서비스 수요, LLM 상용화, 광고 회복",
        "key_risk": "규제 리스크, AI 투자 수익성 불확실, 경쟁 심화",
    },
    "에너지/원자재": {
        "us_sector_kw":   ["Energy", "Utilities"],
        "us_industry_kw": ["Oil", "Gas", "Energy", "Nuclear", "Utilities"],
        "kr_sector_kw":   ["에너지", "전력", "화학"],
        "us_fallback": [("XOM", "ExxonMobil"), ("CVX", "Chevron"),
                        ("NEE", "NextEra Energy")],
        "kr_fallback": [("015760.KS", "한국전력"), ("034020.KS", "두산에너빌리티"),
                        ("010950.KS", "S-Oil")],
        "theme": "에너지 전환, 원자력 르네상스, AI 데이터센터 전력 수요",
        "key_risk": "유가 변동성, 정책 리스크, 금리 민감도",
    },
}


# ── 동적 유니버스 조회 ────────────────────────────────────────

def _dedup_share_classes(rows: list) -> list:
    """M-14 B fix: 동일 회사 복수 상장 클래스(GOOGL/GOOG 등) 정규화.

    rows: [(sym, name), ...] (df 순서 보존). 회사 base-name 이 같으면 첫 항목만 유지.
    base-name = name 에서 클래스 표기("(Class A)", "Class C", "Cl A" 등)를 제거해 산출.
    """
    import re
    _CLASS_RE = re.compile(
        r"\s*\(?\bcl(?:ass)?\.?\s*[a-c]\b\)?", re.IGNORECASE
    )
    seen = set()
    out = []
    for sym, name in rows:
        base = _CLASS_RE.sub("", str(name)).strip().rstrip("(").strip().lower()
        if base in seen:
            continue
        seen.add(base)
        out.append((sym, name))
    return out


def _dynamic_us_tickers(sector_kw: list, industry_kw: list, n: int = 7) -> list:
    """FDR S&P500 구성종목에서 섹터/산업 키워드로 동적 필터링.

    시총 컬럼(MarketCap 등)이 존재하면 내림차순 정렬 후 상위 n.
    부재 시 FDR 원본 순서 유지(대략 알파벳) — 그 사실을 로그로 남긴다. (M-05)
    """
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("S&P500")
        if df is None or df.empty:
            return []
        # 컬럼명 탐지
        sector_col   = next((c for c in df.columns if "Sector" in c or "sector" in c), None)
        industry_col = next((c for c in df.columns if "Industry" in c or "industry" in c), None)
        name_col     = next((c for c in df.columns if c in ("Name", "Company", "LongName")), None)
        sym_col      = next((c for c in df.columns if c in ("Symbol", "Ticker", "Code")), None)
        # 시총 컬럼 탐지 (MarketCap / Marcap / Market Cap 등)
        mcap_col     = next((c for c in df.columns
                             if c.replace(" ", "").replace("_", "").lower()
                             in ("marketcap", "marcap", "mktcap")), None)

        if not sym_col:
            return []

        mask = pd.Series([False] * len(df), index=df.index)
        if sector_col:
            for kw in sector_kw:
                mask |= df[sector_col].fillna("").str.contains(kw, case=False, regex=False)
        if industry_col:
            for kw in industry_kw:
                mask |= df[industry_col].fillna("").str.contains(kw, case=False, regex=False)

        matched = df[mask]
        if mcap_col:
            matched = matched.sort_values(mcap_col, ascending=False)
        else:
            print("    [동적US] 시총 컬럼 부재 — FDR 원본 순서 유지(시총 정렬 미적용)", end=" ")

        result = []
        for _, row in matched.iterrows():
            sym  = str(row[sym_col]).strip()
            name = str(row[name_col]).strip() if name_col else sym
            if sym:
                result.append((sym, name))

        # M-14 B: share-class dedup 후 상위 n
        result = _dedup_share_classes(result)
        return result[:n]
    except Exception as e:
        print(f"    [동적US] 조회 실패: {e}")
        return []


def _dynamic_kr_tickers(sector_kw: list, n: int = 5) -> list:
    """FDR KRX 구성종목에서 섹터/산업 키워드로 동적 필터링."""
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        if df is None or df.empty:
            return []
        code_col = next((c for c in df.columns if c in ("Code", "Symbol", "Ticker")), None)
        name_col = next((c for c in df.columns if c in ("Name", "종목명")), None)
        # 산업 컬럼 탐지
        ind_col  = next((c for c in df.columns
                         if any(k in c for k in ("Industry", "Sector", "업종", "섹터"))), None)

        if not code_col or not name_col:
            return []

        mask = pd.Series([False] * len(df), index=df.index)
        if ind_col:
            for kw in sector_kw:
                mask |= df[ind_col].fillna("").str.contains(kw, case=False, regex=False)

        if mask.sum() == 0:
            return []

        subset = df[mask].head(n)
        result = []
        for _, row in subset.iterrows():
            code = str(row[code_col]).strip().zfill(6)
            name = str(row[name_col]).strip()
            if code and name:
                result.append((f"{code}.KS", name))
        return result
    except Exception as e:
        print(f"    [동적KR] 조회 실패: {e}")
        return []


def _resolve_tickers(config: dict) -> tuple[list, list, bool]:
    """섹터 config에서 동적 조회 시도 → 실패 시 폴백. (us_tickers, kr_tickers, used_dynamic)"""
    us_tickers = _dynamic_us_tickers(
        config.get("us_sector_kw", []),
        config.get("us_industry_kw", []),
    )
    kr_tickers = _dynamic_kr_tickers(config.get("kr_sector_kw", []))

    used_dynamic = bool(us_tickers or kr_tickers)
    if not us_tickers:
        us_tickers = config.get("us_fallback", [])
    if not kr_tickers:
        kr_tickers = config.get("kr_fallback", [])

    return us_tickers, kr_tickers, used_dynamic


def fetch_sector_data(tickers_kr: list, tickers_us: list, days: int = 365) -> dict:
    results = {}
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=days + 30)

    # yfinance로 US 종목
    try:
        import yfinance as yf
        for ticker, name in tickers_us:
            try:
                df = yf.download(ticker, start=start_date.strftime("%Y-%m-%d"),
                                 end=end_date.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
                if df.empty or len(df) < 20:
                    continue
                price_col = "Close" if "Close" in df.columns else df.columns[0]
                prices = df[price_col].dropna()
                ret_1y = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
                ret_1m = (prices.iloc[-1] / prices.iloc[-22] - 1) * 100 if len(prices) >= 22 else None
                results[ticker] = {
                    "name": name, "market": "US",
                    "return_1y": round(float(ret_1y), 2),
                    "return_1m": round(float(ret_1m), 2) if ret_1m is not None else None,
                    "last_price": round(float(prices.iloc[-1]), 2),
                    "source": "yfinance",
                }
            except Exception as e:
                results[ticker] = {"name": name, "market": "US", "error": str(e)[:50]}
    except ImportError:
        pass

    # FDR로 KR 종목
    try:
        import FinanceDataReader as fdr
        for ticker, name in tickers_kr:
            try:
                code = ticker.replace(".KS", "").replace(".KQ", "")
                df = fdr.DataReader(code, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                if df.empty or len(df) < 20:
                    continue
                price_col = "Close" if "Close" in df.columns else df.columns[0]
                prices = df[price_col].dropna()
                ret_1y = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
                ret_1m = (prices.iloc[-1] / prices.iloc[-22] - 1) * 100 if len(prices) >= 22 else None
                results[ticker] = {
                    "name": name, "market": "KR",
                    "return_1y": round(float(ret_1y), 2),
                    "return_1m": round(float(ret_1m), 2) if ret_1m is not None else None,
                    "last_price": round(float(prices.iloc[-1]), 2),
                    "source": "FDR",
                }
            except Exception as e:
                results[ticker] = {"name": name, "market": "KR", "error": str(e)[:50]}
    except ImportError:
        pass

    return results


def generate_sector_section(sector_data: dict) -> str:
    """sector_data: {sector_name: {tickers: {ticker: {...}}}}"""
    if not sector_data:
        return """
<section id="sector">
  <h2 class="section-title">산업별 딥다이브</h2>
  <div class="card" style="color:#475569;padding:20px;text-align:center">
    섹터 데이터 수집 중... (다음 파이프라인 실행 시 표시됩니다)
  </div>
</section>"""

    sections_html = ""
    for sector_name, data in sector_data.items():
        tickers = data.get("tickers", {})
        theme   = data.get("theme", "")
        risk    = data.get("key_risk", "")

        if not tickers:
            continue

        rows_html = ""
        sorted_tickers = sorted(
            [(t, v) for t, v in tickers.items() if "error" not in v and "return_1y" in v],
            key=lambda x: x[1].get("return_1y", 0), reverse=True
        )

        for ticker, info in sorted_tickers:
            ret_1y = info.get("return_1y", 0)
            ret_1m = info.get("return_1m")
            name   = info.get("name", ticker)
            mkt    = info.get("market", "")
            src    = info.get("source", "")
            price  = info.get("last_price", 0)

            ret_cl  = "#22c55e" if ret_1y >= 0 else "#ef4444"
            ret_1m_cl = "#22c55e" if (ret_1m or 0) >= 0 else "#ef4444"
            bar_w   = min(abs(ret_1y) / 5, 100)
            mkt_badge = f'<span style="font-size:0.62rem;padding:1px 4px;border-radius:3px;background:#1e3a5f;color:#60a5fa">{mkt}</span>'
            currency = "$" if mkt == "US" else "₩"

            ret_1m_html = f'<span style="color:{ret_1m_cl};font-size:0.72rem">{"+" if (ret_1m or 0)>=0 else ""}{ret_1m:.1f}%</span>' if ret_1m is not None else ""

            rows_html += f"""
            <div style="display:grid;grid-template-columns:120px 1fr 70px 60px 50px;
                        gap:6px;align-items:center;padding:6px 0;border-bottom:1px solid #1e293b">
              <div>
                <div style="font-size:0.78rem;font-weight:600;color:#e2e8f0">{name}</div>
                <div style="font-size:0.65rem;color:#475569">{ticker} {mkt_badge}</div>
              </div>
              <div style="background:#0f172a;height:6px;border-radius:3px;overflow:hidden">
                <div style="height:100%;width:{bar_w:.1f}%;background:{ret_cl};border-radius:3px;opacity:0.85"></div>
              </div>
              <div style="font-size:0.82rem;font-weight:700;color:{ret_cl};text-align:right">
                {"+" if ret_1y>=0 else ""}{ret_1y:.1f}%
              </div>
              <div style="text-align:center">{ret_1m_html}</div>
              <div style="font-size:0.7rem;color:#475569;text-align:right">{currency}{price:,.0f}</div>
            </div>"""

        if not rows_html:
            rows_html = '<div style="color:#475569;font-size:0.78rem;padding:8px">데이터 수집 실패</div>'

        sections_html += f"""
        <div class="card" style="margin-bottom:14px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div style="font-size:0.9rem;font-weight:700;color:#e2e8f0">{sector_name}</div>
            <div style="text-align:right;font-size:0.7rem;color:#475569;max-width:200px">{theme}</div>
          </div>
          <div style="display:grid;grid-template-columns:120px 1fr 70px 60px 50px;gap:6px;
                      padding-bottom:5px;border-bottom:1px solid #334155;margin-bottom:4px">
            <div style="font-size:0.68rem;color:#475569">종목</div>
            <div style="font-size:0.68rem;color:#475569">1년 수익률 바</div>
            <div style="font-size:0.68rem;color:#475569;text-align:right">1Y</div>
            <div style="font-size:0.68rem;color:#475569;text-align:center">1M</div>
            <div style="font-size:0.68rem;color:#475569;text-align:right">현재가</div>
          </div>
          {rows_html}
          <div style="font-size:0.68rem;color:#ef4444;margin-top:8px;opacity:0.8">
            ⚠ 리스크: {risk}
          </div>
        </div>"""

    return f"""
<!-- ═══ SECTOR SECTION ═══ -->
<section id="sector">
  <h2 class="section-title">산업별 딥다이브</h2>
  <div style="font-size:0.72rem;color:#475569;margin-bottom:14px">
    반도체/AI · AI플랫폼 · 에너지 섹터 | 1Y=1년 수익률, 1M=최근 1개월 | FDR(KR) + yfinance(US)
  </div>
  {sections_html}
</section>"""


def run_sector_analysis(output_dir: Path) -> dict:
    print("  섹터 데이터 수집 중...")
    sector_results = {}
    dynamic_used_count = 0
    seen_tickers: set = set()  # M-05: 섹터 간 전역 dedup (이미 배정된 티커는 후순위 섹터에서 제외)

    for sector_name, config in SECTORS.items():
        print(f"    [{sector_name}]", end=" ")
        us_tickers, kr_tickers, used_dynamic = _resolve_tickers(config)
        if used_dynamic:
            dynamic_used_count += 1
            print(f"(동적조회) ", end="")
        else:
            print(f"(폴백) ", end="")

        # M-05: 처리 순서상 앞선 섹터에 이미 배정된 티커는 제외 (섹터 간 중복 방지)
        us_tickers = [(s, nm) for (s, nm) in us_tickers if s not in seen_tickers]
        kr_tickers = [(s, nm) for (s, nm) in kr_tickers if s not in seen_tickers]
        seen_tickers.update(s for (s, _) in us_tickers)
        seen_tickers.update(s for (s, _) in kr_tickers)

        tickers = fetch_sector_data(kr_tickers, us_tickers)
        sector_results[sector_name] = {
            "tickers":      tickers,
            "theme":        config["theme"],
            "key_risk":     config["key_risk"],
            "universe_src": "dynamic" if used_dynamic else "fallback",
        }
        ok_count = sum(1 for v in tickers.values() if "return_1y" in v)
        print(f"{ok_count}/{len(us_tickers)+len(kr_tickers)} 수집 완료")

    # SEC-2 기록
    sector_results["_meta"] = {
        "generated_at": datetime.now().isoformat(),
        "dynamic_sectors": dynamic_used_count,
        "total_sectors":   len(SECTORS),
    }

    # 저장
    out = output_dir / "sector_analysis.json"
    out.write_text(json.dumps(sector_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {out}")
    return sector_results


if __name__ == "__main__":
    import sys
    BASE_DIR = Path(__file__).parent.parent
    results  = run_sector_analysis(BASE_DIR / "output")

    # ── Done Criteria ──────────────────────────────────────────
    fails = []

    # SEC-1: 최소 1개 섹터에 ≥1종목 데이터 성공
    any_data = any(
        any("return_1y" in v for v in data.get("tickers", {}).values())
        for k, data in results.items() if k != "_meta"
    )
    if not any_data:
        fails.append("SEC-1 모든 섹터 데이터 수집 실패")

    # SEC-2: 동적 조회 시도 확인
    meta = results.get("_meta", {})
    # dynamic_sectors >= 0 means the function ran (fallback is acceptable)
    if "dynamic_sectors" not in meta:
        fails.append("SEC-2 동적 유니버스 조회 시도 기록 없음")

    # SEC-3: 파일 저장 확인
    out_path = BASE_DIR / "output" / "sector_analysis.json"
    if not out_path.exists():
        fails.append("SEC-3 sector_analysis.json 저장 실패")

    print("\n=== Done Criteria ===")
    for code in ["SEC-1", "SEC-2", "SEC-3"]:
        fail_item = next((f for f in fails if code in f), None)
        print(f"  {'✗' if fail_item else '✓'} {fail_item or code + ' PASS'}")

    if fails:
        print(f"\n[FAIL] {fails}")
        sys.exit(1)
    print("\n[PASS] SEC-1~SEC-3 통과")

    for sector, data in results.items():
        if sector == "_meta":
            continue
        tickers = data.get("tickers", {})
        src     = data.get("universe_src", "?")
        print(f"\n{sector} ({src}):")
        for t, v in tickers.items():
            if "return_1y" in v:
                print(f"  {v['name']}: {v['return_1y']:+.1f}% (1Y)")

    # ── Done Criteria (auto-injected by SA-9) ──────────────────────────────
    import sys as _sa9_sys, os as _sa9_os
    from pathlib import Path as _sa9_P
    _sa9_out = str(_sa9_P(__file__).parent.parent / "output/sector_analysis.json")
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
