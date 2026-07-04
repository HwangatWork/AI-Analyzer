# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — classifier: 5단계 확률 분류기.

stage_engine_v3_smoke_test.py(참조 스펙)의 분류 수학을 그대로 포팅:
가용 차원만의 대각 마할라노비스 거리 → softmax → P 벡터,
Confidence = 데이터충족률 × (1 − 정규화 엔트로피).

확장점 (스펙 대비 변경 사항):
- 피처 6개 (vol_z20 추가). MU/SIG는 피처명 키 dict — Phase B 피처 추가 시
  classify() 시그니처 무변경 확장 가능.
- vol_z20의 MU/SIG는 신규 설계값 (UNVALIDATED — 14종목 fixture에 vol_z20
  데이터가 없어 미검증. fixture 회귀는 vol_z20=None으로 원경로 재현).
- 시총 3조 KRW 분기: LARGECAP_MU (UNVALIDATED 휴리스틱).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

STAGES = (0, 1, 2, 3, 4)  # Dormant/Ignition/Momentum/Blowoff/Reset
FEATURE_ORDER = ("pos_low", "pos_high", "per_trailing", "consensus_gap",
                 "rsi14", "vol_z20")
LARGECAP_THRESHOLD_KRW = 3e12  # 3조

# ── 소형주(<3조) 프로파일 — smoke test v3.0 설계값 그대로 + vol_z20 신규 ──
# vol_z20 행은 UNVALIDATED 신규 설계값 (사용자 승인 2026-07-04):
#   S0 -0.3 / S1 +0.8 / S2 +0.5 / S3 +1.5 / S4 -0.5, σ=1.0
SMALLCAP_MU = {
    0: {"pos_low": 0.35, "pos_high": -0.35, "per_trailing": 22,
        "consensus_gap": 0.55, "rsi14": 55, "vol_z20": -0.3},
    1: {"pos_low": 1.00, "pos_high": -0.15, "per_trailing": 35,
        "consensus_gap": 0.35, "rsi14": 68, "vol_z20": 0.8},
    2: {"pos_low": 3.20, "pos_high": -0.15, "per_trailing": 45,
        "consensus_gap": 0.20, "rsi14": 65, "vol_z20": 0.5},
    3: {"pos_low": 6.50, "pos_high": -0.10, "per_trailing": 110,
        "consensus_gap": -0.05, "rsi14": 60, "vol_z20": 1.5},
    4: {"pos_low": 1.60, "pos_high": -0.52, "per_trailing": 60,
        "consensus_gap": 0.05, "rsi14": 33, "vol_z20": -0.5},
}
SMALLCAP_SIG = {
    0: {"pos_low": 0.30, "pos_high": 0.15, "per_trailing": 15,
        "consensus_gap": 0.20, "rsi14": 10, "vol_z20": 1.0},
    1: {"pos_low": 0.40, "pos_high": 0.10, "per_trailing": 15,
        "consensus_gap": 0.15, "rsi14": 8, "vol_z20": 1.0},
    2: {"pos_low": 1.60, "pos_high": 0.12, "per_trailing": 25,
        "consensus_gap": 0.15, "rsi14": 12, "vol_z20": 1.0},
    3: {"pos_low": 3.00, "pos_high": 0.10, "per_trailing": 50,
        "consensus_gap": 0.12, "rsi14": 12, "vol_z20": 1.0},
    4: {"pos_low": 0.80, "pos_high": 0.12, "per_trailing": 40,
        "consensus_gap": 0.15, "rsi14": 8, "vol_z20": 1.0},
}

# ── 대형주(≥3조) 프로파일 — UNVALIDATED 휴리스틱 (스펙 지시) ─────────────
# 대형주는 저점대비 상승배수와 PER 팽창 폭이 구조적으로 작다는 가정:
# MU의 per_trailing ×0.6, pos_low ×0.5. SIG는 스펙에 지시가 없어 미변경.
# 라벨된 대형주 검증 데이터 미확보 — 백테스트/실측으로 검증 전까지 UNVALIDATED.
_PER_SCALE = 0.6
_POSLOW_SCALE = 0.5
LARGECAP_MU = {
    k: {f: (v * _POSLOW_SCALE if f == "pos_low"
            else v * _PER_SCALE if f == "per_trailing" else v)
        for f, v in prof.items()}
    for k, prof in SMALLCAP_MU.items()
}
LARGECAP_SIG = SMALLCAP_SIG


@dataclass
class ClassifyResult:
    P: dict[int, float]
    confidence: float
    stage: int
    n_features_available: int
    profile: str  # "smallcap" | "largecap"


def classify(features: dict[str, float | None],
             market_cap_krw: float | None = None) -> ClassifyResult:
    """5단계 확률 분류.

    features: FEATURE_ORDER 키의 값 dict. 누락 키/None = 결측 (차원 스킵).
              FEATURE_ORDER 외 키는 무시 (Phase B 전방 호환).
    market_cap_krw: None 또는 <3조 → SMALLCAP 프로파일 (smoke test 원경로),
                    ≥3조 → LARGECAP 프로파일.
    """
    if market_cap_krw is not None and market_cap_krw >= LARGECAP_THRESHOLD_KRW:
        mu_all, sig_all, profile = LARGECAP_MU, LARGECAP_SIG, "largecap"
    else:
        mu_all, sig_all, profile = SMALLCAP_MU, SMALLCAP_SIG, "smallcap"

    x = {f: features.get(f) for f in FEATURE_ORDER}
    n_avail = sum(v is not None for v in x.values())

    logps: dict[int, float] = {}
    for k in STAGES:
        d2 = 0.0
        for f, v in x.items():
            if v is None:
                continue
            d2 += ((v - mu_all[k][f]) / sig_all[k][f]) ** 2
        logps[k] = -d2 / 2
    m = max(logps.values())
    ps = {k: math.exp(v - m) for k, v in logps.items()}
    z = sum(ps.values())
    P = {k: ps[k] / z for k in ps}

    coverage = n_avail / len(FEATURE_ORDER)
    ent = -sum(p * math.log(p + 1e-12) for p in P.values()) / math.log(len(STAGES))
    conf = coverage * (1 - ent)

    stage = max(P, key=P.get)
    return ClassifyResult(P=P, confidence=conf, stage=stage,
                          n_features_available=n_avail, profile=profile)
