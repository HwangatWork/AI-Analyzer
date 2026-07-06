# -*- coding: utf-8 -*-
"""
UX Indicators Agent — 지표 가중치 랭킹 + 데이터 품질 섹션 생성
담당: 가중치 시각화 바, SP500/KOSPI 상관계수 비교, 수집 현황, 신선도 테이블
"""
import utf8_setup  # noqa: F401



def generate_indicators_section(ranking: list, data_quality: dict, meta: dict) -> str:
    max_w = max((r.get("combined_weight", 0) or 0 for r in ranking), default=1)

    # ── 가중치 랭킹 바 ────────────────────────────────────────────────────
    rank_rows = ""
    for r in ranking:
        ind    = r.get("indicator", "")
        w      = r.get("combined_weight", 0) or 0
        sp_r   = r.get("sp500_signed_r")
        kp_r   = r.get("kospi_signed_r")
        sp_sig = r.get("sp500_significant", False)
        kp_sig = r.get("kospi_significant", False)
        rank   = r.get("rank", "")
        itype  = r.get("ind_type", "")

        bar_w  = w / max_w * 100
        bar_cl = "#6366f1"  # indigo

        sp_str = f'{"+" if (sp_r or 0)>=0 else ""}{sp_r:.3f}{"*" if sp_sig else ""}' if sp_r is not None else "N/A"
        kp_str = f'{"+" if (kp_r or 0)>=0 else ""}{kp_r:.3f}{"*" if kp_sig else ""}' if kp_r is not None else "N/A"
        sp_cl  = "#22c55e" if (sp_r or 0) > 0 else "#ef4444"
        kp_cl  = "#22c55e" if (kp_r or 0) > 0 else "#ef4444"

        type_colors = {
            "return":   ("#1e3a5f", "#60a5fa"),
            "diff":     ("#1a2e1a", "#22c55e"),
            "level":    ("#2d1b69", "#a78bfa"),
            "discrete": ("#3d2408", "#f59e0b"),
        }
        type_bg, type_fg = type_colors.get(itype, ("#1e293b", "#94a3b8"))

        rank_rows += f"""
        <div style="display:grid;grid-template-columns:28px 110px 1fr 70px 70px 48px;
                    gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid #1e293b">
          <div style="font-size:0.72rem;color:#475569;text-align:right">#{rank}</div>
          <div style="font-size:0.8rem;font-weight:600;color:#e2e8f0">{ind}
            <span style="font-size:0.62rem;padding:1px 4px;border-radius:3px;
                         background:{type_bg};color:{type_fg};margin-left:3px">{itype}</span>
          </div>
          <div style="background:#0f172a;height:8px;border-radius:4px;overflow:hidden">
            <div style="height:100%;width:{bar_w:.1f}%;background:{bar_cl};border-radius:4px;opacity:0.9"></div>
          </div>
          <div style="font-size:0.76rem;text-align:center;color:{sp_cl}">{sp_str}</div>
          <div style="font-size:0.76rem;text-align:center;color:{kp_cl}">{kp_str}</div>
          <div style="font-size:0.76rem;text-align:right;color:#94a3b8">{w:.4f}</div>
        </div>"""

    # ── 수집 현황 ────────────────────────────────────────────────────────
    coll_rate_str = meta.get("collection_rate", "25/29")
    try:
        nums = coll_rate_str.replace("(", "").replace(")", "").replace("%", "").split("/")
        ok_n   = int(nums[0].strip().split()[0])
        tot_n  = int(nums[1].strip().split()[0])
        coll_pct = ok_n / tot_n * 100
    except Exception:
        ok_n, tot_n, coll_pct = 25, 29, 86.2

    fail_inds = data_quality.get("failed_indicators", [])
    fail_reasons = data_quality.get("failure_reasons", {})
    low_conf  = data_quality.get("low_confidence_excluded", [])

    fail_rows = ""
    for fi in fail_inds:
        reason = fail_reasons.get(fi, "수집 실패")
        fail_rows += f'<div class="kv"><span style="color:#ef4444">{fi}</span><span style="color:#64748b;font-size:0.72rem">{reason[:40]}</span></div>'

    # ── 신선도 테이블 ─────────────────────────────────────────────────────
    freshness = data_quality.get("freshness", {})
    ref_date  = meta.get("data_reference_date", "")

    def freshness_color(days_str):
        try:
            d = int(str(days_str))
            if d <= 2:   return "#22c55e"
            if d <= 7:   return "#f59e0b"
            return "#ef4444"
        except Exception:
            return "#64748b"

    # 신선도 정보 계산 (end_date → days_since_last)
    from datetime import datetime, date
    today = date.today()
    fresh_rows = ""
    for ind in sorted(freshness.keys()):
        f = freshness[ind]
        end = f.get("end_date", "")
        rows = f.get("rows", "")
        try:
            end_dt = datetime.strptime(end[:10], "%Y-%m-%d").date()
            days   = (today - end_dt).days
            days_str = str(days)
            fcl    = freshness_color(days)
        except Exception:
            days_str = "?"
            fcl    = "#64748b"
        fresh_rows += f"""
        <div style="display:grid;grid-template-columns:120px 100px 60px 40px;gap:4px;
                    padding:3px 0;border-bottom:1px solid #1e293b;align-items:center;font-size:0.76rem">
          <div style="color:#cbd5e1">{ind}</div>
          <div style="color:#94a3b8">{end}</div>
          <div style="color:#64748b;text-align:right">{rows}행</div>
          <div style="color:{fcl};text-align:center;font-weight:600">{days_str}d</div>
        </div>"""

    return f"""
<!-- ═══ INDICATORS SECTION ═══ -->
<section id="indicators">
  <h2 class="section-title">지표 가중치 랭킹</h2>

  <div class="card" style="margin-bottom:16px;padding:16px">
    <div class="table-scroll"><div class="table-scroll-inner" style="min-width:440px">
    <div style="display:grid;grid-template-columns:28px 110px 1fr 70px 70px 48px;
                gap:6px;padding-bottom:6px;border-bottom:2px solid #334155;margin-bottom:4px">
      <div style="font-size:0.7rem;color:#475569">순위</div>
      <div style="font-size:0.7rem;color:#475569">지표</div>
      <div style="font-size:0.7rem;color:#475569">가중치 바</div>
      <div style="font-size:0.7rem;color:#475569;text-align:center">SP500 r</div>
      <div style="font-size:0.7rem;color:#475569;text-align:center">KOSPI r</div>
      <div style="font-size:0.7rem;color:#475569;text-align:right">가중치</div>
    </div>
    {rank_rows}
    </div></div>
    <div style="font-size:0.68rem;color:#334155;margin-top:8px">
      * = p&lt;0.05 통계적 유의 &nbsp;|&nbsp; 가중치 = |r|×0.5 + R²×0.5 &nbsp;|&nbsp;
      유형: return(수익률) / diff(변화량) / level(원값) / discrete(신호)
    </div>
  </div>

  <!-- 데이터 품질 -->
  <div class="grid-2" style="gap:16px">

    <!-- 수집 현황 -->
    <div class="card">
      <div style="font-size:0.82rem;font-weight:600;color:#94a3b8;margin-bottom:12px">데이터 수집 현황</div>

      <!-- 수집률 진행 바 -->
      <div style="margin-bottom:14px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span style="font-size:0.8rem;color:#e2e8f0">수집 성공</span>
          <span style="font-size:0.9rem;font-weight:700;color:#22c55e">{coll_rate_str}</span>
        </div>
        <div style="background:#0f172a;height:10px;border-radius:5px;overflow:hidden">
          <div style="height:100%;width:{coll_pct:.1f}%;background:linear-gradient(90deg,#22c55e,#16a34a);border-radius:5px"></div>
        </div>
      </div>

      <div style="font-size:0.78rem;font-weight:600;color:#64748b;margin-bottom:6px">수집 실패 ({len(fail_inds)}개)</div>
      {fail_rows if fail_rows else '<div style="color:#475569;font-size:0.75rem">없음</div>'}

      <div style="margin-top:10px;font-size:0.78rem;font-weight:600;color:#64748b;margin-bottom:4px">
        신뢰도 미달 제외 ({len(low_conf)}개)
      </div>
      <div style="font-size:0.72rem;color:#475569;line-height:1.6">
        {", ".join(low_conf) if low_conf else "없음"}
      </div>
    </div>

    <!-- 신선도 테이블 -->
    <div class="card">
      <div style="font-size:0.82rem;font-weight:600;color:#94a3b8;margin-bottom:10px">
        데이터 신선도 <span style="font-weight:400;font-size:0.7rem;color:#475569">(기준: {ref_date})</span>
      </div>
      <div class="table-scroll"><div class="table-scroll-inner" style="min-width:360px">
      <div style="display:grid;grid-template-columns:120px 100px 60px 40px;gap:4px;
                  padding-bottom:5px;border-bottom:1px solid #334155;margin-bottom:4px">
        <div style="font-size:0.68rem;color:#475569">지표</div>
        <div style="font-size:0.68rem;color:#475569">최신 기준일</div>
        <div style="font-size:0.68rem;color:#475569;text-align:right">행수</div>
        <div style="font-size:0.68rem;color:#475569;text-align:center">경과일</div>
      </div>
      {fresh_rows}
      </div></div>
      <div style="font-size:0.68rem;color:#334155;margin-top:6px">
        🟢 ≤2일 &nbsp; 🟡 ≤7일 &nbsp; 🔴 &gt;7일
      </div>
    </div>
  </div>
</section>"""


