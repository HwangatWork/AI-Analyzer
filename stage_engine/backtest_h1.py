# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — backtest_h1: H1 검증 게이트 (사전등록 가설).

H1 (사전등록·불변): 코호트(argmax P∈{0,1} AND conf≥0.4)의 fwd 90일
초과수익 중앙값 − 컨트롤(동일 KRX 섹터, 시총 ±50%, 코호트 제외) 중앙값
≥ +8pp AND bootstrap p < 0.05.

FAIL 시 MU/SIG/conf 임계/드리프트 윈도우 튜닝 금지 — 수치 전체 보고만.

벤치마크: KRX 업종지수 시계열은 FDR에서 조회 불가 확정
(SnapDataReader NotImplementedError, 2026-07-04 실측) → 스펙 fallback 조항에
따라 종목 소속 시장 종합지수(KS11/KQ11) 대비 초과수익 사용, fallback 100%
카운트 기록. 지표가 cohort−control '차이'라 벤치마크 항은 대부분 상쇄됨.

Bootstrap: 스냅샷-월 블록 리샘플 (사용자 승인 2026-07-04) — 90일 전방 윈도우
중첩의 시계열 자기상관으로 naive 리샘플은 p 과소평가 → 월 단위 블록으로 보수화.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from stage_engine import data_loader as dl  # noqa: E402
from stage_engine.classifier import classify  # noqa: E402

CONF_THRESHOLD = 0.40          # 사전등록 — 튜닝 금지
COHORT_STAGES = {0, 1}
MCAP_BAND = (0.5, 1.5)         # 컨트롤 시총 ±50%
FWD_DAYS = 90
N_BOOTSTRAP = 10_000
PASS_MEDIAN_DIFF_PP = 8.0      # 사전등록 — 재해석 금지
PASS_P = 0.05
THIN_COHORT = 5
OUT_PATH = Path(__file__).parents[1] / "output" / "stage_engine_h1_results.json"
_BENCH = {"KOSPI": "KS11", "KOSDAQ": "KQ11", "KOSDAQ GLOBAL": "KQ11"}
RNG_SEED = 20260704            # 재현성


def _bench_fwd(market: str, asof: pd.Timestamp) -> float | None:
    return dl.forward_return(_BENCH.get(market, "KS11"), asof, FWD_DAYS)


def _classify_snapshot(snap: pd.DataFrame) -> pd.DataFrame:
    stages, confs = [], []
    for _, r in snap.iterrows():
        res = classify(
            {"pos_low": r["pos_low"], "pos_high": r["pos_high"],
             "per_trailing": r["per_trailing"],
             "consensus_gap": r["consensus_gap"],
             "rsi14": r["rsi14"], "vol_z20": r["vol_z20"]},
            market_cap_krw=r["market_cap_krw"])
        stages.append(res.stage)
        confs.append(res.confidence)
    out = snap.copy()
    out["stage"] = stages
    out["conf"] = confs
    return out


def _build_month(snap: pd.DataFrame, asof: pd.Timestamp) -> dict:
    """단일 스냅샷의 cohort/control 초과수익 관측치."""
    df = _classify_snapshot(snap)
    cohort = df[df["stage"].isin(COHORT_STAGES) & (df["conf"] >= CONF_THRESHOLD)]
    cohort_set = set(cohort["ticker"])

    controls = set()
    for _, c in cohort.iterrows():
        mc = c["market_cap_krw"]
        if mc is None or pd.isna(mc) or pd.isna(c["sector"]):
            continue
        pool = df[(df["sector"] == c["sector"])
                  & df["market_cap_krw"].notna()
                  & (df["market_cap_krw"] >= mc * MCAP_BAND[0])
                  & (df["market_cap_krw"] <= mc * MCAP_BAND[1])
                  & ~df["ticker"].isin(cohort_set)]
        controls.update(pool["ticker"])

    bench_cache: dict[str, float | None] = {}

    def _excess(rows: pd.DataFrame) -> list[float]:
        out = []
        for _, r in rows.iterrows():
            fr = dl.forward_return(r["ticker"], asof, FWD_DAYS)
            if fr is None:
                continue
            mkt = r["market"]
            if mkt not in bench_cache:
                bench_cache[mkt] = _bench_fwd(mkt, asof)
            if bench_cache[mkt] is None:
                continue
            out.append(fr - bench_cache[mkt])
        return out

    return {
        "asof": str(asof.date()),
        "cohort_excess": _excess(cohort),
        "control_excess": _excess(df[df["ticker"].isin(controls)]),
        "cohort_size": len(cohort),
        "control_size": len(controls),
        "cohort_tickers": sorted(cohort["ticker"].tolist()),
    }


def _median_diff(months: list[dict]) -> float | None:
    co = [x for m in months for x in m["cohort_excess"]]
    ct = [x for m in months for x in m["control_excess"]]
    if not co or not ct:
        return None
    return float(np.median(co) - np.median(ct))


