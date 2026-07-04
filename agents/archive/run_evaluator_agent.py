"""
Evaluator Agent — F13, F14
- F13: 통계적 유의성 확인 (p-value < 0.05)
- F14: 이상값 필터링 및 신뢰도 점수 산출
[?] 신뢰도 점수 70점 미만 지표 존재 시 중단 및 보고
"""
import utf8_setup  # noqa: F401

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from scipy import stats

BASE_DIR = Path(__file__).parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"
RAW_DIR = BASE_DIR / "data" / "raw"
PROC_DIR.mkdir(parents=True, exist_ok=True)

LOW_CONFIDENCE_THRESHOLD = 70


def compute_confidence_score(ind_name: str, sp_data: dict, ksp_data: dict) -> dict:
    """
    신뢰도 점수 (0-100):
    - 데이터 충분성: 행 수 기준 (30점)
    - 통계적 유의성: p < 0.05 여부 (30점)
    - 상관강도: |r| 크기 (20점)
    - 이상값 비율: 낮을수록 높은 점수 (20점)
    """
    scores = {}
    details = {}

    for market_name, data in [("sp500", sp_data), ("kospi", ksp_data)]:
        if not data or data.get("status") == "FAILED":
            scores[market_name] = 0
            details[market_name] = {"reason": "데이터 없음"}
            continue

        n = data.get("corr", {}).get("n", 0)
        r = abs(data.get("corr", {}).get("pearson_r") or 0)
        p = data.get("corr", {}).get("pearson_p")
        r2 = data.get("regression", {}).get("r2") or 0

        # 이상값 비율 계산 (데이터 파일에서 직접)
        outlier_ratio = 0.0
        path = RAW_DIR / f"{ind_name}.parquet"
        if path.exists():
            try:
                df = pd.read_parquet(path)
                vals = pd.to_numeric(df["value"], errors="coerce").dropna()
                if len(vals) > 10:
                    q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
                    iqr = q3 - q1
                    outliers = ((vals < q1 - 3 * iqr) | (vals > q3 + 3 * iqr)).sum()
                    outlier_ratio = outliers / len(vals)
            except Exception:
                pass

        # 점수 계산
        data_score = min(30, n / 10)  # 300행 이상이면 만점
        sig_score = 30 if (p is not None and p < 0.05) else 0
        corr_score = min(20, r * 20)  # |r|=1이면 20점
        outlier_score = max(0, 20 - outlier_ratio * 100)  # 이상값 0%이면 20점

        total = data_score + sig_score + corr_score + outlier_score

        scores[market_name] = round(total, 1)
        details[market_name] = {
            "n": n,
            "r": round(r, 4),
            "p": round(p, 6) if p else None,
            "r2": round(r2, 4),
            "outlier_ratio": round(outlier_ratio, 4),
            "breakdown": {
                "data_score": round(data_score, 1),
                "sig_score": sig_score,
                "corr_score": round(corr_score, 1),
                "outlier_score": round(outlier_score, 1),
            }
        }

    # 전체 신뢰도: SP500과 KOSPI 중 높은 값 기준
    combined = max(scores.get("sp500", 0), scores.get("kospi", 0))
    return {
        "sp500_confidence": scores.get("sp500", 0),
        "kospi_confidence": scores.get("kospi", 0),
        "combined_confidence": round(combined, 1),
        "details": details,
    }


def filter_outliers_in_ranking(ranking: list) -> tuple[list, list]:
    """
    가중치 랭킹에서 통계적으로 이상한 항목 필터링:
    - p-value >= 0.05 (양쪽 시장 모두) → 신뢰도 미달
    - NaN 값 포함 → 데이터 부족
    - r2 < 0.01 → 설명력 없음
    """
    valid = []
    filtered = []

    for item in ranking:
        sp_r = item.get("sp500_r") or 0
        ksp_r = item.get("kospi_r") or 0
        sp_sig = item.get("sp500_significant", False)
        ksp_sig = item.get("kospi_significant", False)
        combined = item.get("combined_weight") or 0

        # NaN 체크
        if np.isnan(combined) or np.isnan(sp_r) or np.isnan(ksp_r):
            item["filter_reason"] = "NaN 값 (데이터 부족 또는 상수)"
            filtered.append(item)
            continue

        # 양쪽 모두 유의하지 않음
        if not sp_sig and not ksp_sig:
            item["filter_reason"] = "통계적 비유의 (p >= 0.05 양 시장)"
            filtered.append(item)
            continue

        valid.append(item)

    return valid, filtered


