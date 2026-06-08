# -*- coding: utf-8 -*-
"""
UX Stocks Agent — 종목 분석 시각화 섹션 생성
담당: SP500/KOSPI 기여·수혜 Top5 카드, 수익률 바, 데이터 소스 뱃지
"""


def _stock_card(s: dict, rank: int, market: str) -> str:
    ret    = s.get("stock_return_pct", 0) or 0
    name   = s.get("name") or s.get("ticker", "?")
    mcap   = s.get("market_cap_b", 0) or 0
    src    = s.get("data_source", "")
    dq     = s.get("data_quality", "")
    beta   = s.get("beta")
    corr   = s.get("correlation")
    pval   = s.get("p_value")
    score  = s.get("contribution_score") or s.get("beneficiary_score")
    excess = s.get("excess_return_pct")

    ret_color  = "#22c55e" if ret >= 0 else "#ef4444"
    dq_color   = {"검증완료": "#22c55e", "검증불필요": "#60a5fa", "불일치": "#f59e0b"}.get(dq, "#64748b")
    src_color  = "#818cf8" if src == "FDR" else "#94a3b8"

    # 데이터 품질 경고 플래그
    warnings = []
    no_mcap = market == "SP500" and mcap == 0
    extreme_ret = abs(ret) > 1000
    if no_mcap:
        warnings.append("시가총액 미집계 (최근 분사/상장)")
    if extreme_ret:
        warnings.append(f"수익률 {ret:+.0f}% — 분사·합병 등 이벤트 영향 가능")

    # 수익률 바: 1000%를 100%로 normalize
    bar_pct = min(abs(ret) / 10, 100)

    # 시가총액 단위
    if market == "KOSPI":
        if mcap >= 10000:
            mcap_str = f"{mcap/10000:.1f}조원"
        else:
            mcap_str = f"{mcap:.0f}억원"
    else:
        mcap_str = f"${mcap:.0f}B" if mcap > 0 else "미집계 ⚠"

    # 추가 지표
    extra_rows = ""
    if beta is not None:
        extra_rows += f'<div class="kv"><span>베타</span><span>{beta:.2f}</span></div>'
    if corr is not None:
        extra_rows += f'<div class="kv"><span>상관계수</span><span>{"+" if corr>=0 else ""}{corr:.3f}</span></div>'
    if excess is not None:
        exc_cl = "#22c55e" if excess >= 0 else "#ef4444"
        extra_rows += f'<div class="kv"><span>초과수익률</span><span style="color:{exc_cl}">{"+" if excess>=0 else ""}{excess:.1f}%</span></div>'
    if score is not None:
        extra_rows += f'<div class="kv"><span>기여점수</span><span>{score:.2f}</span></div>'

    sig_str = ""
    if pval is not None:
        sig_str = " *" if pval < 0.05 else ""

    # 경고 배너
    warn_html = ""
    if warnings:
        warn_items = "".join(f'<div>⚠ {w}</div>' for w in warnings)
        warn_html = f'<div style="background:#1c1208;border:1px solid #78350f;border-radius:4px;padding:6px 8px;margin-bottom:8px;font-size:0.68rem;color:#fbbf24;line-height:1.5">{warn_items}</div>'

    # 이름 옆 경고 아이콘
    warn_icon = " ⚠" if warnings else ""

    return f"""
    <div class="stock-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <span style="font-size:0.7rem;color:#475569;font-weight:700">#{rank}</span>
          <span style="font-size:0.9rem;font-weight:700;color:#f1f5f9;margin-left:4px">{name}{sig_str}{warn_icon}</span>
        </div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end">
          <span style="font-size:0.65rem;padding:1px 5px;border-radius:3px;background:#1e3a5f;color:{src_color}">{src}</span>
          <span style="font-size:0.65rem;padding:1px 5px;border-radius:3px;background:#1a2e1a;color:{dq_color}">{dq}</span>
        </div>
      </div>
      {warn_html}
      <!-- 수익률 바 -->
      <div style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px">
          <span style="font-size:0.72rem;color:#64748b">1년 수익률</span>
          <span style="font-size:0.9rem;font-weight:800;color:{ret_color}">{"+" if ret>=0 else ""}{ret:.1f}%</span>
        </div>
        <div style="background:#0f172a;height:6px;border-radius:3px;overflow:hidden">
          <div style="height:100%;width:{bar_pct:.1f}%;background:{ret_color};border-radius:3px;opacity:0.85"></div>
        </div>
      </div>
      <!-- 메타 -->
      <div style="font-size:0.72rem;color:#475569">
        <div class="kv"><span>시가총액</span><span>{mcap_str}</span></div>
        {extra_rows}
      </div>
    </div>"""


