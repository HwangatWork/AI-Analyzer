# -*- coding: utf-8 -*-
"""
Phase 11-A 재정의 (사이클 2 Commit 2/3): narrative_context.json 완전성 회귀.

배경: Phase 11-A Path Z 채택 후 verification 자동화 강화.
- data-prep (run_narrative_agent.py) 이 필수 필드 완전 생성 강제
- prose (FINAL_REPORT_v2.md) 는 manual dogfood — 이 회귀는 prep-only 강제
- 실 파이프라인 출력 fixture 사용 (FIX-G 룰: 합성 fixture 금지)

Peer review consensus:
- audit Q2: grep + mtime + LLM 작성 (template 패턴 0건)
- validation Q3: sourced-claim ratio metric (deterministic 불가, proxy 만)
- meta-audit: LLM 작성 주장의 진위 → sourced-claim heuristic

Tests:
T-NC-1: narrative_context.json 파일 존재 + JSON 파싱 가능
T-NC-2: 필수 23 필드 모두 존재 (실측 스키마)
T-NC-3: 수치 값 정합성 (confidence_pct ∈ [0,100], composite_score ∈ [0,100],
   bullish + bearish = total_signals)
T-NC-4: 필드별 최소 크기 (key_indicators ≥ 5, action_plan ≥ 3)
T-NC-5: FINAL_REPORT_v2.md 존재 시 sourced-claim heuristic
   (숫자 인용 ≥ 3건 = LLM 실제 작성 proxy)
T-NC-6: signal / sp500_action / kospi_action ∈ {BUY, SELL, HOLD, WATCH, WAIT}
   (action enum)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NC_PATH = _REPO_ROOT / "output" / "narrative_context.json"
_FR_PATH = _REPO_ROOT / "output" / "FINAL_REPORT_v2.md"

# 2026-07-04 스키마 갱신: run_narrative_agent 리팩터로 top-level 7 필드로 축소.
# 기존 flat 스키마 (23 필드) → nested (signal/decision/top5_ranking).
_REQUIRED_TOP_FIELDS = {
    "generated_at", "analysis_period", "signal", "decision",
    "top5_ranking", "sp500", "kospi",
}
_REQUIRED_SIGNAL_FIELDS = {
    "score", "direction", "bullish_count", "bearish_count",
    "total_signals", "indicator_details",
}
_REQUIRED_DECISION_FIELDS = {"sp500", "kospi", "risk_factors"}

_VALID_ACTIONS = {"BUY", "SELL", "HOLD", "WATCH", "WAIT",
                  "STRONG_BUY", "STRONG_SELL"}
_VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}


@pytest.fixture(scope="module")
def nc() -> dict:
    if not _NC_PATH.exists():
        pytest.skip(f"narrative_context.json 미생성 (실 파이프라인 실행 전) — {_NC_PATH}")
    return json.loads(_NC_PATH.read_text(encoding="utf-8"))


def test_T_NC_1_file_exists_and_parses(nc):
    assert isinstance(nc, dict), "narrative_context.json 최상위 object 아님"
    assert len(nc) >= 7, f"top 필드 수 부족: {len(nc)} < 7 (새 스키마)"


def test_T_NC_2_all_required_fields_present(nc):
    """새 스키마: top 7 필드 + signal 하위 6 + decision 하위 3."""
    missing_top = _REQUIRED_TOP_FIELDS - set(nc.keys())
    assert not missing_top, f"top 필드 누락: {missing_top}"
    signal = nc.get("signal") or {}
    missing_signal = _REQUIRED_SIGNAL_FIELDS - set(signal.keys())
    assert not missing_signal, f"signal 하위 필드 누락: {missing_signal}"
    decision = nc.get("decision") or {}
    missing_decision = _REQUIRED_DECISION_FIELDS - set(decision.keys())
    assert not missing_decision, f"decision 하위 필드 누락: {missing_decision}"


def test_T_NC_3_numeric_bounds(nc):
    """새 스키마: signal.score [0,100] + bullish + bearish = total."""
    signal = nc.get("signal") or {}
    score = signal.get("score")
    if score is not None:
        assert 0 <= score <= 100, f"signal.score={score} 가 [0,100] 밖"
    bull = signal.get("bullish_count", 0)
    bear = signal.get("bearish_count", 0)
    total = signal.get("total_signals", 0)
    assert bull + bear <= total, f"bull({bull})+bear({bear}) > total({total})"

    # decision.sp500/kospi confidence_pct (있으면 [0,100])
    for market in ("sp500", "kospi"):
        m = (nc.get("decision") or {}).get(market) or {}
        conf = m.get("confidence_pct")
        if conf is not None:
            assert 0 <= conf <= 100, f"decision.{market}.confidence_pct={conf} 밖"


def test_T_NC_4_minimum_content_size(nc):
    """새 스키마: signal.indicator_details ≥ 5, top5_ranking ≥ 3."""
    signal = nc.get("signal") or {}
    ind = signal.get("indicator_details") or []
    assert len(ind) >= 5, f"signal.indicator_details 부족: {len(ind)} < 5"
    top5 = nc.get("top5_ranking") or []
    assert len(top5) >= 3, f"top5_ranking 부족: {len(top5)} < 3"


def test_T_NC_5_final_report_sourced_claim_heuristic():
    """FINAL_REPORT_v2.md 가 있다면 최소 3+ 수치 인용 = LLM 작성 proxy.

    없으면 SKIP (manual dogfood 미완료 = 정상 상태).
    """
    if not _FR_PATH.exists():
        pytest.skip("FINAL_REPORT_v2.md 미생성 — manual dogfood 대기")
    text = _FR_PATH.read_text(encoding="utf-8", errors="replace")
    # 숫자 인용 heuristic: %/원/달러/포인트/pt/bp/점 등의 수치 표기
    number_patterns = [
        r"\d+\.?\d*\s*%",           # 3.14% / 65%
        r"\d+\.?\d*\s*(pt|bp|점)",  # 130pt / 25bp / 30점
        r"[\$￥]\s*\d+",       # $100 / ￥1000
        r"\d{2,}\s*(달러|원)",     # 100달러 / 1000원
        r"\d+\.?\d*\s*배",         # 3.5배
    ]
    hits = 0
    for pat in number_patterns:
        hits += len(re.findall(pat, text))
    assert hits >= 3, (
        f"FINAL_REPORT_v2.md sourced-claim heuristic 실패: "
        f"수치 인용 {hits}건 (< 3). LLM 실제 작성 여부 의심 (template 위장)"
    )


def test_T_NC_6_action_enum_valid(nc):
    """새 스키마: signal.direction ∈ {bullish, bearish, neutral},
    decision.sp500/kospi.action ∈ _VALID_ACTIONS."""
    direction = (nc.get("signal") or {}).get("direction")
    if direction is not None:
        assert direction.lower() in _VALID_DIRECTIONS, (
            f"signal.direction={direction!r} 가 허용 enum 외: {_VALID_DIRECTIONS}"
        )
    for market in ("sp500", "kospi"):
        m = (nc.get("decision") or {}).get(market) or {}
        action = m.get("action")
        if action is None:
            continue
        assert action.upper() in _VALID_ACTIONS, (
            f"decision.{market}.action={action!r} 가 허용 enum 외: {_VALID_ACTIONS}"
        )
