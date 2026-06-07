# -*- coding: utf-8 -*-
"""
Evaluator Agent v2 - F13, F14 (개선판)
수정사항:
  - 타겟 변수(SP500/KOSPI)를 신뢰도 평가 대상에서 제외
  - 신뢰도 점수 기준 명확화
  - 데이터 신선도 정보 추가 (PM 요청)
  - CTD 연동 준비 여부 판단 필드 추가
"""

import json, numpy as np, pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR  = Path(__file__).parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
RAW_DIR   = BASE_DIR / "data" / "raw"

TARGET_VARS          = {"SP500", "KOSPI"}   # Fix: 타겟 변수 제외
LOW_CONF_THRESHOLD   = 70
AUTO_EXCLUDE_REASON  = "신뢰도 70점 미만 - 자동 제외 (Option A)"


def get_data_freshness(name: str) -> dict:
    """데이터 신선도 정보 (PM 요청: 언제 기준 데이터인지 명시)"""
    path = RAW_DIR / f"{name}.parquet"
    if not path.exists():
        return {"available": False}
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        return {
            "available":  True,
            "rows":       len(df),
            "start_date": df["date"].min().strftime("%Y-%m-%d"),
            "end_date":   df["date"].max().strftime("%Y-%m-%d"),
            "days_since_last": (pd.Timestamp.now() - df["date"].max()).days,
        }
    except Exception:
        return {"available": False}


def compute_confidence(ind_name: str, sp_data: dict, ksp_data: dict) -> dict:
    """
    신뢰도 점수 (0-100):
      데이터 충분성  30pt (300행 이상 만점)
      통계적 유의성  30pt (p < 0.05)
      상관 강도      20pt (|r| 비례)
      이상값 청결도  20pt (IQR 3배 기준)
    """
    def score_one(data: dict, market: str) -> tuple[float, dict]:
        if not data or data.get("status") == "FAILED":
            return 0.0, {"reason": "데이터 없음"}
        n   = data.get("corr", {}).get("n", 0)
        r   = abs(data.get("corr", {}).get("pearson_r") or 0)
        p   = data.get("corr", {}).get("pearson_p")
        r2  = data.get("regression", {}).get("r2") or 0

        outlier_ratio = 0.0
        path = RAW_DIR / f"{ind_name}.parquet"
        if path.exists():
            try:
                vals = pd.to_numeric(pd.read_parquet(path)["value"], errors="coerce").dropna()
                if len(vals) > 10:
                    q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
                    iqr = q3 - q1
                    outlier_ratio = ((vals < q1 - 3*iqr) | (vals > q3 + 3*iqr)).mean()
            except Exception:
                pass

        data_pt     = min(30.0, n / 10)
        sig_pt      = 30.0 if (p is not None and p < 0.05) else 0.0
        corr_pt     = min(20.0, r * 20)
        outlier_pt  = max(0.0, 20.0 - outlier_ratio * 100)
        total       = data_pt + sig_pt + corr_pt + outlier_pt

        return round(total, 1), {
            "n": n, "r": round(r, 4),
            "p": round(p, 6) if p else None,
            "r2": round(r2, 4),
            "outlier_ratio": round(float(outlier_ratio), 4),
            "breakdown": {
                "data_score":    round(data_pt, 1),
                "sig_score":     sig_pt,
                "corr_score":    round(corr_pt, 1),
                "outlier_score": round(outlier_pt, 1),
            }
        }

    sp_score,  sp_detail  = score_one(sp_data,  "sp500")
    ksp_score, ksp_detail = score_one(ksp_data, "kospi")
    combined = max(sp_score, ksp_score)

    freshness = get_data_freshness(ind_name)

    return {
        "sp500_confidence":    sp_score,
        "kospi_confidence":    ksp_score,
        "combined_confidence": combined,
        "freshness":           freshness,
        "details":             {"sp500": sp_detail, "kospi": ksp_detail},
    }


def filter_ranking(ranking: list) -> tuple[list, list]:
    valid, filtered = [], []
    for item in ranking:
        w  = item.get("combined_weight")
        sp = item.get("sp500_abs_r")
        kp = item.get("kospi_abs_r")

        is_nan = (w is None or (isinstance(w, float) and np.isnan(w))
                  or (sp is not None and isinstance(sp, float) and np.isnan(sp))
                  or (kp is not None and isinstance(kp, float) and np.isnan(kp)))

        if is_nan:
            item["filter_reason"] = "NaN (데이터 부족 또는 상수 계열)"
            filtered.append(item)
        elif not item.get("sp500_significant") and not item.get("kospi_significant"):
            item["filter_reason"] = "통계적 비유의 (p >= 0.05 양 시장)"
            filtered.append(item)
        else:
            valid.append(item)
    return valid, filtered


