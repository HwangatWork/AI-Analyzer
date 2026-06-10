# -*- coding: utf-8 -*-
"""
CTD Integration Agent — AI Analyzer → CTD 연동
Done Criteria (CI-1~CI-5):
  CI-1: output/ctd_bridge.json 생성 (AI Analyzer 데이터 CTD 호환 포맷)
  CI-2: CTD index.html에 AI Analyzer 시그널 섹션 삽입 확인
  CI-3: CTD index.html에 AI Analyzer Top5 종목 데이터 삽입 확인
  CI-4: output/ctd_weights.json 생성 (가중치 랭킹 CTD 포맷)
  CI-5: CTD index.html 변경 후 HTML 구조 유효성 (tab-market 닫힘 태그 존재)

연동 대상:
  A) ctd_weights.json — 가중치 랭킹 CTD 알고리즘 반영용
  B) CTD Zone 1D 섹션 — AI Analyzer 시그널 (점수/방향/판단)
  C) CTD 종목 탭 — AI Analyzer Top5 기여/수혜 종목 그룹 추가
"""
import utf8_setup  # noqa: F401

import json
import sys
import re
from pathlib import Path
from datetime import datetime

BASE_DIR  = Path(__file__).parent.parent
OUT_DIR   = BASE_DIR / "output"
CTD_DIR   = Path(r"C:\Users\JY Hwang\Desktop\AI Projects\AI Investment")
CTD_HTML  = CTD_DIR / "frontend" / "index.html"

INDICATOR_KR = {
    "NASDAQ100": "나스닥100", "DOW": "다우존스", "SP500": "S&P500",
    "KOSPI": "코스피", "KOSDAQ": "코스닥", "NIKKEI225": "닛케이225",
    "US10Y": "미국10년물", "DXY": "달러인덱스", "WTI": "WTI원유",
    "HY_SPREAD": "하이일드스프레드", "VIX": "VIX공포지수",
    "BBAND": "볼린저밴드", "RSI14": "RSI(14일)", "STOCH_RSI": "Stoch RSI",
    "MARKET_MOMENTUM": "시장모멘텀", "MARKET_STRENGTH": "시장강도",
    "FOREIGN_NET": "외국인순매수", "INSTITUTION_NET": "기관순매수",
}


