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

    # 수익률 바: max 기준 상대 비율로 표시 (최대 200%를 100%로 정규화)
    bar_pct = min(abs(ret) / 10, 100)  # 1000%를 100%로 normalize

    # 시가총액 단위
    if market == "KOSPI":
        # 억원 단위 (market_cap_b가 억원)
        if mcap >= 10000:
            mcap_str = f"{mcap/10000:.1f}조원"
        else:
            mcap_str = f"{mcap:.0f}억원"
    else:
        mcap_str = f"${mcap:.0f}B"

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

    return f"""
    <div class="stock-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <span style="font-size:0.7rem;color:#475569;font-weight:700">#{rank}</span>
          <span style="font-size:0.9rem;font-weight:700;color:#f1f5f9;margin-left:4px">{name}{sig_str}</span>
        </div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end">
          <span style="font-size:0.65rem;padding:1px 5px;border-radius:3px;background:#1e3a5f;color:{src_color}">{src}</span>
          <span style="font-size:0.65rem;padding:1px 5px;border-radius:3px;background:#1a2e1a;color:{dq_color}">{dq}</span>
        </div>
      </div>
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
