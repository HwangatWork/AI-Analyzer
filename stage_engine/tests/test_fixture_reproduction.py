# -*- coding: utf-8 -*-
"""14종목 라벨 fixture 회귀 — stage_engine_v3_smoke_test.py 재현 (합격선 ≥12/14).

호출 규약 (사용자 승인 2026-07-04):
- market_cap=None → SMALLCAP 프로파일 = smoke test 원경로 정확 재현
- vol_z20=None → 결측 차원 스킵 → argmax는 smoke test와 수학적으로 동일
- conf 절대값 assert 금지 (coverage 분모 5→6으로 스케일만 변동) —
  argmax 재현율 + H5 방향성(오답 conf < 정답 conf)만 검증
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from stage_engine.classifier import classify  # noqa: E402

# stage_engine_v3_smoke_test.py 실측 확정치 (verbatim)
STOCKS = {
    "지엔씨에너지":  [0.515,  -0.405,  None,   None,   63.9],
    "오이솔루션":    [1.518,  -0.588,  None,   None,   26.1],
    "대한전선":      [1.232,  -0.567,  None,   None,   34.1],
    "LS":            [1.320,  -0.381,  None,   None,   38.4],
    "심텍":          [4.302,  -0.214,  None,   None,   47.9],
    "삼화콘덴서":    [3.300,  -0.394,  None,   None,   42.4],
    "가온전선":      [8.494,  -0.214,  148.2,  None,   None],
    "SK하이닉스":    [8.878,  -0.190,  7.0,    0.62,   None],
    "삼성전기":      [None,   None,    None,  -0.02,   None],
    "대덕전자":      [None,   -0.051,  22.0,  -0.149,  None],
    "Nvidia":        [None,   -0.30,   None,   0.50,   None],
    "GE_Vernova":    [None,   -0.037,  63.0,   0.11,   None],
    "ASML":          [None,   -0.078,  64.7,  -0.052,  None],
    "TokyoElectron": [None,   None,    None,  -0.167,  None],
}
LABELS = {"지엔씨에너지": 0, "오이솔루션": 4, "대한전선": 4, "LS": 4, "심텍": 2,
          "삼화콘덴서": 4, "가온전선": 3, "SK하이닉스": 2, "삼성전기": 3,
          "대덕전자": 3, "Nvidia": 2, "GE_Vernova": 3, "ASML": 3,
          "TokyoElectron": 3}
PASS_LINE = 12  # 합격선: ≥12/14 (smoke test 기준 81%)


def _features(x):
    return {"pos_low": x[0], "pos_high": x[1], "per_trailing": x[2],
            "consensus_gap": x[3], "rsi14": x[4], "vol_z20": None}


def _run_all():
    results = []
    for name, x in STOCKS.items():
        r = classify(_features(x), market_cap_krw=None)
        results.append((name, r.stage, LABELS[name], r.confidence))
    return results


def test_reproduction_at_least_12_of_14():
    results = _run_all()
    hits = sum(pred == label for _, pred, label, _ in results)
    misses = [(n, p, l) for n, p, l, _ in results if p != l]
    assert hits >= PASS_LINE, f"재현율 {hits}/14 < {PASS_LINE}/14 — 오답: {misses}"


def test_h5_direction_bad_conf_below_ok_conf():
    results = _run_all()
    ok = [c for _, p, l, c in results if p == l]
    bad = [c for _, p, l, c in results if p != l]
    if not bad:
        return  # 오답 표본 없음 — 측정 불가 (smoke test 동일 처리)
    assert statistics.mean(bad) < statistics.mean(ok), (
        f"H5 방향성 위반: bad_conf {statistics.mean(bad):.3f} >= "
        f"ok_conf {statistics.mean(ok):.3f}")


def test_known_baseline_misses_are_nvidia_and_gevernova():
    # baseline 실측(2026-07-04): 오답 = Nvidia(S0/S2), GE_Vernova(S2/S3).
    # 오답 집합이 달라지면 분류 수학이 변경된 것 — 즉시 탐지.
    results = _run_all()
    misses = sorted(n for n, p, l, _ in results if p != l)
    assert misses == ["GE_Vernova", "Nvidia"], f"오답 집합 변동: {misses}"
