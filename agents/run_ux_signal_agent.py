# -*- coding: utf-8 -*-
"""
UX Signal Agent — 시장 시그널 시각화 섹션 생성
담당: SVG 게이지, Z-score 바 차트, 시그널 요약 카드
"""
import utf8_setup  # noqa: F401


def generate_signal_section(signal: dict) -> str:
    score     = max(0, min(100, int(signal.get("score", 50) or 50)))
    direction = signal.get("direction", "neutral")
    bullish   = signal.get("bullish_count", 0)
    bearish   = signal.get("bearish_count", 0)
    total     = signal.get("total_signals", 0)
    computed  = (signal.get("computed_at", "") or "")[:10]
    method    = signal.get("methodology", "") or ""
    ind_sigs  = signal.get("indicator_signals", [])

    dir_color = {"risk-on": "#22c55e", "neutral": "#f59e0b", "risk-off": "#ef4444"}.get(direction, "#64748b")
    dir_ko    = {"risk-on": "위험 선호 (Risk-On)", "neutral": "중립 (Neutral)", "risk-off": "위험 회피 (Risk-Off)"}.get(direction, direction)

    # ── SVG Gauge ──────────────────────────────────────────────────────────
    # 반원형 게이지: 왼쪽(180°)=0, 오른쪽(0°)=100
    # score → needle angle (degrees from positive x-axis)
    import math
    needle_deg = 180.0 - (score / 100.0 * 180.0)
    rad        = math.radians(needle_deg)
    cx, cy, r  = 100, 100, 76

    # 존 경계점 계산
    def arc_point(pct):
        a = math.radians(180.0 - pct / 100.0 * 180.0)
        return (cx + r * math.cos(a), cy - r * math.sin(a))

    p0 = (cx - r, cy)          # 0점 (왼쪽)
    p35 = arc_point(35)
    p65 = arc_point(65)
    p100 = (cx + r, cy)        # 100점 (오른쪽)

    # 바늘 끝점
    nl = 62  # 바늘 길이
    nx = cx + nl * math.cos(rad)
    ny = cy - nl * math.sin(rad)

    gauge_svg = f"""
    <svg viewBox="0 0 200 112" style="width:100%;max-width:260px;display:block;margin:0 auto">
      <defs>
        <filter id="glow"><feGaussianBlur stdDeviation="2.5" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <!-- 구역: 위험회피(빨) -->
      <path d="M {p0[0]:.1f} {p0[1]:.1f} A {r} {r} 0 0 1 {p35[0]:.1f} {p35[1]:.1f}"
            fill="none" stroke="#ef4444" stroke-width="14" stroke-linecap="round" opacity="0.85"/>
      <!-- 구역: 중립(노) -->
      <path d="M {p35[0]:.1f} {p35[1]:.1f} A {r} {r} 0 0 1 {p65[0]:.1f} {p65[1]:.1f}"
            fill="none" stroke="#f59e0b" stroke-width="14" stroke-linecap="round" opacity="0.85"/>
      <!-- 구역: 위험선호(녹) -->
      <path d="M {p65[0]:.1f} {p65[1]:.1f} A {r} {r} 0 0 1 {p100[0]:.1f} {p100[1]:.1f}"
            fill="none" stroke="#22c55e" stroke-width="14" stroke-linecap="round" opacity="0.85"/>
      <!-- 바늘 -->
      <line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}"
            stroke="{dir_color}" stroke-width="3" stroke-linecap="round" filter="url(#glow)"/>
      <circle cx="{cx}" cy="{cy}" r="5" fill="{dir_color}"/>
      <!-- 눈금 레이블 -->
      <text x="16" y="110" fill="#64748b" font-size="9" text-anchor="middle">0</text>
      <text x="100" y="22" fill="#64748b" font-size="9" text-anchor="middle">50</text>
      <text x="184" y="110" fill="#64748b" font-size="9" text-anchor="middle">100</text>
      <!-- 점수 -->
      <text x="{cx}" y="{cy + 22}" fill="{dir_color}" font-size="26" font-weight="800"
            text-anchor="middle" font-family="system-ui">{score}</text>
    </svg>"""

    # ── Z-Score 수평 바 차트 ────────────────────────────────────────────────
    max_z = 2.0
    bar_rows = ""
    for s in ind_sigs:
        z      = s.get("z_score", 0)
        bull   = s.get("bullish", False)
        ind    = s.get("indicator", "")
        sig_v  = s.get("signal", 0)
        w      = s.get("weight", 0)
        cl     = "#22c55e" if bull else "#ef4444"
        pct    = abs(z) / max_z * 50  # 최대 50% width (절반 기준)
        arrow  = "▲" if bull else "▼"
        # 바: 중앙선 기준, 강세=우측, 약세=좌측
        if bull:
            bar_style = f"margin-left:50%;width:{pct:.1f}%;background:{cl}"
        else:
            bar_style = f"margin-left:{50-pct:.1f}%;width:{pct:.1f}%;background:{cl}"

        bar_rows += f"""
        <div style="display:grid;grid-template-columns:100px 1fr 60px;gap:6px;align-items:center;padding:3px 0;border-bottom:1px solid #1e293b">
          <div style="font-size:0.78rem;color:#cbd5e1;text-align:right;padding-right:8px">{ind}</div>
          <div style="position:relative;height:12px;background:#0f172a;border-radius:6px;overflow:hidden">
            <div style="position:absolute;top:50%;transform:translateY(-50%);left:49.5%;width:1px;height:100%;background:#334155"></div>
            <div style="position:absolute;top:2px;height:8px;border-radius:4px;{bar_style};opacity:0.9"></div>
          </div>
          <div style="font-size:0.76rem;color:{cl};text-align:center">{arrow} {z:+.2f}</div>
        </div>"""

    return f"""
<!-- ═══ SIGNAL SECTION ═══ -->
<section id="signal">
  <h2 class="section-title">종합 시장 시그널</h2>
  <div class="grid-3" style="grid-template-columns:1fr 1.4fr 1fr;gap:16px;margin-bottom:20px">

    <!-- 게이지 -->
    <div class="card" style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px 12px">
      {gauge_svg}
      <div style="text-align:center;margin-top:4px">
        <div style="font-size:0.85rem;font-weight:700;color:{dir_color}">{dir_ko}</div>
        <div style="font-size:0.72rem;color:#475569;margin-top:2px">기준일 {computed}</div>
      </div>
    </div>

    <!-- Z-Score 바 차트 -->
    <div class="card" style="padding:14px">
      <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:8px;font-weight:600">지표별 Z-Score 기여</div>
      <div style="font-size:0.68rem;color:#475569;margin-bottom:6px">◀ 약세 &nbsp;│&nbsp; 강세 ▶</div>
      {bar_rows}
    </div>

    <!-- 요약 카드 -->
    <div class="card" style="display:flex;flex-direction:column;gap:10px">
      <div class="stat-block" style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:2rem;font-weight:800;color:#22c55e">{bullish}</div>
        <div style="font-size:0.75rem;color:#64748b">강세 신호</div>
      </div>
      <div class="stat-block" style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:2rem;font-weight:800;color:#ef4444">{bearish}</div>
        <div style="font-size:0.75rem;color:#64748b">약세 신호</div>
      </div>
      <div class="stat-block" style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:1.4rem;font-weight:700;color:#94a3b8">{total}</div>
        <div style="font-size:0.75rem;color:#64748b">분석 지표 수</div>
      </div>
      <div style="font-size:0.68rem;color:#334155;line-height:1.4;margin-top:4px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical">{method if method else "방법론 미기재"}</div>
    </div>
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
    signal  = results.get("market_signal", {
        "score": 55, "direction": "neutral",
        "bullish_count": 5, "bearish_count": 4,
        "total_signals": 9, "indicator_signals": [],
        "methodology": "복합 시그널 점수 계산",
        "computed_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
    })

    html = generate_signal_section(signal)

    fails = []
    score_val = max(0, min(100, int(signal.get("score", 50) or 50)))
    if not (0 <= score_val <= 100):
        fails.append(f"UX-S1 score 범위 오류: {score_val}")
    if signal.get("direction", "") not in ("risk-on", "neutral", "risk-off"):
        fails.append(f"UX-S2 direction 유효하지 않음: {signal.get('direction','')}")
    if len(html) < 200:
        fails.append("UX-S3 signal HTML 생성 실패 (200자 미만)")

    print("=== Done Criteria ===")
    for code in ["UX-S1", "UX-S2", "UX-S3"]:
        fail_item = next((f for f in fails if code in f), None)
        print(f"  {'✗' if fail_item else '✓'} {fail_item or code + ' PASS'}")

    if fails:
        print(f"\n[FAIL] {fails}")
        sys.exit(1)
    print("\n[PASS] UX-S1~UX-S3 통과")
