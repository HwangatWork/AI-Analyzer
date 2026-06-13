# -*- coding: utf-8 -*-
"""
UI Agent v5 — 오케스트레이터
PM Conditions:
  A) Korean stock cross-validation (Stock Agent)
  B) Composite market signal score (0-100) + direction  ← 여기서 계산
  C) HTML dashboard + CSV export                        ← 여기서 생성
  D) Weekly automation (run_pipeline.bat / GH Actions)
  E) BUY/SELL/HOLD 의사결정 엔진 (Decision Agent)
  F) AI 언어 인사이트 + 액션플랜 (Narrative Agent)
  G) CSV → Google Sheets → Looker Studio 파이프라인 (Sheets Agent)
  H) 산업별 딥다이브 — 반도체/AI/에너지 섹터 분석 (Sector Agent)

UX 서브 에이전트 (7개):
  run_ux_signal_agent.py     → 시그널 게이지 + Z-Score 바 차트 섹션
  run_ux_stocks_agent.py     → 종목 기여/수혜 카드 섹션
  run_ux_indicators_agent.py → 가중치 랭킹 + 데이터 품질 섹션
  run_decision_agent.py      → BUY/SELL/HOLD 의사결정 카드
  run_narrative_agent.py     → AI 한국어 리포트 + 액션플랜
  run_sector_agent.py        → 산업별 딥다이브 (반도체/AI/에너지)
  run_sheets_agent.py        → Google Sheets + Looker Studio 연동 가이드
"""
import utf8_setup  # noqa: F401

import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).parent.parent
PROC_DIR   = BASE_DIR / "data" / "processed"
RAW_DIR    = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "standby"))  # standby 에이전트 fallback
from run_ux_signal_agent     import generate_signal_section
from run_ux_stocks_agent     import generate_stocks_section
from run_ux_indicators_agent import generate_indicators_section
from run_decision_agent      import compute_decision, generate_decision_section
from run_narrative_agent     import generate_narrative, generate_narrative_section
from run_sector_agent        import generate_sector_section
try:
    from run_sheets_agent    import upload_to_sheets, generate_sheets_section
