# -*- coding: utf-8 -*-
"""
Phase 13-D-2 (사이클 1 Commit 3/3): DC-6 dogfood 부분 자동화 (e2e mock).

배경: DC-6 의 동적 검증 = `/tf-review <proposal>` manual dogfood (사용자 1회 invoke).
slash command 는 인터랙티브 + Claude Code 내부 routing → pytest 환경 불가.
그러나 **underlying mechanics 의 e2e 정합성** 은 mock 으로 자동화 가능:
  synthetic 13 response → tf_aggregate _build_aggregate() → aggregate.md
  → 4 필수 섹션 + conditional 섹션 (Meta-Patterns / Minority Dissent)
이 회귀가 PASS 하면 manual dogfood 실패 시 원인이 slash command 자체로 좁혀짐.

Peer review consensus: validation (DC-1~5 체크리스트) + audit (manual run 결과 일치).
완전 동적 검증은 여전히 사용자 1회 `/tf-review` 실 실행 — 이건 회귀 0건.

Tests:
T-TFD-E2E-1: _synthetic_responses(13) → 13 valid + 각 schema 통과
T-TFD-E2E-2: _build_aggregate 결과에 필수 4 섹션 (Consensus/Urgency/NewItems/Actions)
T-TFD-E2E-3: Meta-Patterns conditional 분기 (≥5 agent 동일 file 참조)
T-TFD-E2E-4: Minority Dissent conditional 분기 (direct relevance + disagree + 50+ chars)
T-TFD-E2E-5: aggregate.md 가 stop_hook get_tf_digest_section regex 와 정합
"""
from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "tf_aggregate.py"
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "peer_review_response.schema.json"


@pytest.fixture(scope="module")
def aggr_mod():
    spec = importlib.util.spec_from_file_location("tf_aggregate", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_T_TFD_E2E_1_synthetic_13_validate(aggr_mod, schema):
    """_synthetic_responses(13) → 13 valid + 각 schema 통과."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        pytest.skip("jsonschema 미설치")
    responses = aggr_mod._synthetic_responses(13)
    assert len(responses) == 13
    validator = Draft202012Validator(schema)
    for i, r in enumerate(responses):
        errs = list(validator.iter_errors(r))
        assert not errs, f"response[{i}] schema 위반: {errs[:2]}"


def test_T_TFD_E2E_2_aggregate_has_required_4_sections(aggr_mod):
    """4 필수 섹션이 모두 aggregate.md 에 등장."""
    responses = aggr_mod._synthetic_responses(13)
    text = aggr_mod._build_aggregate(responses)
    assert "## 1. Consensus Matrix" in text
    assert "## 2. Urgency Revote" in text
    assert "## 3. New Items Surfaced" in text
    assert "## 4. Recommended Action Order" in text
    # 헤더 라인 검증
    assert re.search(r"^#\s*TF Peer Review Aggregate\s*—\s*13\s*response", text, re.M)


def test_T_TFD_E2E_3_meta_patterns_conditional(aggr_mod):
    """Meta-Patterns: ≥5 agent 가 동일 file 참조 시에만 표기."""
    # case A: 모두 다른 file → meta 부재
    diverse = []
    for i in range(13):
        diverse.append({
            "agent": f"agent-{i}", "domain_relevance": "indirect", "agreement": "support",
            "urgency_vote": 1, "reason": "ok",
            "addition": {"file": f"f-{i}.py", "function": "g", "change": "x"},
        })
    text_a = aggr_mod._build_aggregate(diverse)
    assert "## 5. Meta-Patterns" not in text_a

    # case B: 5+ agent 가 same file → meta 출현
    same = [dict(diverse[i], addition={"file": "hot.py", "function": "g", "change": "x"})
            for i in range(6)]
    same.extend(diverse[6:])
    text_b = aggr_mod._build_aggregate(same)
    assert "## 5. Meta-Patterns" in text_b
    assert "hot.py" in text_b


def test_T_TFD_E2E_4_minority_dissent_conditional(aggr_mod):
    """Minority Dissent: direct relevance + disagree + reason ≥50 chars."""
    # case A: 모두 same vote → dissent 부재
    consensus = [{
        "agent": f"a-{i}", "domain_relevance": "direct", "agreement": "support",
        "urgency_vote": 3, "reason": "x" * 60,
    } for i in range(13)]
    text_a = aggr_mod._build_aggregate(consensus)
    assert "## 6. Minority Dissent" not in text_a

    # case B: 1 direct agent 가 diff vote + 충분한 reason → dissent 출현
    dissent = [dict(consensus[i]) for i in range(13)]
    dissent[0]["urgency_vote"] = 7
    dissent[0]["reason"] = "방향 정합 X — 시그널 점수와 액션 모순. 추가 분석 필요한 케이스 다수 누락." * 2
    text_b = aggr_mod._build_aggregate(dissent)
    assert "## 6. Minority Dissent" in text_b
    assert "a-0" in text_b


def test_T_TFD_E2E_5_aggregate_format_matches_digest_regex(aggr_mod):
    """stop_hook get_tf_digest_section regex 가 _build_aggregate 출력과 정합."""
    responses = aggr_mod._synthetic_responses(13)
    text = aggr_mod._build_aggregate(responses)
    # stop_hook.py 의 regex (DC-10):
    head_re = re.search(r"#\s*TF Peer Review Aggregate\s*—\s*(\d+)\s*response", text)
    assert head_re, "헤더 regex 미일치 → DC-10 digest 가 작동 안 함"
    assert head_re.group(1) == "13"
    cons_re = re.search(
        r"\*\*Consensus most urgent\*\*:\s*item\s*(\S+)\s*\((\d+)/(\d+)\s*votes\)",
        text,
    )
    assert cons_re, "Consensus 라인 regex 미일치"
