# -*- coding: utf-8 -*-
"""
Phase 13-B-1 회귀 테스트: TF schema 파일 유효성 (DC-1).

Tests:
T-TF-S-1: response schema 자체가 valid JSON Schema (Draft 2020-12)
T-TF-S-2: response schema가 minimal valid fixture를 통과시킴
T-TF-S-3: response schema가 addition 포함 valid fixture를 통과시킴
T-TF-S-4: response schema가 필수 필드 누락 시 reject
T-TF-S-5: response schema가 reason 길이 < 20 시 reject
T-TF-S-6: response schema가 enum 위반 시 reject
T-TF-S-7: concerns schema 자체가 valid JSON Schema
T-TF-S-8: concerns schema가 valid fixture 통과
T-TF-S-9: concerns schema가 empty failure_modes reject
T-TF-S-10: concerns schema가 verification_target field 누락 reject
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMAS = _REPO_ROOT / "schemas"


def _load(name: str) -> dict:
    return json.loads((_SCHEMAS / name).read_text(encoding="utf-8"))


# ── Response schema ────────────────────────────────────────────────

def test_T_TF_S_1_response_schema_self_valid():
    schema = _load("peer_review_response.schema.json")
    Draft202012Validator.check_schema(schema)


def test_T_TF_S_2_response_accepts_minimal():
    schema = _load("peer_review_response.schema.json")
    fixture = {
        "agent": "news-agent",
        "domain_relevance": "direct",
        "agreement": "agree",
        "urgency_vote": 1,
        "reason": "RSS empty case에서도 mtime이 갱신되어 false positive 발생 가능",
    }
    Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_3_response_accepts_with_addition():
    schema = _load("peer_review_response.schema.json")
    fixture = {
        "agent": "stock-agent",
        "domain_relevance": "indirect",
        "agreement": "partial",
        "urgency_vote": 3,
        "reason": "f09 기여도는 evaluator 독립 계산이라 게이트 전파 영향 작음",
        "addition": {
            "file": "agents/run_stock_agent_v2.py",
            "function": "compute_f09",
            "change": "evaluator FAIL 분기 추가로 부분 산출 유지",
        },
    }
    Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_4_response_rejects_missing_required():
    schema = _load("peer_review_response.schema.json")
    fixture = {
        # missing "domain_relevance"
        "agent": "news-agent",
        "agreement": "agree",
        "urgency_vote": 1,
        "reason": "valid reason text here for testing purpose",
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_5_response_rejects_short_reason():
    schema = _load("peer_review_response.schema.json")
    fixture = {
        "agent": "news-agent",
        "domain_relevance": "direct",
        "agreement": "agree",
        "urgency_vote": 1,
        "reason": "too short",  # < 20 chars
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_6_response_rejects_invalid_enum():
    schema = _load("peer_review_response.schema.json")
    fixture = {
        "agent": "news-agent",
        "domain_relevance": "tangent",  # not in enum
        "agreement": "agree",
        "urgency_vote": 1,
        "reason": "valid reason text here for testing purpose",
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)


# ── Concerns schema ────────────────────────────────────────────────

def test_T_TF_S_7_concerns_schema_self_valid():
    schema = _load("peer_review_concerns.schema.json")
    Draft202012Validator.check_schema(schema)


def test_T_TF_S_8_concerns_accepts_valid():
    schema = _load("peer_review_concerns.schema.json")
    fixture = {
        "domain": "news collection (Google RSS, body fetch)",
        "failure_modes": [
            "RSS returns empty feed but mtime refreshes",
            "Single-source dominance leads to causation bias",
        ],
        "verification_targets": [
            {
                "file": "output/news_report.json",
                "key": "articles",
                "check": "len >= 5 AND len(set(a.source)) >= 3",
            }
        ],
    }
    Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_9_concerns_rejects_empty_failure_modes():
    schema = _load("peer_review_concerns.schema.json")
    fixture = {
        "domain": "news collection",
        "failure_modes": [],  # violates minItems=1
        "verification_targets": [
            {
                "file": "output/news_report.json",
                "key": "articles",
                "check": "len >= 5",
            }
        ],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)


def test_T_TF_S_10_concerns_rejects_missing_target_field():
    schema = _load("peer_review_concerns.schema.json")
    fixture = {
        "domain": "news collection",
        "failure_modes": ["RSS returns empty feed silently"],
        "verification_targets": [
            {
                "file": "output/news_report.json",
                "key": "articles",
                # missing "check"
            }
        ],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)
