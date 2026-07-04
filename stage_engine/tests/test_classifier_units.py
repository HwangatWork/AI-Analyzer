# -*- coding: utf-8 -*-
"""classifier 단위 테스트 — None-안전성, 대형주 디스패치, conf 범위, 전방 호환."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from stage_engine.classifier import (  # noqa: E402
    FEATURE_ORDER, LARGECAP_MU, LARGECAP_THRESHOLD_KRW, SMALLCAP_MU, classify,
)


def test_all_none_gives_uniform_p_and_zero_conf():
    r = classify({f: None for f in FEATURE_ORDER})
    for p in r.P.values():
        assert abs(p - 0.2) < 1e-9
    assert r.confidence == 0.0
    assert r.n_features_available == 0


def test_empty_dict_equals_all_none():
    a = classify({})
    b = classify({f: None for f in FEATURE_ORDER})
    assert a.P == b.P and a.confidence == b.confidence


def test_single_feature_works_and_conf_in_range():
    r = classify({"pos_low": 8.5})
    assert r.stage == 3  # smoke test: 가온전선류 고배수 → Blowoff
    assert 0.0 <= r.confidence <= 1.0
    assert r.n_features_available == 1


def test_unknown_extra_keys_ignored():
    base = classify({"pos_low": 3.2, "rsi14": 65.0})
    extra = classify({"pos_low": 3.2, "rsi14": 65.0,
                      "narrative_heat": 9.9, "foreign_saturation": 0.5})
    assert base.P == extra.P
    assert base.confidence == extra.confidence


def test_largecap_dispatch_boundary():
    feats = {"pos_low": 3.0, "rsi14": 60.0}
    below = classify(feats, market_cap_krw=LARGECAP_THRESHOLD_KRW - 1)
    at = classify(feats, market_cap_krw=LARGECAP_THRESHOLD_KRW)
    none_ = classify(feats, market_cap_krw=None)
    assert below.profile == "smallcap" and below.P == none_.P
    assert at.profile == "largecap"
    assert at.P != below.P  # pos_low MU ×0.5 → 확률 분포 달라야 함


def test_largecap_mu_scaling_values():
    for k in SMALLCAP_MU:
        assert math.isclose(LARGECAP_MU[k]["pos_low"],
                            SMALLCAP_MU[k]["pos_low"] * 0.5)
        assert math.isclose(LARGECAP_MU[k]["per_trailing"],
                            SMALLCAP_MU[k]["per_trailing"] * 0.6)
        for f in ("pos_high", "consensus_gap", "rsi14", "vol_z20"):
            assert LARGECAP_MU[k][f] == SMALLCAP_MU[k][f]


def test_p_sums_to_one():
    r = classify({"pos_low": 1.2, "pos_high": -0.5, "rsi14": 34.0})
    assert abs(sum(r.P.values()) - 1.0) < 1e-9


def test_vol_z20_participates_when_present():
    without = classify({"pos_low": 3.2, "rsi14": 65.0})
    with_vz = classify({"pos_low": 3.2, "rsi14": 65.0, "vol_z20": 1.5})
    assert with_vz.n_features_available == 3
    assert without.P != with_vz.P