if __name__ == "__main__":
    print("=" * 60)
    print("EVALUATOR AGENT v2 - Phase 4 (F13, F14)")
    print("=" * 60)

    ap = PROC_DIR / "analysis_results.json"
    if not ap.exists():
        print("[ERROR] analysis_results.json 없음"); exit(1)

    analysis   = json.loads(ap.read_text(encoding="utf-8"))
    sp500_data = analysis.get("f06_sp500_analysis", {})
    kospi_data = analysis.get("f07_kospi_analysis", {})
    ranking    = analysis.get("f08_weight_ranking", [])

    # Fix: 타겟 변수 제외
    sp500_data = {k: v for k, v in sp500_data.items() if k not in TARGET_VARS}
    kospi_data = {k: v for k, v in kospi_data.items() if k not in TARGET_VARS}
    all_inds   = sorted(set(list(sp500_data.keys()) + list(kospi_data.keys())))

    # F13
    print(f"\n[F13] 통계적 유의성 확인 ({len(all_inds)}개 지표)")
    sig_report  = {}
    sp_sig_cnt  = ksp_sig_cnt = 0

    for ind in all_inds:
        sp  = sp500_data.get(ind, {})
        ksp = kospi_data.get(ind, {})
        sp_p  = sp.get("corr", {}).get("pearson_p")
        ksp_p = ksp.get("corr", {}).get("pearson_p")
        sp_s  = sp_p  is not None and sp_p  < 0.05
        ksp_s = ksp_p is not None and ksp_p < 0.05
        if sp_s:  sp_sig_cnt  += 1
        if ksp_s: ksp_sig_cnt += 1
        sig_report[ind] = {
            "sp500_p": round(sp_p, 6) if sp_p else None, "sp500_significant": sp_s,
            "kospi_p": round(ksp_p, 6) if ksp_p else None, "kospi_significant": ksp_s,
        }

    print(f"  SP500 유의: {sp_sig_cnt}/{len(all_inds)}개")
    print(f"  KOSPI 유의: {ksp_sig_cnt}/{len(all_inds)}개")

    # F14
    print("\n[F14] 이상값 필터링 및 신뢰도 점수")
    conf_results = {}
    low_conf     = []

    for ind in all_inds:
        conf = compute_confidence(ind, sp500_data.get(ind, {}), kospi_data.get(ind, {}))
        conf_results[ind] = conf
        if conf["combined_confidence"] < LOW_CONF_THRESHOLD:
            low_conf.append({
                "indicator":           ind,
                "combined_confidence": conf["combined_confidence"],
                "sp500_confidence":    conf["sp500_confidence"],
                "kospi_confidence":    conf["kospi_confidence"],
                "auto_action":         AUTO_EXCLUDE_REASON,
            })

    # 데이터 신선도 요약 (PM 요청)
    freshness_report = {}
    for ind in all_inds:
        f = conf_results[ind]["freshness"]
        if f.get("available"):
            freshness_report[ind] = {
                "end_date":        f["end_date"],
                "days_since_last": f["days_since_last"],
                "rows":            f["rows"],
            }

    print("\n  신뢰도 Top 10:")
    sorted_conf = sorted(conf_results.items(), key=lambda x: x[1]["combined_confidence"], reverse=True)
    for ind, c in sorted_conf[:10]:
        flag = " [!]" if c["combined_confidence"] < LOW_CONF_THRESHOLD else ""
        print(f"    {ind:22s} SP500:{c['sp500_confidence']:5.1f}  KOSPI:{c['kospi_confidence']:5.1f}  합:{c['combined_confidence']:5.1f}{flag}")

    print(f"\n  신뢰도 70점 미만 (자동 제외): {len(low_conf)}개")
    for item in low_conf:
        print(f"    [자동제외] {item['indicator']}: {item['combined_confidence']:.1f}점")

    valid_ranking, filtered_ranking = filter_ranking(ranking)
    # 낮은 신뢰도 제외 후 최종
    low_conf_names = {i["indicator"] for i in low_conf}
    final_ranking  = [r for r in valid_ranking if r["indicator"] not in low_conf_names]

    print(f"\n  유효 랭킹: {len(valid_ranking)}개 -> 신뢰도 필터 후: {len(final_ranking)}개")
    print("\n  === 최종 랭킹 ===")
    print(f"  {'#':>3} {'지표':22} {'SP500 r':>9} {'KOSPI r':>9} {'가중치':>8}")
    for r in final_ranking:
        sp_r  = f"{r.get('sp500_signed_r',0):+.3f}{'*' if r.get('sp500_significant') else ' '}"
        ksp_r = f"{r.get('kospi_signed_r',0):+.3f}{'*' if r.get('kospi_significant') else ' '}"
        print(f"  #{r['rank']:2d} {r['indicator']:22} {sp_r:>9} {ksp_r:>9} {r.get('combined_weight',0):8.3f}")

    # CTD 연동 준비 판단 (PM 요청)
    ctd_ready = len(final_ranking) >= 5
    ctd_status = {
        "ready":   ctd_ready,
        "reason":  f"유효 지표 {len(final_ranking)}개 - {'충분' if ctd_ready else '부족'}",
        "min_required": 5,
        "action":  "MVP 연동 가능" if ctd_ready else "추가 데이터 수집 필요",
    }

    eval_results = {
        "generated_at":          datetime.now().isoformat(),
        "target_vars_excluded":  list(TARGET_VARS),
        "f13_significance":      sig_report,
        "f13_summary": {
            "sp500_significant_count":  sp_sig_cnt,
            "kospi_significant_count":  ksp_sig_cnt,
            "total_evaluated":          len(all_inds),
        },
        "f14_confidence":        conf_results,
        "f14_low_confidence":    low_conf,
        "f14_valid_ranking":     valid_ranking,
        "f14_filtered_ranking":  filtered_ranking,
        "f14_final_ranking":     final_ranking,
        "data_freshness_report": freshness_report,
        "ctd_readiness":         ctd_status,
        "low_confidence_threshold": LOW_CONF_THRESHOLD,
        "auto_exclude_policy":   AUTO_EXCLUDE_REASON,
    }

    out = PROC_DIR / "evaluation_results.json"
    out.write_text(json.dumps(eval_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n평가 결과 저장: {out}")

    print(f"\n  CTD 연동 준비: {'가능' if ctd_ready else '불가'} ({ctd_status['reason']})")

    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] in ("F13", "F14"):
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Evaluator Agent v2 완료")