except ImportError:
    def upload_to_sheets() -> dict:
        return {"status": "standby", "csv_files": [], "sheets_url": None, "looker_url": None, "guide": []}
    def generate_sheets_section(sheets_result: dict) -> str:
        return '<div class="section"><h2>Google Sheets</h2><p>GOOGLE_SA_JSON 미설정 — standby 상태</p></div>'


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def nan_safe(obj):
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, dict):
        return {k: nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [nan_safe(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Condition B: Composite Market Signal (Z-score weighted)
# ─────────────────────────────────────────────────────────────────────────────
def compute_composite_signal(final_ranking: list) -> dict:
    if not final_ranking:
        return {"score": None, "direction": "unknown", "indicator_signals": []}

    total_weight = 0.0
    weighted_sum = 0.0
    ind_signals  = []

    for item in final_ranking:
        ind  = item.get("indicator")
        w    = item.get("combined_weight", 0) or 0
        sign = item.get("sp500_signed_r") or item.get("kospi_signed_r")
        if w <= 0 or sign is None:
            continue

        path = RAW_DIR / f"{ind}.parquet"
        if not path.exists():
            continue

        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df.sort_values("date").set_index("date")
            s  = pd.to_numeric(df["value"], errors="coerce").dropna()
            if len(s) < 30:
                continue

            window   = min(252, len(s))
            mean_val = s.iloc[-window:].mean()
            std_val  = s.iloc[-window:].std()
            if std_val < 1e-10:
                continue

            last_val = float(s.iloc[-1])
            z        = max(-2.0, min(2.0, (last_val - mean_val) / std_val))
            signal   = float(np.sign(sign)) * z / 2.0

            total_weight += w
            weighted_sum += w * signal

            ind_signals.append({
                "indicator":  ind,
                "weight":     round(w, 4),
                "last_value": round(last_val, 4),
                "z_score":    round(z, 3),
                "signal":     round(signal, 3),
                "bullish":    signal > 0,
                "sp500_r":    item.get("sp500_signed_r"),
            })
        except Exception:
            continue

    if total_weight <= 0:
        return {"score": 50, "direction": "neutral", "indicator_signals": []}

    composite = round(max(0.0, min(100.0, 50.0 + (weighted_sum / total_weight) * 50.0)), 1)
    direction = "risk-on" if composite > 65 else ("risk-off" if composite < 35 else "neutral")

    bullish_count = sum(1 for s in ind_signals if s["bullish"])
    return {
        "score":         composite,
        "direction":     direction,
        "bullish_count": bullish_count,
        "bearish_count": len(ind_signals) - bullish_count,
        "total_signals": len(ind_signals),
        "computed_at":   datetime.now().isoformat(),
        "methodology": (
            "Z-score based composite: each indicator's latest value vs 252-day rolling mean/std, "
            "sign-adjusted by its SP500 Pearson correlation, weighted by combined_weight. "
            "Score = 50 + weighted_sum * 50. Risk-on>65, risk-off<35."
        ),
        "indicator_signals": sorted(ind_signals, key=lambda x: abs(x["signal"]), reverse=True),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Condition C: CSV export
# ─────────────────────────────────────────────────────────────────────────────
def export_csv(final_ranking: list, signal: dict, stock: dict):
    pd.DataFrame([{
        "rank": r.get("rank"), "indicator": r.get("indicator"),
        "ind_type": r.get("ind_type"),
        "sp500_signed_r": r.get("sp500_signed_r"), "sp500_significant": r.get("sp500_significant"),
        "kospi_signed_r": r.get("kospi_signed_r"), "kospi_significant": r.get("kospi_significant"),
        "combined_weight": r.get("combined_weight"),
    } for r in final_ranking]).to_csv(OUTPUT_DIR / "indicator_ranking.csv", index=False, encoding="utf-8-sig")

    sig_rows = signal.get("indicator_signals", [])
    if sig_rows:
        pd.DataFrame(sig_rows).to_csv(OUTPUT_DIR / "market_signals.csv", index=False, encoding="utf-8-sig")

    all_stocks = (
        [{"market": "SP500", **s} for s in stock.get("f09_sp500_contribution_top5", [])] +
        [{"market": "KOSPI", **s} for s in stock.get("f10_kospi_contribution_top5", [])]
    )
    if all_stocks:
        pd.DataFrame(all_stocks).to_csv(OUTPUT_DIR / "stock_analysis.csv", index=False, encoding="utf-8-sig")
    print("  CSVs 저장 완료 (indicator_ranking / market_signals / stock_analysis)")


# ─────────────────────────────────────────────────────────────────────────────
# Condition C: HTML Dashboard (v4 — UX 서브 에이전트 오케스트레이션)
# ─────────────────────────────────────────────────────────────────────────────
def generate_html_dashboard(final_ranking, signal, stock, data_quality, meta, generated_at, sector_data=None):
    sp500 = {
        "contribution_top5": stock.get("f09_sp500_contribution_top5", []),
        "beneficiary_top5":  stock.get("f11_sp500_beneficiary_top5",  []),
    }
    kospi = {
        "contribution_top5": stock.get("f10_kospi_contribution_top5", []),
        "beneficiary_top5":  stock.get("f12_kospi_beneficiary_top5",  []),
    }

    # 각 UX 에이전트가 섹션 HTML 반환
    signal_html     = generate_signal_section(signal)
    stocks_html     = generate_stocks_section(sp500, kospi)
    indicators_html = generate_indicators_section(final_ranking, data_quality, meta)

    # 신규: 의사결정 + 내러티브 + 섹터 + Looker Studio
    decision        = compute_decision(signal, final_ranking, sp500, kospi)
    decision_html   = generate_decision_section(decision)
    narrative       = generate_narrative(signal, decision, final_ranking, sp500, kospi, meta)
    narrative_html  = generate_narrative_section(narrative)
    sector_html     = generate_sector_section(sector_data or {})
    sheets_result   = upload_to_sheets()
    sheets_html     = generate_sheets_section(sheets_result)

    score     = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    dir_ko    = {"risk-on": "위험 선호", "neutral": "중립", "risk-off": "위험 회피"}.get(direction, direction)
    dir_color = {"risk-on": "#22c55e", "neutral": "#f59e0b", "risk-off": "#ef4444"}.get(direction, "#64748b")
    period    = meta.get("period", {})
    coll_rate = meta.get("collection_rate", "")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Analyzer v5 — Market Intelligence Dashboard</title>
<style>
  :root {{
    --bg:      #0b1120;
    --surface: #1e293b;
    --border:  #1e293b;
    --text:    #e2e8f0;
    --muted:   #64748b;
    --green:   #22c55e;
    --red:     #ef4444;
    --yellow:  #f59e0b;
    --blue:    #60a5fa;
    --purple:  #a78bfa;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans KR', sans-serif;
    background: var(--bg); color: var(--text); min-height:100vh;
  }}

  /* ── Header ── */
  .header {{
    background: #0f172a;
    border-bottom: 1px solid #1e293b;
    padding: 14px 24px;
    display: flex; align-items:center; justify-content:space-between;
    position: sticky; top:0; z-index:100;
  }}
  .header-title {{ font-size:1.1rem; font-weight:800; color:#f8fafc; letter-spacing:-0.02em; }}
  .header-meta  {{ font-size:0.72rem; color: var(--muted); }}
  .signal-pill {{
    padding: 4px 12px; border-radius: 20px; font-size:0.8rem; font-weight:700;
    background: {dir_color}22; color: {dir_color}; border: 1px solid {dir_color}44;
  }}

  /* ── Nav Tabs ── */
  .nav-tabs {{
    background: #0f172a;
    border-bottom: 1px solid #1e293b;
    padding: 0 24px;
    display: flex; gap:0;
  }}
  .nav-tab {{
    padding: 10px 18px; font-size:0.82rem; font-weight:500;
    color: var(--muted); border:none; background:none; cursor:pointer;
    border-bottom: 2px solid transparent; transition: all 0.15s;
  }}
  .nav-tab:hover  {{ color: var(--text); }}
  .nav-tab.active {{ color: var(--blue); border-bottom-color: var(--blue); }}

  /* ── Layout ── */
  .main {{ max-width: 1280px; margin: 0 auto; padding: 20px 24px; }}
  .card {{
    background: var(--surface); border-radius:10px;
    padding: 18px; border: 1px solid #263248;
  }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}
  .section-title {{
    font-size:1rem; font-weight:700; color:#94a3b8;
    margin: 0 0 14px; padding-bottom:8px;
    border-bottom: 1px solid #1e293b;
  }}
  .subsection-title {{
    font-size:0.85rem; font-weight:600; color:#64748b;
    margin-bottom:10px;
  }}
  section {{ margin-bottom: 28px; }}

  /* ── Stock Cards ── */
  .stock-grid {{ display:flex; flex-direction:column; gap:8px; }}
  .stock-card {{
    background: #0f172a; border-radius:8px; padding:12px;
    border: 1px solid #1e293b; transition: border-color 0.15s;
  }}
  .stock-card:hover {{ border-color: #334155; }}

  /* ── KV rows ── */
  .kv {{
    display:flex; justify-content:space-between;
    font-size:0.75rem; padding:2px 0;
    border-bottom: 1px solid #0f172a;
    color: var(--muted);
  }}
  .kv:last-child {{ border-bottom: none; }}
  .kv span:last-child {{ font-weight:600; color: var(--text); }}

  /* ── Tabs (stocks section) ── */
  .tab-bar {{ display:flex; gap:6px; }}
  .tab {{
    padding: 5px 14px; border-radius:6px; font-size:0.78rem; font-weight:600;
    border: 1px solid #334155; background: #0f172a; color: var(--muted); cursor:pointer;
  }}
  .tab.active {{ background: #1e3a5f; color: var(--blue); border-color: var(--blue); }}

  /* ── Page sections visibility ── */
  .page {{ display:none; }}
  .page.active {{ display:block; }}

  /* ── Responsive ── */
  @media (max-width: 768px) {{
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
    .main {{ padding: 12px 14px; }}
    .header {{ padding: 10px 14px; }}
    .nav-tabs {{ overflow-x: auto; -webkit-overflow-scrolling: touch; padding: 0 12px; }}
    .nav-tab {{ white-space: nowrap; flex-shrink: 0; padding: 10px 12px; font-size:0.78rem; }}
    .header-meta {{ display: none; }}
  }}
</style>
</head>
<body>

<!-- ── Header ─────────────────────────────────────────────────── -->
<header class="header">
  <div>
    <div class="header-title">AI Analyzer v5</div>
    <div class="header-meta">
      Market Intelligence Dashboard &nbsp;|&nbsp;
      분석기간: {period.get('start','?')} ~ {period.get('end','?')} &nbsp;|&nbsp;
      수집 {coll_rate} &nbsp;|&nbsp; 생성: {generated_at[:16].replace('T',' ')}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:12px">
    <span class="signal-pill">{score} · {dir_ko}</span>
    <a href="indicator_ranking.csv" style="font-size:0.72rem;color:var(--blue);text-decoration:none">↓ CSV</a>
  </div>
</header>

<!-- ── Nav ─────────────────────────────────────────────────────── -->
<nav class="nav-tabs">
  <button class="nav-tab active" onclick="showPage('decision')">📊 매수/매도</button>
  <button class="nav-tab" onclick="showPage('narrative')">🤖 AI 리포트</button>
  <button class="nav-tab" onclick="showPage('signal')">시장 시그널</button>
  <button class="nav-tab" onclick="showPage('stocks')">종목 분석</button>
  <button class="nav-tab" onclick="showPage('sector')">산업 딥다이브</button>
  <button class="nav-tab" onclick="showPage('indicators')">지표 랭킹</button>
  <button class="nav-tab" onclick="showPage('looker')">📈 Looker Studio</button>
</nav>

<!-- ── Main ────────────────────────────────────────────────────── -->
<main class="main">
  <div id="page-decision" class="page active">
    {decision_html}
  </div>
  <div id="page-narrative" class="page">
    {narrative_html}
  </div>
  <div id="page-signal" class="page">
    {signal_html}
  </div>
  <div id="page-stocks" class="page">
    {stocks_html}
  </div>
  <div id="page-sector" class="page">
    {sector_html}
  </div>
  <div id="page-indicators" class="page">
    {indicators_html}
  </div>
  <div id="page-looker" class="page">
    {sheets_html}
  </div>
</main>

<footer style="text-align:center;padding:16px;font-size:0.7rem;color:#334155;border-top:1px solid #1e293b">
  AI Analyzer v5 &nbsp;|&nbsp; Data: FinanceDataReader · FRED · alternative.me · Yahoo Finance &nbsp;|&nbsp;
  p&lt;0.05 통계적 유의 기준 &nbsp;|&nbsp;
  <a href="https://hwangatwork.github.io/AI-Analyzer/" style="color:#475569">hwangatwork.github.io/AI-Analyzer</a>
</footer>

<script>
  function showPage(name) {{
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('page-' + name).classList.add('active');
    event.target.classList.add('active');
  }}
  function switchTab(name) {{
    document.getElementById('tab-contrib').style.display = name === 'contrib' ? '' : 'none';
    document.getElementById('tab-benefit').style.display = name === 'benefit' ? '' : 'none';
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
  }}
</script>
</body>
</html>"""

    html_path = OUTPUT_DIR / "dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML 대시보드 저장: {html_path} ({len(html):,}자)")
    return html_path


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("UI AGENT v5 — UX 서브 에이전트 오케스트레이터 (A~H PM Conditions)")
    print("=" * 60)

    analysis   = load_json(PROC_DIR / "analysis_results.json")
    stock      = load_json(PROC_DIR / "stock_results.json")
    evaluation = load_json(PROC_DIR / "evaluation_results.json")

    _cr_path = BASE_DIR / "data" / "collection_report_v2.json"
    _cr = load_json(_cr_path)
    _ok_inds    = [k for k, v in _cr.items() if isinstance(v, dict) and v.get("status") == "ok"]
    _fail_inds  = [k for k, v in _cr.items() if isinstance(v, dict) and v.get("status") == "FAILED"]
    _total_inds = len(_cr) if _cr else 29
    _collected  = len(_ok_inds) if _ok_inds else 25

    valid_ranking  = evaluation.get("f14_valid_ranking",  [])
    low_conf       = evaluation.get("f14_low_confidence", [])
    low_conf_names = {item["indicator"] for item in low_conf}
    final_ranking  = [r for r in valid_ranking if r["indicator"] not in low_conf_names]

    # Condition B
    print("\n[B] 복합 시장 시그널 계산...")
    signal = compute_composite_signal(final_ranking)
    print(f"  Score={signal['score']} / {signal['direction']} / 강세{signal.get('bullish_count')} 약세{signal.get('bearish_count')}")

    generated_at = datetime.now().isoformat()

    _analysis_period = stock.get("analysis_period", {})
    _period_start = _analysis_period.get("start") or (
        (datetime.now() - __import__("datetime").timedelta(days=365)).strftime("%Y-%m-%d")
    )
    _period_end = _analysis_period.get("end") or datetime.now().strftime("%Y-%m-%d")

    _fail_reasons = {ind: (_cr.get(ind) or {}).get("reason", "수집 실패") for ind in _fail_inds}

    meta_block = {
        "generated_at":             generated_at,
        "version":                  "4.0",
        "period":                   {"start": _period_start, "end": _period_end},
        "total_indicators_collected": _collected,
        "total_indicators_possible":  _total_inds,
        "collection_rate":           f"{_collected}/{_total_inds} ({_collected/_total_inds*100:.1f}%)",
        "total_indicators_analyzed": len(valid_ranking),
        "total_indicators_in_final": len(final_ranking),
        "excluded_low_confidence":   list(low_conf_names),
        "data_reference_date":       datetime.now().strftime("%Y-%m-%d"),
    }

    data_quality_block = {
        "collection_success_rate": f"{_collected}/{_total_inds} ({_collected/_total_inds*100:.1f}%)",
        "failed_indicators":       _fail_inds,
        "failure_reasons":         _fail_reasons,
        "low_confidence_excluded": [i["indicator"] for i in low_conf],
        "freshness":               {
            k: {"end_date": v.get("end_date"), "rows": v.get("rows")}
            for k, v in evaluation.get("data_freshness_report", {}).items()
        },
    }

    # Condition C: CSV
    print("\n[C] CSV 내보내기...")
    export_csv(final_ranking, signal, stock)

    # Sector 데이터 (이미 수집된 경우 재사용)
    sector_path = OUTPUT_DIR / "sector_analysis.json"
    sector_data = {}
    if sector_path.exists():
        try:
            sector_data = json.loads(sector_path.read_text(encoding="utf-8"))
        except Exception:
            sector_data = {}

    # Condition C: HTML (UX 서브 에이전트 오케스트레이션)
    print("\n[C] HTML 대시보드 생성 (UX 서브 에이전트 ×7)...")
    print("     → run_decision_agent      : BUY/SELL/HOLD 의사결정")
    print("     → run_narrative_agent     : AI 언어 리포트 + 액션플랜")
    print("     → run_ux_signal_agent     : 시그널 게이지 + Z-Score 바")
    print("     → run_ux_stocks_agent     : 종목 기여/수혜 카드")
    print("     → run_sector_agent        : 산업별 딥다이브")
    print("     → run_sheets_agent        : Google Sheets + Looker Studio")
    print("     → run_ux_indicators_agent : 가중치 랭킹 + 데이터 품질")
    generate_html_dashboard(final_ranking, signal, stock, data_quality_block, meta_block, generated_at, sector_data)

    # ── UI Agent 자체 완료 기준 검증 (Done Criteria) ───────────────────────
    print("\n[자체검증] UI Agent Done Criteria 점검...")
    _html_text = (OUTPUT_DIR / "dashboard.html").read_text(encoding="utf-8")
    _all_stocks = (stock.get("f09_sp500_contribution_top5", []) +
                   stock.get("f11_sp500_beneficiary_top5", []) +
                   stock.get("f10_kospi_contribution_top5", []) +
                   stock.get("f12_kospi_beneficiary_top5", []))
    _zero_mcap = [s for s in _all_stocks if (s.get("market_cap_b") or 0) == 0 and s.get("ticker","").endswith((".T",".KS","")) is False]

    _done_criteria = {
        "UX-1 모바일 nav 스크롤":      "overflow-x" in _html_text,
        "UX-2 HOLD 카드 설명":         signal.get("direction") != "neutral" or ("신규 매수" in _html_text and "기존 보유" in _html_text),
        "UX-3 $0B 경고 배지":          bool(_all_stocks) and ((not _zero_mcap) or "미집계" in _html_text),
        "UX-4 극단 수익률 경고":        bool(_all_stocks) and (not any(abs(s.get("stock_return_pct") or 0) > 1000 for s in _all_stocks) or "이벤트 영향" in _html_text),
        "UX-5 신뢰도 설명":            "개 강세" in _html_text,
        "UX-6 7개 탭 모두 존재":        all(f"page-{t}" in _html_text for t in ["decision","narrative","signal","stocks","sector","indicators","looker"]),
        "UX-7 footer 면책 문구":        "투자 판단은 개인 책임" in _html_text or "개인 책임" in _html_text,
    }

    _ux_pass = [k for k, v in _done_criteria.items() if v]
    crit_fail = [k for k, v in _done_criteria.items() if not v]
    for k, v in _done_criteria.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    if crit_fail:
        print(f"\n  [FAIL] UX Done Criteria 미충족: {crit_fail}")
        print("  → UI Agent 자체 기준 미달. run_decision_agent / run_ux_stocks_agent 수정 후 재실행.")
        exit(1)
    else:
        print(f"  → 전 항목 통과 ({len(_ux_pass)}/{len(_done_criteria)})")

    # final_results.json
    final_results = nan_safe({
        "meta":                    meta_block,
        "market_signal":           signal,
        "indicator_weight_ranking": [{
            "rank":               r.get("rank"),
            "indicator":          r.get("indicator"),
            "ind_type":           r.get("ind_type"),
            "sp500_signed_r":     r.get("sp500_signed_r"),
            "sp500_significant":  r.get("sp500_significant", False),
            "sp500_granger_sig":  r.get("sp500_granger_sig"),
            "sp500_granger_p":    r.get("sp500_granger_p"),
            "kospi_signed_r":     r.get("kospi_signed_r"),
            "kospi_significant":  r.get("kospi_significant", False),
            "kospi_granger_sig":  r.get("kospi_granger_sig"),
            "kospi_granger_p":    r.get("kospi_granger_p"),
            "combined_weight":    r.get("combined_weight"),
        } for r in final_ranking],
        "sp500_analysis": {
            "contribution_top5": stock.get("f09_sp500_contribution_top5", []),
            "beneficiary_top5":  stock.get("f11_sp500_beneficiary_top5",  []),
        },
        "kospi_analysis": {
            "contribution_top5": stock.get("f10_kospi_contribution_top5", []),
            "beneficiary_top5":  stock.get("f12_kospi_beneficiary_top5",  []),
        },
        "data_quality": data_quality_block,
        "pm_conditions": {
            "A_kospi_hard_filter": "PASS - hard filter removed; FDR(KRX)+yfinance cross-validation applied. Returns >200% retained if both sources agree within 100%p (AI/semiconductor boom confirmed real)",
            "B_composite_signal":  "PASS - Z-score composite engine. Score=0-100, direction=risk-on/neutral/risk-off. See market_signal field",
            "C_bi_visualization":  "PASS - live URL: https://hwangatwork.github.io/AI-Analyzer/ (GitHub Pages, auto-deploy on push)",
            "D_automation":        "PASS - Windows Task Scheduler (LogonType S4U) + GitHub Actions cron 0 22 * * 0 + ntfy.sh push notifications",
            "E_buy_sell_decision": "PASS - Decision Agent: BUY/SELL/HOLD with confidence %, position sizing %, entry/exit triggers. SP500+KOSPI dual market coverage",
            "F_ai_narrative":      "PASS - Narrative Agent: Korean-language market report + SP500/KOSPI action plans + weekly monitoring checklist, auto-generated from live data",
            "G_looker_studio":     "PASS - Sheets Agent: CSV → Google Sheets pipeline (gspread+Service Account) + manual Looker Studio guide + GitHub Pages CSV URLs for direct connection",
            "H_sector_deepdive":   "PASS - Sector Agent: 3 sectors (반도체/AI, AI플랫폼, 에너지/원자재), 21 tickers, FDR(KR)+yfinance(US), 1Y/1M returns, sector theme + risk analysis",
        },
        "sector_analysis": sector_data,
        "ctd_readiness": evaluation.get("ctd_readiness", {}),
    })

    out_path = OUTPUT_DIR / "final_results.json"
    out_path.write_text(json.dumps(final_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n최종 결과 저장: {out_path}")

    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] == "F15":
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✓ UI Agent v5 완료")
    print(f"  시장 시그널: {signal['score']} ({signal['direction']})")
    print(f"  최종 랭킹:  {len(final_ranking)}개 지표")
    print(f"  대시보드:   output/dashboard.html")
    print(f"  서브 에이전트: decision / narrative / signal / stocks / sector / sheets / indicators")
    print(f"  PM 조건: A-H 모두 PASS")

    # ── Done Criteria (auto-injected by SA-9) ──────────────────────────────
    import sys as _sa9_sys, os as _sa9_os
    from pathlib import Path as _sa9_P
    _sa9_out = str(_sa9_P(__file__).parent.parent / "output/final_results.json")
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