def _block_bootstrap_p(months: list[dict], n_iter: int = N_BOOTSTRAP,
                       seed: int = RNG_SEED) -> tuple[float | None, float | None]:
    """스냅샷-월 블록 bootstrap. 반환: (p_one_sided, observed_diff).

    p = 리샘플 통계량 diff ≤ 0 비율 (단측 — H1: cohort > control).
    """
    obs = _median_diff(months)
    if obs is None:
        return None, None
    rng = np.random.default_rng(seed)
    usable = [m for m in months if m["cohort_excess"] or m["control_excess"]]
    n = len(usable)
    diffs = []
    for _ in range(n_iter):
        pick = rng.integers(0, n, size=n)
        co, ct = [], []
        for i in pick:
            co.extend(usable[i]["cohort_excess"])
            ct.extend(usable[i]["control_excess"])
        if co and ct:
            diffs.append(np.median(co) - np.median(ct))
    if not diffs:
        return None, obs
    p = float(np.mean(np.asarray(diffs) <= 0.0))
    return p, obs


def run_backtest(start: str = "2023-01", end: str = "2025-12") -> dict:
    t0 = time.time()
    dates = dl.month_end_snapshots(start, end)
    universe = dl.load_universe()
    snaps = dl.build_all_snapshots(dates, universe)
    snaps["asof"] = pd.to_datetime(snaps["asof"])

    months = []
    for d in dates:
        sub = snaps[snaps["asof"] == d]
        if sub.empty:
            continue
        m = _build_month(sub, d)
        months.append(m)
        print(f"[backtest] {m['asof']} cohort={m['cohort_size']} "
              f"control={m['control_size']} "
              f"obs=({len(m['cohort_excess'])},{len(m['control_excess'])})",
              flush=True)

    p_all, diff_all = _block_bootstrap_p(months)
    per_year = {}
    for yr in ("2023", "2024", "2025"):
        sel = [m for m in months if m["asof"].startswith(yr)]
        p_y, diff_y = _block_bootstrap_p(sel)
        per_year[yr] = {
            "median_diff_pp": None if diff_y is None else round(diff_y * 100, 3),
            "bootstrap_p": p_y,
            "n_cohort_obs": sum(len(m["cohort_excess"]) for m in sel),
            "n_control_obs": sum(len(m["control_excess"]) for m in sel),
        }

    thin = [m["asof"] for m in months if m["cohort_size"] < THIN_COHORT]
    n_co = sum(len(m["cohort_excess"]) for m in months)
    n_ct = sum(len(m["control_excess"]) for m in months)
    co_all = [x for m in months for x in m["cohort_excess"]]
    ct_all = [x for m in months for x in m["control_excess"]]

    h1_pass = (diff_all is not None and p_all is not None
               and diff_all * 100 >= PASS_MEDIAN_DIFF_PP and p_all < PASS_P)

    meta = {}
    if dl.META_PATH.exists():
        meta = json.loads(dl.META_PATH.read_text(encoding="utf-8"))

    results = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "pass_line": {"median_diff_pp_min": PASS_MEDIAN_DIFF_PP,
                      "p_max": PASS_P, "pre_registered": True},
        "h1_verdict": "PASS" if h1_pass else "FAIL",
        "median_diff_pp": None if diff_all is None else round(diff_all * 100, 3),
        "bootstrap_p": p_all,
        "bootstrap_method": "block-by-snapshot-month, one-sided, "
                            f"n={N_BOOTSTRAP}, seed={RNG_SEED}",
        "cohort_median_excess_pp": round(float(np.median(co_all)) * 100, 3) if co_all else None,
        "control_median_excess_pp": round(float(np.median(ct_all)) * 100, 3) if ct_all else None,
        "n_cohort_obs": n_co,
        "n_control_obs": n_ct,
        "n_snapshots": len(months),
        "per_year": per_year,
        "thin_cohort_months": thin,
        "conf_threshold": CONF_THRESHOLD,
        "sector_index_fallback": {
            "reason": "FDR SnapDataReader KRX/INDEX/OHLCV NotImplementedError "
                      "(2026-07-04 실측) — 시장 종합지수(KS11/KQ11) 대체",
            "fallback_count": n_co + n_ct,
            "fallback_ratio": 1.0,
        },
        "download_meta": {k: v for k, v in meta.items() if k != "empty_tickers"},
        "n_empty_fdr_tickers": meta.get("n_empty"),
        "backtest_wall_clock_sec": round(time.time() - t0, 1),
        "months": months,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\nH1 {results['h1_verdict']}: median_diff={results['median_diff_pp']}pp "
          f"(합격선 +{PASS_MEDIAN_DIFF_PP}pp), p={p_all} (<{PASS_P}), "
          f"cohort_obs={n_co}, control_obs={n_ct}, thin_months={len(thin)}")
    ok = OUT_PATH.exists() and len(months) > 0
    print(f"DONE_CRITERIA: {'PASS' if ok else 'FAIL — 출력 파일/스냅샷 부재'}")
    return results


if __name__ == "__main__":
    r = run_backtest()
    sys.exit(0 if r["n_snapshots"] > 0 else 1)