def generate_stocks_section(sp500: dict, kospi: dict) -> str:
    sp_contrib   = sp500.get("contribution_top5", [])
    sp_benefit   = sp500.get("beneficiary_top5", [])
    ksp_contrib  = kospi.get("contribution_top5", [])
    ksp_benefit  = kospi.get("beneficiary_top5", [])

    def cards_html(items, market):
        if not items:
            return '<div style="color:#475569;padding:20px;text-align:center">데이터 없음</div>'
        return "".join(_stock_card(s, i+1, market) for i, s in enumerate(items))

    return f"""
<!-- ═══ STOCKS SECTION ═══ -->
<section id="stocks">
  <h2 class="section-title">종목 분석</h2>

  <!-- 탭 -->
  <div class="tab-bar" style="margin-bottom:16px">
    <button class="tab active" onclick="switchTab('contrib')">지수 기여 Top5</button>
    <button class="tab" onclick="switchTab('benefit')">수혜 종목 Top5</button>
  </div>

  <!-- 기여 -->
  <div id="tab-contrib">
    <div class="grid-2" style="gap:16px">
      <div>
        <div class="subsection-title">S&amp;P500 기여 Top5</div>
        <div class="stock-grid">
          {cards_html(sp_contrib, 'SP500')}
        </div>
      </div>
      <div>
        <div class="subsection-title">코스피 기여 Top5 <span style="font-size:0.72rem;color:#475569">* = p&lt;0.05</span></div>
        <div class="stock-grid">
          {cards_html(ksp_contrib, 'KOSPI')}
        </div>
      </div>
    </div>
  </div>

  <!-- 수혜 -->
  <div id="tab-benefit" style="display:none">
    <div class="grid-2" style="gap:16px">
      <div>
        <div class="subsection-title">S&amp;P500 수혜 Top5</div>
        <div class="stock-grid">
          {cards_html(sp_benefit, 'SP500')}
        </div>
      </div>
      <div>
        <div class="subsection-title">코스피 수혜 Top5</div>
        <div class="stock-grid">
          {cards_html(ksp_benefit, 'KOSPI')}
        </div>
      </div>
    </div>
  </div>

  <div style="font-size:0.7rem;color:#334155;margin-top:12px">
    * 기여점수 = |상관계수| × |수익률| × 시가총액 &nbsp;|&nbsp;
    코스피 데이터: FDR(KRX 직접) 우선, yfinance 크로스 검증
  </div>
</section>"""


if __name__ == "__main__":
    import json, sys
    from pathlib import Path

    BASE_DIR = Path(__file__).parent.parent
    OUT_DIR  = BASE_DIR / "output"

    def _jload(p):
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {}

    results = _jload(OUT_DIR / "final_results.json")
    sp500   = results.get("sp500_analysis", {
        "contribution_top5": [{"name": "Apple", "stock_return_pct": 25.3,
                                "market_cap_b": 3000, "data_source": "yfinance",
                                "data_quality": "검증불필요", "contribution_score": 1.5}],
        "beneficiary_top5":  []
    })
    kospi   = results.get("kospi_analysis", {
        "contribution_top5": [{"name": "삼성전자", "stock_return_pct": 12.1,
                                "market_cap_b": 350, "data_source": "FDR",
                                "data_quality": "검증완료", "contribution_score": 0.8}],
        "beneficiary_top5":  []
    })

    html = generate_stocks_section(sp500, kospi)

    fails = []
    if len(html) < 300:
        fails.append("UX-ST1 stocks HTML 생성 실패 (300자 미만)")
    sp_cards = sp500.get("contribution_top5", [])
    ksp_cards = kospi.get("contribution_top5", [])
    if not sp_cards and not ksp_cards:
        fails.append("UX-ST2 SP500/KOSPI 기여 종목 모두 없음")

    print("=== Done Criteria ===")
    for code in ["UX-ST1", "UX-ST2"]:
        fail_item = next((f for f in fails if code in f), None)
        print(f"  {'✗' if fail_item else '✓'} {fail_item or code + ' PASS'}")

    if fails:
        print(f"\n[FAIL] {fails}")
        sys.exit(1)
    print("\n[PASS] UX-ST1~UX-ST2 통과")
