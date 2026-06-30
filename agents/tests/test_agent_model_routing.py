# -*- coding: utf-8 -*-
"""
Phase 13-D-2 (사이클 1 Commit 2/3): agent frontmatter model 필드 정적 검증.

배경: 옵션 3 hybrid model 분기 (data/ui/report → sonnet, 나머지 inherit).
audit 5차 결과 self-report 신뢰 불가 + 사용자가 routing 진위 검증 요구.
정적 검증 (frontmatter syntax + 일관성) 으로 Level 7 evidence 확보.
동적 검증 (실 routing) 은 manual dogfood — 사용자 session 재시작 후 확인.

Tests:
T-AMR-1: 14 worker agent MD 모두 frontmatter 존재 + 파싱 가능
T-AMR-2: data/ui/report-agent 에 정확히 'model: sonnet' (Anthropic 공식 syntax)
T-AMR-3: 나머지 11 agent (pm/analysis/evaluator/validation/decision/stock/sector/
   news/narrative/audit/meta-audit) 는 model 키 부재 (inherit = main session)
T-AMR-4: model 값이 Anthropic 공식 enum (sonnet/opus/haiku/fable/inherit/full-id)
T-AMR-5: frontmatter 필수 필드 (name, description, tools) 누락 없음
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO_ROOT / ".claude" / "agents"

_SONNET_AGENTS = {"data-agent", "ui-agent", "report-agent"}
_INHERIT_AGENTS = {
    "pm-agent", "analysis-agent", "evaluator-agent", "validation-agent",
    "decision-agent", "stock-agent", "sector-agent", "news-agent",
    "narrative-agent", "audit-agent", "meta-audit-agent",
}
_ALL_WORKER_AGENTS = _SONNET_AGENTS | _INHERIT_AGENTS  # 14 total

_VALID_MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable", "inherit"}
_VALID_MODEL_FULL_RE = re.compile(r"^claude-(opus|sonnet|haiku|fable)-\d[\d\-a-z]*$")


def _parse_frontmatter(md_path: Path) -> dict:
    """간단한 yaml frontmatter 파서 (---  ... ---) → dict."""
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


@pytest.fixture(scope="module")
def agent_mds() -> dict[str, dict]:
    """14 worker agent MD frontmatter 파싱 결과."""
    out = {}
    for stem in _ALL_WORKER_AGENTS:
        p = _AGENTS_DIR / f"{stem}.md"
        if p.exists():
            out[stem] = _parse_frontmatter(p)
    return out


def test_T_AMR_1_all_14_mds_parseable(agent_mds):
    """14 agent MD 모두 존재 + frontmatter 파싱 가능."""
    missing = _ALL_WORKER_AGENTS - agent_mds.keys()
    assert not missing, f"누락된 agent MD: {missing}"
    for stem, fm in agent_mds.items():
        assert fm, f"{stem}.md frontmatter 빈 또는 파싱 실패"


def test_T_AMR_2_sonnet_agents_have_model_sonnet(agent_mds):
    """data/ui/report-agent 가 정확히 'model: sonnet' 보유."""
    for stem in _SONNET_AGENTS:
        fm = agent_mds[stem]
        assert "model" in fm, f"{stem}.md 에 model 키 부재 (Sonnet 분기 미적용)"
        assert fm["model"] == "sonnet", (
            f"{stem}.md model 값 잘못됨: {fm['model']!r} (expected: 'sonnet')"
        )


def test_T_AMR_3_inherit_agents_have_no_model_field(agent_mds):
    """11 reasoning agent 는 model 키 부재 (inherit = Opus)."""
    for stem in _INHERIT_AGENTS:
        fm = agent_mds[stem]
        assert "model" not in fm, (
            f"{stem}.md 에 model 키 존재: {fm.get('model')!r} "
            f"(inherit 의도였다면 frontmatter 에서 제거 필요)"
        )


def test_T_AMR_4_model_values_are_valid_anthropic_syntax(agent_mds):
    """model 값이 Anthropic 공식 enum (alias 또는 full ID) 인지."""
    for stem, fm in agent_mds.items():
        if "model" not in fm:
            continue  # inherit
        value = fm["model"]
        is_alias = value in _VALID_MODEL_ALIASES
        is_full_id = bool(_VALID_MODEL_FULL_RE.match(value))
        assert is_alias or is_full_id, (
            f"{stem}.md model={value!r} 가 Anthropic 공식 syntax 아님. "
            f"허용: {_VALID_MODEL_ALIASES} 또는 claude-<family>-<version>"
        )


def test_T_AMR_5_required_frontmatter_fields(agent_mds):
    """name / description / tools 누락 없음."""
    required = {"name", "description", "tools"}
    for stem, fm in agent_mds.items():
        missing = required - fm.keys()
        assert not missing, f"{stem}.md frontmatter 누락 필드: {missing}"
