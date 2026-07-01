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

_REQUIRED_FIELDS = {
    "generated_at", "signal", "confidence_pct", "kospi_confidence_pct",
    "composite_score_sp500", "composite_score_kospi", "consensus_ratio",
    "bullish_count", "bearish_count", "total_signals",
    "market_summary", "key_indicators", "sp500_action", "kospi_action",
    "position_size_pct", "position_guidance",
    "sp500_top_stocks", "kospi_top_stocks",
    "action_plan", "monitor_points", "risk_flags",
    "data_quality", "na_verification",
}

_VALID_ACTIONS = {"BUY", "SELL", "HOLD", "WATCH", "WAIT", "STRONG_BUY", "STRONG_SELL"}


@pytest.fixture(scope="module")
def nc() -> dict:
    if not _NC_PATH.exists():
        pytest.skip(f"narrative_context.json 미생성 (실 파이프라인 실행 전) — {_NC_PATH}")
    return json.loads(_NC_PATH.read_text(encoding="utf-8"))


def test_T_NC_1_file_exists_and_parses(nc):
    assert isinstance(nc, dict), "narrative_context.json 최상위 object 아님"
    assert len(nc) >= 20, f"필드 수 부족: {len(nc)} < 20"


def test_T_NC_2_all_required_fields_present(nc):
    missing = _REQUIRED_FIELDS - set(nc.keys())
    assert not missing, f"필수 필드 누락 (Phase 11-A DC gate): {missing}"


def test_T_NC_3_numeric_bounds(nc):
    for key in ("confidence_pct", "kospi_confidence_pct"):
        v = nc.get(key)
        if v is not None:
            assert 0 <= v <= 100, f"{key}={v} 가 [0,100] 밖"
    for key in ("composite_score_sp500", "composite_score_kospi"):
        v = nc.get(key)
        if v is not None:
            assert 0 <= v <= 100, f"{key}={v} 가 [0,100] 밖"
    # bullish + bearish = total (or ≤ total for HOLD entries)
    bull = nc.get("bullish_count", 0)
    bear = nc.get("bearish_count", 0)
    total = nc.get("total_signals", 0)
    assert bull + bear <= total, f"bull({bull})+bear({bear}) > total({total})"


def test_T_NC_4_minimum_content_size(nc):
    key_ind = nc.get("key_indicators") or []
    assert len(key_ind) >= 5, f"key_indicators 부족: {len(key_ind)} < 5"
    action = nc.get("action_plan") or []
    assert len(action) >= 3, f"action_plan 부족: {len(action)} < 3"


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
    for key in ("signal", "sp500_action", "kospi_action"):
        v = nc.get(key)
        if v is None:
            continue
        assert v.upper() in _VALID_ACTIONS, (
            f"{key}={v!r} 가 허용 enum 외: {_VALID_ACTIONS}"
        )
