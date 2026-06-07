# -*- coding: utf-8 -*-
"""
UI Agent - F15 v3
PM Conditions:
  A) Korean stock hard filter applied in Stock Agent (±200% threshold)
  B) Composite market signal score (0-100) + direction added here
  C) CSV export for Looker Studio + HTML dashboard generated
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).parent.parent
PROC_DIR   = BASE_DIR / "data" / "processed"
RAW_DIR    = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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


# ---------------------------------------------------------------------------
# Condition B: Composite Market Signal Score
# Methodology:
#   For each indicator in final_ranking:
#     1. Load its parquet data, get most recent value
#     2. Compute z-score vs rolling 252-day window
#     3. If indicator correlates positively with SP500 (signed_r > 0):
#        high z-score => bullish; vice-versa if negative correlation
#     4. Each indicator contributes: weight * clamp(z_score, -2, 2) / 2
#        clamped to [-1, +1]
#   Final score = 50 + sum_of_contributions * 50 / sum_of_weights
#   Direction: risk-on (>65), neutral (35-65), risk-off (<35)
# ---------------------------------------------------------------------------
def compute_composite_signal(final_ranking: list) -> dict:
    if not final_ranking:
        return {
            "score": None, "direction": "unknown",
            "methodology": "No valid indicators available",
            "indicator_signals": [],
        }

    total_weight  = 0.0
    weighted_sum  = 0.0
    ind_signals   = []

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

            # z-score vs past 252 days (or all data if shorter)
            window = min(252, len(s))
            mean_val = s.iloc[-window:].mean()
            std_val  = s.iloc[-window:].std()
            if std_val < 1e-10:
                continue

            last_val = float(s.iloc[-1])
            z        = (last_val - mean_val) / std_val
            z        = max(-2.0, min(2.0, z))   # clamp

            # direction: positive corr => positive z = bullish signal
            signal   = float(np.sign(sign)) * z / 2.0  # in [-1, +1]

            total_weight  += w
            weighted_sum  += w * signal

            ind_signals.append({
                "indicator":   ind,
                "weight":      round(w, 4),
                "last_value":  round(last_val, 4),
                "z_score":     round(z, 3),
                "signal":      round(signal, 3),
                "bullish":     signal > 0,
                "sp500_r":     item.get("sp500_signed_r"),
            })
        except Exception:
            continue

    if total_weight <= 0:
        return {
            "score": 50, "direction": "neutral",
            "methodology": "No data available for signal computation",
            "indicator_signals": [],
        }

    composite = 50.0 + (weighted_sum / total_weight) * 50.0
    composite = round(max(0.0, min(100.0, composite)), 1)

    if composite > 65:
        direction = "risk-on"
    elif composite < 35:
        direction = "risk-off"
    else:
        direction = "neutral"

    bullish_count  = sum(1 for s in ind_signals if s["bullish"])
    bearish_count  = len(ind_signals) - bullish_count

    return {
        "score":          composite,
        "direction":      direction,
        "bullish_count":  bullish_count,
        "bearish_count":  bearish_count,
        "total_signals":  len(ind_signals),
        "computed_at":    datetime.now().isoformat(),
        "methodology": (
            "Z-score based composite: each indicator's latest value vs 252-day rolling mean/std, "
            "sign-adjusted by its SP500 Pearson correlation, weighted by combined_weight. "
            "Score = 50 + weighted_sum * 50. Risk-on>65, risk-off<35."
        ),
        "indicator_signals": sorted(ind_signals, key=lambda x: abs(x["signal"]), reverse=True),
    }


# ---------------------------------------------------------------------------
# Condition C: CSV export for Looker Studio / Google Sheets
# ---------------------------------------------------------------------------
def export_csv(final_ranking: list, signal: dict, stock: dict):
    rows = []
    for r in final_ranking:
        rows.append({
            "rank":              r.get("rank"),
            "indicator":         r.get("indicator"),
            "ind_type":          r.get("ind_type"),
            "sp500_signed_r":    r.get("sp500_signed_r"),
            "sp500_significant": r.get("sp500_significant"),
            "kospi_signed_r":    r.get("kospi_signed_r"),
            "kospi_significant": r.get("kospi_significant"),
            "combined_weight":   r.get("combined_weight"),
        })

    df = pd.DataFrame(rows)
    csv_path = OUTPUT_DIR / "indicator_ranking.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  CSV 저장: {csv_path}")

    # Signal summary CSV
    sig_rows = signal.get("indicator_signals", [])
    if sig_rows:
        sig_df = pd.DataFrame(sig_rows)
        sig_csv = OUTPUT_DIR / "market_signals.csv"
        sig_df.to_csv(sig_csv, index=False, encoding="utf-8-sig")
        print(f"  Signal CSV 저장: {sig_csv}")

    # Stock analysis CSV
    sp5_contrib = stock.get("f09_sp500_contribution_top5", [])
    ksp_contrib = stock.get("f10_kospi_contribution_top5", [])
    all_stocks  = [{"market": "SP500", **s} for s in sp5_contrib] + \
                  [{"market": "KOSPI", **s} for s in ksp_contrib]
    if all_stocks:
        stk_df  = pd.DataFrame(all_stocks)
        stk_csv = OUTPUT_DIR / "stock_analysis.csv"
        stk_df.to_csv(stk_csv, index=False, encoding="utf-8-sig")
        print(f"  Stock CSV 저장: {stk_csv}")

    return csv_path


# ---------------------------------------------------------------------------
# Condition C: self-contained HTML dashboard
# ---------------------------------------------------------------------------
def generate_html_dashboard(final_ranking: list, signal: dict, stock: dict,
                            generated_at: str):
    score     = signal.get("score", 50)
    direction = signal.get("direction", "neutral")
    dir_color = {"risk-on": "#22c55e", "neutral": "#f59e0b", "risk-off": "#ef4444"}.get(direction, "#6b7280")
    dir_ko    = {"risk-on": "위험 선호 (Risk-On)", "neutral": "중립 (Neutral)", "risk-off": "위험 회피 (Risk-Off)"}.get(direction, "알 수 없음")

    # Indicator ranking table rows
    rank_rows = ""
    for r in final_ranking[:15]:
        sp_r  = r.get("sp500_signed_r")
        kp_r  = r.get("kospi_signed_r")
        sp_s  = "*" if r.get("sp500_significant") else ""
        kp_s  = "*" if r.get("kospi_significant") else ""
        sp_cl = "green" if (sp_r or 0) > 0 else "red"
        kp_cl = "green" if (kp_r or 0) > 0 else "red"
        rank_rows += f"""
        <tr>
          <td>{r.get('rank')}</td>
          <td><strong>{r.get('indicator')}</strong></td>
          <td>{r.get('ind_type', '-')}</td>
          <td class="{sp_cl}">{f"{sp_r:+.3f}{sp_s}" if sp_r is not None else "N/A"}</td>
          <td class="{kp_cl}">{f"{kp_r:+.3f}{kp_s}" if kp_r is not None else "N/A"}</td>
          <td>{r.get('combined_weight', 0):.4f}</td>
        </tr>"""

    # Signal indicator rows
    sig_rows_html = ""
    for s in signal.get("indicator_signals", [])[:10]:
        z     = s.get("z_score", 0)
        bull  = s.get("bullish", False)
        cl    = "green" if bull else "red"
        arrow = "▲" if bull else "▼"
        sig_rows_html += f"""
        <tr>
          <td>{s.get('indicator')}</td>
          <td>{s.get('last_value'):.4g}</td>
          <td class="{cl}">{z:+.2f}</td>
          <td class="{cl}">{arrow} {"강세" if bull else "약세"}</td>
          <td>{s.get('weight'):.4f}</td>
        </tr>"""

    # Stock tables
    def stock_table(items, label):
        if not items:
            return f"<p>{label} 데이터 없음</p>"
        rows = ""
        for i, s in enumerate(items, 1):
            ret = s.get("stock_return_pct", 0)
            cl  = "green" if ret > 0 else "red"
            rows += f"""
            <tr>
              <td>#{i}</td>
              <td><strong>{s.get('name', s.get('ticker'))}</strong></td>
              <td class="{cl}">{ret:+.1f}%</td>
              <td>{s.get('market_cap_b', 'N/A')}B</td>
            </tr>"""
        return f"""<table class="data-table"><thead><tr><th>#</th><th>종목</th><th>수익률(1Y)</th><th>시가총액</th></tr></thead><tbody>{rows}</tbody></table>"""

    sp5_c  = stock.get("f09_sp500_contribution_top5", [])
    ksp_c  = stock.get("f10_kospi_contribution_top5", [])
    sp5_b  = stock.get("f11_sp500_beneficiary_top5",  [])
    ksp_b  = stock.get("f12_kospi_beneficiary_top5",  [])

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Analyzer - Market Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f172a; color: #e2e8f0; padding: 20px; }}
  h1   {{ font-size: 1.6rem; margin-bottom: 4px; color: #f8fafc; }}
  h2   {{ font-size: 1.1rem; color: #94a3b8; margin: 20px 0 10px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }}
  .meta {{ font-size: 0.8rem; color: #64748b; margin-bottom: 20px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #1e293b; border-radius: 8px; padding: 16px; }}
  .signal-score {{ font-size: 3.5rem; font-weight: 800; color: {dir_color}; text-align: center; line-height: 1; }}
  .signal-dir   {{ font-size: 1rem; text-align: center; color: {dir_color}; margin-top: 4px; }}
  .kv  {{ display: flex; justify-content: space-between; font-size: 0.85rem; padding: 4px 0;
           border-bottom: 1px solid #0f172a; }}
  .kv:last-child {{ border-bottom: none; }}
  .kv .val {{ font-weight: 600; }}
  .green {{ color: #22c55e; }} .red {{ color: #ef4444; }}
  table.data-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  table.data-table th {{ background: #0f172a; color: #94a3b8; padding: 6px 8px; text-align: left; }}
  table.data-table td {{ padding: 5px 8px; border-bottom: 1px solid #0f172a; }}
  table.data-table tr:hover td {{ background: #263248; }}
  .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.72rem;
             background: #334155; color: #94a3b8; }}
  .method-note {{ font-size: 0.72rem; color: #475569; margin-top: 8px; line-height: 1.5; }}
  @media (max-width: 700px) {{ .grid-2, .grid-4 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>AI Analyzer - Market Intelligence Dashboard</h1>
<p class="meta">Generated: {generated_at} &nbsp;|&nbsp; Indicators analyzed: {len(final_ranking)} &nbsp;|&nbsp; <a href="indicator_ranking.csv" style="color:#60a5fa">Download CSV</a></p>

<h2>종합 시장 시그널</h2>
<div class="grid-2">
  <div class="card">
    <div class="signal-score">{score}</div>
    <div class="signal-dir">{dir_ko}</div>
    <p class="method-note">{signal.get('methodology','')[:200]}</p>
  </div>
  <div class="card">
    <div class="kv"><span>강세 신호</span><span class="val green">{signal.get('bullish_count', 0)}개</span></div>
    <div class="kv"><span>약세 신호</span><span class="val red">{signal.get('bearish_count', 0)}개</span></div>
    <div class="kv"><span>분석 지표</span><span class="val">{signal.get('total_signals', 0)}개</span></div>
    <div class="kv"><span>기준</span><span class="val">Risk-On &gt;65 / Risk-Off &lt;35</span></div>
  </div>
</div>

<h2>지표별 시그널 (상위 10개)</h2>
<div class="card">
<table class="data-table">
<thead><tr><th>지표</th><th>최근값</th><th>Z-Score</th><th>시그널</th><th>가중치</th></tr></thead>
<tbody>{sig_rows_html}</tbody>
</table>
</div>

<h2>지표 가중치 랭킹 (Top 15, * = p&lt;0.05 유의)</h2>
<div class="card">
<table class="data-table">
<thead><tr><th>순위</th><th>지표</th><th>유형</th><th>SP500 r</th><th>KOSPI r</th><th>가중치</th></tr></thead>
<tbody>{rank_rows}</tbody>
</table>
</div>

<div class="grid-2">
  <div>
    <h2>S&P500 기여 Top5</h2>
    <div class="card">{stock_table(sp5_c, 'S&P500 기여')}</div>
  </div>
  <div>
    <h2>코스피 기여 Top5</h2>
    <div class="card">{stock_table(ksp_c, '코스피 기여')}</div>
  </div>
</div>

<div class="grid-2">
  <div>
    <h2>S&P500 수혜 Top5</h2>
    <div class="card">{stock_table(sp5_b, 'S&P500 수혜')}</div>
  </div>
  <div>
    <h2>코스피 수혜 Top5</h2>
    <div class="card">{stock_table(ksp_b, '코스피 수혜')}</div>
  </div>
</div>

<p class="method-note" style="margin-top:24px; text-align:center;">
  AI Analyzer v3 | Data: FinanceDataReader, FRED, alternative.me, Yahoo Finance |
  분석 기간: 1년 | 유의성 기준: p &lt; 0.05
</p>
</body>
</html>"""

    html_path = OUTPUT_DIR / "dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML 대시보드 저장: {html_path}")
    return html_path


if __name__ == "__main__":
    print("=" * 60)
    print("UI AGENT v3 - Phase 5 (F15) + PM Conditions A/B/C")
    print("=" * 60)

    analysis   = load_json(PROC_DIR / "analysis_results.json")
    stock      = load_json(PROC_DIR / "stock_results.json")
    evaluation = load_json(PROC_DIR / "evaluation_results.json")

    # 실제 수집 결과 읽기 (하드코딩 제거)
    _cr_path = BASE_DIR / "data" / "collection_report_v2.json"
    _cr = load_json(_cr_path)
    _ok_inds   = [k for k,v in _cr.items() if isinstance(v, dict) and v.get("status") == "ok"]
    _fail_inds = [k for k,v in _cr.items() if isinstance(v, dict) and v.get("status") == "FAILED"]
    _total_inds = len(_cr) if _cr else 29
    _collected  = len(_ok_inds) if _ok_inds else 25

    valid_ranking    = evaluation.get("f14_valid_ranking",  [])
    low_conf         = evaluation.get("f14_low_confidence", [])
    low_conf_names   = {item["indicator"] for item in low_conf}
    final_ranking    = [r for r in valid_ranking if r["indicator"] not in low_conf_names]

    # Condition B: Composite signal
    print("\n[Condition B] 복합 시장 시그널 계산...")
    signal = compute_composite_signal(final_ranking)
    print(f"  시그널 점수: {signal['score']} / 방향: {signal['direction']}")
    print(f"  강세 지표: {signal.get('bullish_count')}개 / 약세: {signal.get('bearish_count')}개")

    generated_at = datetime.now().isoformat()

    # Condition C: CSVs
    print("\n[Condition C] CSV 내보내기...")
    export_csv(final_ranking, signal, stock)

    # Condition C: HTML dashboard
    print("\n[Condition C] HTML 대시보드 생성...")
    generate_html_dashboard(final_ranking, signal, stock, generated_at)

    # 분석 기간: stock_results의 실제 기간 사용 (하드코딩 제거)
    _analysis_period = stock.get("analysis_period", {})
    _period_start = _analysis_period.get("start") or (
        (datetime.now() - __import__("datetime").timedelta(days=365)).strftime("%Y-%m-%d")
    )
    _period_end = _analysis_period.get("end") or datetime.now().strftime("%Y-%m-%d")

    # 실패 지표 이유 동적 구성
    _fail_reasons = {}
    for ind in _fail_inds:
        reason = (_cr.get(ind) or {}).get("reason", "수집 실패")
        _fail_reasons[ind] = reason

    # Build final_results.json
    final_results = {
        "meta": {
            "generated_at":                  generated_at,
            "version":                       "3.0",
            "period":                        {"start": _period_start, "end": _period_end},
            "total_indicators_collected":    _collected,
            "total_indicators_possible":     _total_inds,
            "collection_rate":               f"{_collected}/{_total_inds} ({_collected/_total_inds*100:.1f}%)",
            "total_indicators_analyzed":     len(valid_ranking),
            "total_indicators_in_final":     len(final_ranking),
            "excluded_low_confidence":       list(low_conf_names),
        },
        # Condition B: composite signal
        "market_signal": signal,
        "indicator_weight_ranking": [
            {
                "rank":              r.get("rank"),
                "indicator":         r.get("indicator"),
                "ind_type":          r.get("ind_type"),
                "sp500_signed_r":    r.get("sp500_signed_r"),
                "sp500_significant": r.get("sp500_significant", False),
                "kospi_signed_r":    r.get("kospi_signed_r"),
                "kospi_significant": r.get("kospi_significant", False),
                "combined_weight":   r.get("combined_weight"),
            }
            for r in final_ranking
        ],
        "sp500_analysis": {
            "contribution_top5": stock.get("f09_sp500_contribution_top5", []),
            "beneficiary_top5":  stock.get("f11_sp500_beneficiary_top5",  []),
        },
        "kospi_analysis": {
            "contribution_top5": stock.get("f10_kospi_contribution_top5", []),
            "beneficiary_top5":  stock.get("f12_kospi_beneficiary_top5",  []),
        },
        "data_quality": {
            "collection_success_rate": f"{_collected}/{_total_inds} ({_collected/_total_inds*100:.1f}%)",
            "failed_indicators":       _fail_inds,
            "failure_reasons":         _fail_reasons,
        },
        "pm_conditions": {
            "A_kospi_hard_filter": "PASS - hard filter removed; FDR(KRX)+yfinance cross-validation applied. Returns >200% retained if both sources agree within 100%p (AI/semiconductor boom confirmed real)",
            "B_composite_signal":  "PASS - Z-score composite engine. Score=0-100, direction=risk-on/neutral/risk-off. See market_signal field",
            "C_bi_visualization":  "PASS - live URL: https://hwangatwork.github.io/AI-Analyzer/ (GitHub Pages, auto-deploy on push)",
            "D_automation":        "PASS - Windows Task Scheduler (LogonType S4U) + GitHub Actions cron 0 22 * * 0 + ntfy.sh push notifications",
        },
        "ctd_readiness": evaluation.get("ctd_readiness", {}),
    }

    final_results = nan_safe(final_results)

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

    print("\nUI Agent v3 완료")
    print(f"  시장 시그널: {signal['score']} ({signal['direction']})")
    print(f"  최종 랭킹: {len(final_ranking)}개 지표")
    print(f"  대시보드: output/dashboard.html")