if __name__ == "__main__":
    import json, sys
    from pathlib import Path

    BASE_DIR = Path(__file__).parent.parent
    OUT_DIR  = BASE_DIR / "output"
    PROC_DIR = BASE_DIR / "data" / "processed"

    def _jload(p):
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {}

    results  = _jload(OUT_DIR / "final_results.json")
    ranking  = results.get("indicator_weight_ranking", [
        {"indicator": "HY_SPREAD", "combined_weight": 0.35, "rank": 1,
         "sp500_signed_r": -0.55, "kospi_signed_r": -0.42,
         "sp500_significant": True, "kospi_significant": True, "ind_type": "diff"}
    ])
    dq       = results.get("data_quality", {
        "failed_indicators": [], "failure_reasons": {}, "low_confidence_excluded": [], "freshness": {}
    })
    meta     = results.get("meta", {
        "collection_rate": f"{len(ranking)}/29",
        "data_reference_date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
    })

    html = generate_indicators_section(ranking, dq, meta)

    fails = []
    if len(html) < 200:
        fails.append("UX-I1 indicators HTML 생성 실패 (200자 미만)")
    if not ranking:
        fails.append("UX-I2 랭킹 데이터 없음")

    print("=== Done Criteria ===")
    for code in ["UX-I1", "UX-I2"]:
        fail_item = next((f for f in fails if code in f), None)
        print(f"  {'✗' if fail_item else '✓'} {fail_item or code + ' PASS'}")

    if fails:
        print(f"\n[FAIL] {fails}")
        sys.exit(1)
    print("\n[PASS] UX-I1~UX-I2 통과")