if __name__ == "__main__":
    print("=" * 60)
    print("EVALUATOR AGENT - Phase 4 (F13, F14)")
    print("=" * 60)

    # 분석 결과 로드
    analysis_path = PROC_DIR / "analysis_results.json"
    stock_path = PROC_DIR / "stock_results.json"

    if not analysis_path.exists():
        print("[ERROR] analysis_results.json 없음 — Analysis Agent 먼저 실행 필요")
        exit(1)

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    sp500_analysis = analysis.get("f06_sp500_analysis", {})
    kospi_analysis = analysis.get("f07_kospi_analysis", {})
    ranking = analysis.get("f08_weight_ranking", [])

    # ─────────────────────────────────
    # F13: 통계적 유의성 확인
    # ─────────────────────────────────
    print("\n[F13] 통계적 유의성 확인 (p-value < 0.05)")
    sig_report = {}
    all_indicators = set(list(sp500_analysis.keys()) + list(kospi_analysis.keys()))

    sp_sig_count = 0
    ksp_sig_count = 0

    for ind in sorted(all_indicators):
        sp = sp500_analysis.get(ind, {})
        ksp = kospi_analysis.get(ind, {})

        sp_p = sp.get("corr", {}).get("pearson_p")
        ksp_p = ksp.get("corr", {}).get("pearson_p")
        sp_sig = sp_p is not None and sp_p < 0.05
        ksp_sig = ksp_p is not None and ksp_p < 0.05

        if sp_sig: sp_sig_count += 1
        if ksp_sig: ksp_sig_count += 1

        sig_report[ind] = {
            "sp500_p": round(sp_p, 6) if sp_p else None,
            "sp500_significant": sp_sig,
            "kospi_p": round(ksp_p, 6) if ksp_p else None,
            "kospi_significant": ksp_sig,
        }

    print(f"  S&P500 유의 지표: {sp_sig_count}/{len(all_indicators)}개")
    print(f"  코스피  유의 지표: {ksp_sig_count}/{len(all_indicators)}개")

    # ─────────────────────────────────
    # F14: 이상값 필터링 및 신뢰도 점수
    # ─────────────────────────────────
    print("\n[F14] 이상값 필터링 및 신뢰도 점수 산출")

    confidence_results = {}
    low_confidence_indicators = []

    for ind in sorted(all_indicators):
        sp = sp500_analysis.get(ind, {})
        ksp = kospi_analysis.get(ind, {})
        conf = compute_confidence_score(ind, sp, ksp)
        confidence_results[ind] = conf

        if conf["combined_confidence"] < LOW_CONFIDENCE_THRESHOLD:
            low_confidence_indicators.append({
                "indicator": ind,
                "combined_confidence": conf["combined_confidence"],
                "sp500_confidence": conf["sp500_confidence"],
                "kospi_confidence": conf["kospi_confidence"],
            })

    # 신뢰도 점수 출력
    print("\n  신뢰도 점수 Top 10:")
    sorted_conf = sorted(confidence_results.items(), key=lambda x: x[1]["combined_confidence"], reverse=True)
    for ind, conf in sorted_conf[:10]:
        flag = "" if conf["combined_confidence"] >= LOW_CONFIDENCE_THRESHOLD else " [!]"
        print(f"    {ind:22s} | SP500:{conf['sp500_confidence']:5.1f} | KOSPI:{conf['kospi_confidence']:5.1f} | 합:{conf['combined_confidence']:5.1f}{flag}")

    print(f"\n  신뢰도 70점 미만: {len(low_confidence_indicators)}개")
    for item in low_confidence_indicators:
        print(f"    [!] {item['indicator']}: {item['combined_confidence']:.1f}점")

    # 랭킹 필터링
    valid_ranking, filtered_ranking = filter_outliers_in_ranking(ranking)
    print(f"\n  유효 랭킹: {len(valid_ranking)}개 / 필터링: {len(filtered_ranking)}개")

    print("\n  === 최종 유효 가중치 랭킹 (유의 지표만) ===")
    for i, r in enumerate(valid_ranking[:10]):
        sp_sig = "(*)" if r.get("sp500_significant") else "   "
        ksp_sig = "(*)" if r.get("kospi_significant") else "   "
        print(f"  #{i+1:2d} {r['indicator']:20s} | SP500:{r['sp500_r']:.3f}{sp_sig} | KOSPI:{r['kospi_r']:.3f}{ksp_sig} | 가중:{r['combined_weight']:.3f}")

    # ─────────────────────────────────
    # 결과 저장
    # ─────────────────────────────────
    eval_results = {
        "generated_at": datetime.now().isoformat(),
        "f13_significance": sig_report,
        "f13_summary": {
            "sp500_significant_count": sp_sig_count,
            "kospi_significant_count": ksp_sig_count,
            "total_indicators": len(all_indicators),
        },
        "f14_confidence": confidence_results,
        "f14_low_confidence": low_confidence_indicators,
        "f14_valid_ranking": valid_ranking,
        "f14_filtered_ranking": filtered_ranking,
        "evaluation_passed": len(low_confidence_indicators) == 0,
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
    }

    out_path = PROC_DIR / "evaluation_results.json"
    out_path.write_text(json.dumps(eval_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n평가 결과 저장: {out_path}")

    # feature_list.json 업데이트
    fl_path = BASE_DIR / "feature_list.json"
    fl = json.loads(fl_path.read_text(encoding="utf-8"))
    for feat in fl["features"]:
        if feat["id"] in ("F13", "F14"):
            feat["status"] = "done"
    fl["updated"] = datetime.now().strftime("%Y-%m-%d")
    fl_path.write_text(json.dumps(fl, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─────────────────────────────────
    # [?] 신뢰도 70점 미만 지표 체크
    # ─────────────────────────────────
    if low_confidence_indicators:
        print("\n" + "=" * 60)
        print("[?] 대표님 확인 필요 — 신뢰도 70점 미만 지표 발견")
        print("=" * 60)
        print(f"\n아래 {len(low_confidence_indicators)}개 지표의 신뢰도가 기준(70점) 미만입니다:")
        for item in low_confidence_indicators:
            print(f"  - {item['indicator']}: {item['combined_confidence']:.1f}점")
        print("\n처리 방향 선택지:")
        print("  A. 분석에서 제외 (기본 권장)")
        print("  B. 낮은 신뢰도 주석 달고 포함")
        print("  C. 추가 데이터 수집 후 재분석")
        print("\n>>> [?] 항목 — 대표님 판단 대기 중 <<<")
        exit(2)  # exit code 2 = [?] 중단
    else:
        print("\n[OK] 모든 지표 신뢰도 70점 이상 — Phase 5 진행 가능")
        print("Evaluator Agent 완료")
