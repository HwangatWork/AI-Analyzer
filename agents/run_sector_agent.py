# -*- coding: utf-8 -*-
"""
Sector Agent — 산업별 딥다이브
PM Condition H: 반도체/AI/에너지 섹터 분석 + 직무별 인사이트

분석 대상:
  - 반도체/AI: NVDA, TSM, AVGO, AMAT, ASML / SK하이닉스, 삼성전자
  - 에너지: XOM, CVX / 한국전력, 두산에너빌리티
  - 테크: AAPL, MSFT, GOOGL / 카카오, 네이버
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta


SECTORS = {
    "반도체/AI": {
        "us":  [("NVDA", "NVIDIA"), ("TSM", "TSMC"), ("AVGO", "Broadcom"), ("AMAT", "Applied Materials"), ("INTC", "Intel")],
        "kr":  [("000660.KS", "SK하이닉스"), ("005930.KS", "삼성전자"), ("042700.KS", "한미반도체")],
        "theme": "AI 수요 급증, HBM 메모리 사이클, 파운드리 확장",
        "key_risk": "재고 조정, 중국 제재 리스크, 설비투자 과잉",
    },
    "AI/플랫폼": {
        "us":  [("GOOGL", "Alphabet"), ("MSFT", "Microsoft"), ("META", "Meta"), ("AMZN", "Amazon")],
        "kr":  [("035720.KS", "카카오"), ("035420.KS", "NAVER"), ("259960.KS", "크래프톤")],
        "theme": "클라우드 AI 서비스 수요, LLM 상용화, 광고 회복",
        "key_risk": "규제 리스크, AI 투자 수익성 불확실, 경쟁 심화",
    },
    "에너지/원자재": {
        "us":  [("XOM", "ExxonMobil"), ("CVX", "Chevron"), ("NEE", "NextEra Energy")],
        "kr":  [("015760.KS", "한국전력"), ("034020.KS", "두산에너빌리티"), ("010950.KS", "S-Oil")],
        "theme": "에너지 전환, 원자력 르네상스, AI 데이터센터 전력 수요",
        "key_risk": "유가 변동성, 정책 리스크, 금리 민감도",
    },
}


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

    for sector_name, config in SECTORS.items():
        print(f"    [{sector_name}]", end=" ")
        tickers = fetch_sector_data(config["kr"], config["us"])
        sector_results[sector_name] = {
            "tickers":  tickers,
            "theme":    config["theme"],
            "key_risk": config["key_risk"],
        }
        ok_count = sum(1 for v in tickers.values() if "return_1y" in v)
        print(f"{ok_count}/{len(config['us'])+len(config['kr'])} 수집 완료")

    # 저장
    out = output_dir / "sector_analysis.json"
    out.write_text(json.dumps(sector_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {out}")
    return sector_results


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent.parent
    results  = run_sector_analysis(BASE_DIR / "output")
    for sector, data in results.items():
        tickers = data.get("tickers", {})
        print(f"\n{sector}:")
        for t, v in tickers.items():
            if "return_1y" in v:
                print(f"  {v['name']}: {v['return_1y']:+.1f}% (1Y)")