def load_results() -> dict:
    path = OUT_DIR / "final_results.json"
    if not path.exists():
        raise FileNotFoundError("output/final_results.json 없음 — 파이프라인 먼저 실행")
    return json.loads(path.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════
# A) ctd_weights.json — 가중치 랭킹
# ══════════════════════════════════════════════════════════════

def build_ctd_weights(data: dict) -> dict:
    ranking = data.get("indicator_weight_ranking", [])
    out = {
        "generated_at": datetime.now().isoformat(),
        "source":       "AI Analyzer v4",
        "methodology":  data.get("meta", {}).get("version", "v4"),
        "indicators":   [],
    }
    for r in ranking:
        out["indicators"].append({
            "rank":          r["rank"],
            "indicator":     r["indicator"],
            "name_kr":       INDICATOR_KR.get(r["indicator"], r["indicator"]),
            "weight":        r["combined_weight"],
            "sp500_r":       r.get("sp500_signed_r"),
            "kospi_r":       r.get("kospi_signed_r"),
            "sp500_sig":     r.get("sp500_significant", False),
            "granger_p":     r.get("sp500_granger_p"),
            "granger_sig":   r.get("sp500_granger_sig", False),
            "lead_lag":      r.get("sp500_lead_lag"),
        })
    return out


# ══════════════════════════════════════════════════════════════
# B) CTD Zone 1D — AI Analyzer 시그널 HTML 섹션
# ══════════════════════════════════════════════════════════════

def build_signal_section(data: dict) -> str:
    sig      = data.get("market_signal", {})
    score    = sig.get("score", 0)
    direction = sig.get("direction", "N/A")
    bull_n   = sig.get("bullish_count", 0)
    total_n  = sig.get("total_signals", 1)
    ranking  = data.get("indicator_weight_ranking", [])
    generated = datetime.now().strftime("%m/%d %H:%M")

    # 방향 색상/뱃지
    if score >= 75:
        color = "var(--gr)"
        badge = '<span class="badge t-bull">매수</span>'
    elif score < 40:
        color = "var(--re)"
        badge = '<span class="badge t-bear">매도</span>'
    else:
        color = "var(--ye)"
        badge = '<span class="badge t-hold">관망</span>'

    dir_kr = {"risk-on": "리스크 온", "risk-off": "리스크 오프", "neutral": "중립"}.get(
        direction, direction
    )

    # Top3 지표 (가중치 기준)
    top3_html = ""
    for r in ranking[:3]:
        name = INDICATOR_KR.get(r["indicator"], r["indicator"])
        lead_lag = r.get("sp500_lead_lag") or 0
        granger = r.get("sp500_granger_sig", False)
        lead_r   = r.get("sp500_lead_r") or r.get("sp500_signed_r") or 0
        lead_tag = f"L{lead_lag}" if lead_lag and lead_lag > 0 else "동행"
        g_tag    = " ·G✓" if granger else ""
        arrow    = "▲" if lead_r >= 0 else "▼"
        c        = "var(--gr)" if lead_r >= 0 else "var(--re)"
        top3_html += f"""<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--gb)">
          <span style="font-size:11px;color:var(--t2)">{name}</span>
          <span style="font-family:var(--font-mono);font-size:10px;color:{c}">{arrow} {abs(lead_r):.3f} [{lead_tag}{g_tag}]</span>
        </div>"""

    section = f"""
    <!-- ════ AI Analyzer 시그널 (자동 삽입) ════ -->
    <div class="section-card" id="ai-analyzer-signal" style="margin-top:var(--sp-md)">
      <div class="sec-label">Zone 1D — AI Analyzer 시그널 <span class="badge" style="background:var(--acd);color:var(--ac);border-color:var(--acb)">자동</span></div>
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0 8px">
        <div>
          <div style="font-size:10px;color:var(--t4);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px">종합 시그널 점수</div>
          <div style="display:flex;align-items:baseline;gap:6px">
            <div style="font-family:var(--font-mono);font-size:36px;font-weight:700;color:{color};letter-spacing:-.04em">{score:.1f}</div>
            <div style="font-size:12px;color:var(--t3)">/ 100</div>
          </div>
          <div style="font-size:11px;color:var(--t3);margin-top:2px">{dir_kr} · 강세 {bull_n}/{total_n}개</div>
        </div>
        <div style="text-align:right">
          {badge}
          <div style="font-size:10px;color:var(--t4);margin-top:6px">{generated} 기준</div>
        </div>
      </div>
      <div style="font-size:10px;color:var(--t4);margin:8px 0 4px;letter-spacing:.04em;text-transform:uppercase">핵심 지표 Top 3 (Granger 인과 기반)</div>
      {top3_html}
      <div style="font-size:10px;color:var(--t4);margin-top:8px;line-height:1.5">
        방법론: 시차상관(Lag 1~5) + Granger 인과검정 + 동행지수 페널티 보정<br>
        <span style="color:var(--ac)">→ AI Analyzer 상세</span>: <a href="https://hwangatwork.github.io/AI-Analyzer/" style="color:var(--ac);text-decoration:none" target="_blank">hwangatwork.github.io/AI-Analyzer</a>
      </div>
    </div>
    <!-- /AI Analyzer 시그널 -->"""
    return section


# ══════════════════════════════════════════════════════════════
# C) CTD 종목 탭 — AI Analyzer Top5 데이터 주입
# ══════════════════════════════════════════════════════════════

def build_stock_js(data: dict) -> str:
    sp_contrib  = data.get("sp500_analysis", {}).get("contribution_top5", [])
    ksp_contrib = data.get("kospi_analysis", {}).get("contribution_top5", [])

    stocks_js = []

    for s in ksp_contrib[:5]:
        ticker = s.get("ticker", "").replace(".KS", "")
        name   = s.get("name", ticker)
        ret    = s.get("stock_return_pct", 0)
        score  = s.get("contribution_score", 0)
        note   = s.get("spinoff_note", "")
        verdict = "매수" if ret > 50 else "관망"
        tag = " ⚠" if s.get("spinoff_event") else ""
        stocks_js.append({
            "code":    ticker,
            "name":    f"{name}{tag}",
            "group":   "domestic",
            "ai_tag":  "AI기여",
            "ai_score": round(ret, 1),
            "ai_note": note or f"코스피 기여도 {score:.2f} · 1Y {ret:+.1f}%",
            "verdict": verdict,
        })

    for s in sp_contrib[:5]:
        ticker = s.get("ticker", "")
        name   = s.get("name", ticker)
        ret    = s.get("stock_return_pct", 0)
        score  = s.get("contribution_score", 0)
        note   = s.get("spinoff_note", "")
        verdict = "매수" if ret > 50 else "관망"
        tag = " ⚠" if s.get("spinoff_event") else ""
        stocks_js.append({
            "code":    ticker,
            "name":    f"{name}{tag}",
            "group":   "overseas",
            "ai_tag":  "AI기여",
            "ai_score": round(ret, 1),
            "ai_note": note or f"S&P500 기여도 {score:.2f} · 1Y {ret:+.1f}%",
            "verdict": verdict,
        })

    js_array = json.dumps(stocks_js, ensure_ascii=False, indent=2)

    return f"""
// ── AI Analyzer 연동 데이터 (자동 생성 {datetime.now().strftime('%Y-%m-%d %H:%M')}) ──
const AI_ANALYZER_STOCKS = {js_array};

function injectAIAnalyzerStocks() {{
  // AI Analyzer 종목을 기존 STOCKS 객체에 병합
  AI_ANALYZER_STOCKS.forEach(s => {{
    if (!STOCKS[s.code]) {{
      STOCKS[s.code] = {{
        name:    s.name,
        group:   s.group,
        verdict: s.verdict,
        score:   7.5,
        ai_tag:  s.ai_tag,
        ai_note: s.ai_note,
        axes: [7,6,8,7,7,6],
        ctd_chain: [],
        summary: s.ai_note,
        signal_text: `AI Analyzer 1Y 수익률 ${{s.ai_score > 0 ? '+' : ''}}${{s.ai_score}}%`,
      }};
    }}
  }});
  // 칩 재렌더
  if (typeof renderChips === 'function') renderChips();
}}

// DOM 준비 후 주입
if (document.readyState === 'loading') {{
  document.addEventListener('DOMContentLoaded', injectAIAnalyzerStocks);
}} else {{
  injectAIAnalyzerStocks();
}}
// ── /AI Analyzer 연동 ──"""


# ══════════════════════════════════════════════════════════════
# CTD HTML 패치
# ══════════════════════════════════════════════════════════════

def patch_ctd_html(data: dict) -> bool:
    if not CTD_HTML.exists():
        print(f"[ERROR] CTD index.html 없음: {CTD_HTML}")
        return False

    html = CTD_HTML.read_text(encoding="utf-8")

    # ── B) Zone 1D 시그널 섹션 삽입 ──────────────────────────
    signal_section = build_signal_section(data)
    SIGNAL_MARKER  = "<!-- /AI Analyzer 시그널 -->"
    END_MARKET     = "  </div><!-- /tab-market -->"

    if SIGNAL_MARKER in html:
        # 기존 섹션 교체
        pattern = r"    <!-- ════ AI Analyzer 시그널.*?<!-- /AI Analyzer 시그널 -->"
        html = re.sub(pattern, signal_section.strip(), html, flags=re.DOTALL)
        print("  [B] AI Analyzer 시그널 섹션 교체 완료")
    elif END_MARKET in html:
        # 최초 삽입 (tab-market 닫기 전에)
        html = html.replace(END_MARKET, signal_section + "\n\n  " + END_MARKET)
        print("  [B] AI Analyzer 시그널 섹션 신규 삽입 완료")
    else:
        print("  [B] WARNING: tab-market 삽입 위치를 찾지 못함")

    # ── C) 종목 JS 데이터 주입 ───────────────────────────────
    stock_js = build_stock_js(data)
    STOCK_MARKER_START = "// ── AI Analyzer 연동 데이터"
    STOCK_MARKER_END   = "// ── /AI Analyzer 연동 ──"
    SCRIPT_END         = "</script>"

    if STOCK_MARKER_START in html:
        # 기존 블록 교체
        pattern = r"// ── AI Analyzer 연동 데이터.*?// ── /AI Analyzer 연동 ──"
        html = re.sub(pattern, stock_js.strip(), html, flags=re.DOTALL)
        print("  [C] AI Analyzer 종목 데이터 교체 완료")
    else:
        # </script> 태그 직전에 삽입 (마지막 스크립트 블록)
        last_script_end = html.rfind(SCRIPT_END)
        if last_script_end >= 0:
            html = html[:last_script_end] + "\n" + stock_js + "\n" + html[last_script_end:]
            print("  [C] AI Analyzer 종목 데이터 신규 삽입 완료")
        else:
            print("  [C] WARNING: </script> 위치 못 찾음")

    CTD_HTML.write_text(html, encoding="utf-8")
    return True


# ══════════════════════════════════════════════════════════════
# Done Criteria 자체 검증
# ══════════════════════════════════════════════════════════════

def _done_criteria(data: dict) -> None:
    print("\n[CTD] Done Criteria 검증")
    html = CTD_HTML.read_text(encoding="utf-8") if CTD_HTML.exists() else ""

    criteria = {
        "CI-1 ctd_bridge.json 생성":    (OUT_DIR / "ctd_bridge.json").exists(),
        "CI-2 시그널 섹션 삽입":         "ai-analyzer-signal" in html,
        "CI-3 종목 데이터 삽입":         "AI_ANALYZER_STOCKS" in html,
        "CI-4 ctd_weights.json 생성":   (OUT_DIR / "ctd_weights.json").exists(),
        "CI-5 HTML 구조 유효성":         "</div><!-- /tab-market -->" in html,
    }

    fails = []
    for k, v in criteria.items():
        s = "PASS" if v else "FAIL"
        print(f"  {s}  {k}")
        if not v:
            fails.append(k)

    if fails:
        print(f"\n[FAIL] Done Criteria {len(fails)}개 미충족")
        sys.exit(1)
    else:
        print("\n[PASS] Done Criteria CI-1~CI-5 모두 통과")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("CTD Integration Agent — AI Analyzer → CTD 연동")
    print("=" * 60)

    data = load_results()
    sig  = data.get("market_signal", {})
    print(f"  시그널: {sig.get('score')} ({sig.get('direction')})")

    # A) ctd_weights.json
    print("\n[A] 가중치 랭킹 CTD 포맷 출력")
    weights = build_ctd_weights(data)
    wpath   = OUT_DIR / "ctd_weights.json"
    wpath.write_text(json.dumps(weights, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {wpath} ({len(weights['indicators'])}개 지표)")

    # B+C) ctd_bridge.json (통합 브리지)
    print("\n[Bridge] ctd_bridge.json 생성")
    bridge = {
        "generated_at": datetime.now().isoformat(),
        "source":       "AI Analyzer v4",
        "signal": {
            "score":         sig.get("score"),
            "direction":     sig.get("direction"),
            "bullish_count": sig.get("bullish_count"),
            "total_signals": sig.get("total_signals"),
        },
        "top_indicators": [
            {
                "rank":     r["rank"],
                "name":     r["indicator"],
                "name_kr":  INDICATOR_KR.get(r["indicator"], r["indicator"]),
                "weight":   r["combined_weight"],
                "sp500_r":  r.get("sp500_signed_r"),
                "lead_lag": r.get("sp500_lead_lag"),
                "granger":  r.get("sp500_granger_sig", False),
            }
            for r in data.get("indicator_weight_ranking", [])[:10]
        ],
        "sp500_top5":  data.get("sp500_analysis", {}).get("contribution_top5", [])[:5],
        "kospi_top5":  data.get("kospi_analysis", {}).get("contribution_top5", [])[:5],
    }
    bpath = OUT_DIR / "ctd_bridge.json"
    bpath.write_text(json.dumps(bridge, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {bpath}")

    # B+C) CTD HTML 패치
    print("\n[B+C] CTD index.html 패치")
    success = patch_ctd_html(data)
    if not success:
        print("[ERROR] CTD HTML 패치 실패")
        sys.exit(1)

    # Done Criteria
    _done_criteria(data)

    print("\nCTD Integration Agent 완료")
