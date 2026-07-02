# -*- coding: utf-8 -*-
"""
2026-07-03 사용자 요청: Notion 자식 페이지 매일 생성 회귀.

Tests:
T-NDC-1: markdown_to_notion_blocks — H1/H2/H3 헤더 파싱
T-NDC-2: markdown_to_notion_blocks — bullet + paragraph + divider
T-NDC-3: markdown_to_notion_blocks — 코드 블록 (```)
T-NDC-4: markdown_to_notion_blocks — 빈 마크다운 → 빈 블록
T-NDC-5: create_daily_child_page — 이미 존재하면 skip
T-NDC-6: create_daily_child_page — 리포트 파일 부재 → error
T-NDC-7: create_daily_child_page — 정상 생성 (mock httpx)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "agents"))


@pytest.fixture(scope="module")
def notion_mod():
    spec = importlib.util.spec_from_file_location(
        "run_notion_agent",
        _REPO_ROOT / "agents" / "run_notion_agent.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_NDC_1_headers_parsed(notion_mod):
    md = "# 대제목\n## 중제목\n### 소제목\n"
    blocks = notion_mod.markdown_to_notion_blocks(md)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "heading_1"
    assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "대제목"
    assert blocks[1]["type"] == "heading_2"
    assert blocks[2]["type"] == "heading_3"


def test_T_NDC_2_bullet_paragraph_divider(notion_mod):
    md = "일반 문장\n- 첫번째 bullet\n- 두번째 bullet\n---\n마지막 문단"
    blocks = notion_mod.markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    assert "paragraph" in types
    assert types.count("bulleted_list_item") == 2
    assert "divider" in types


def test_T_NDC_3_code_block(notion_mod):
    md = "설명\n```python\nprint('hello')\n```\n뒤 문장"
    blocks = notion_mod.markdown_to_notion_blocks(md)
    code_blocks = [b for b in blocks if b["type"] == "code"]
    assert len(code_blocks) == 1
    assert code_blocks[0]["code"]["language"] == "python"
    content = code_blocks[0]["code"]["rich_text"][0]["text"]["content"]
    assert "print" in content


def test_T_NDC_4_empty_markdown_empty_blocks(notion_mod):
    assert notion_mod.markdown_to_notion_blocks("") == []
    assert notion_mod.markdown_to_notion_blocks("\n\n   \n") == []


def test_T_NDC_5_child_page_skipped_when_exists(notion_mod, tmp_path, monkeypatch):
    """이미 존재하는 title → skip."""
    md_path = tmp_path / "FINAL_REPORT_v2.md"
    md_path.write_text("# 리포트\n\n내용", encoding="utf-8")

    def fake_get(path):
        # /blocks/<parent>/children?... 응답
        return {
            "results": [{
                "type": "child_page",
                "id": "existing-page-id",
                "child_page": {"title": "2026-07-03 리포트"},
            }]
        }

    monkeypatch.setattr(notion_mod, "_get", fake_get)
    result = notion_mod.create_daily_child_page(
        parent_id="parent-x",
        date_str="2026-07-03",
        report_md_path=md_path,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "already_exists"
    assert result["page_id"] == "existing-page-id"


def test_T_NDC_6_missing_report_returns_error(notion_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(notion_mod, "_get", lambda p: {"results": []})
    result = notion_mod.create_daily_child_page(
        parent_id="parent-x",
        date_str="2026-07-03",
        report_md_path=tmp_path / "nonexistent.md",
    )
    assert result["status"] == "error"
    assert "미존재" in result["reason"]


def test_T_NDC_7_child_page_created_ok(notion_mod, tmp_path, monkeypatch):
    md_path = tmp_path / "FINAL_REPORT_v2.md"
    md_path.write_text(
        "# 시장 리포트\n## SP500\n- HOLD\n\n## KOSPI\n- HOLD\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(notion_mod, "_get", lambda p: {"results": []})  # 중복 없음

    # httpx.post mock
    fake_response = MagicMock()
    fake_response.json.return_value = {"id": "new-page-id-123"}
    fake_response.raise_for_status = MagicMock()

    with patch.object(notion_mod, "httpx") as fake_httpx:
        fake_httpx.post.return_value = fake_response
        result = notion_mod.create_daily_child_page(
            parent_id="parent-x",
            date_str="2026-07-03",
            report_md_path=md_path,
        )

    assert result["status"] == "created"
    assert result["page_id"] == "new-page-id-123"
    assert result["title"] == "2026-07-03 리포트"
    assert result["block_count"] >= 4  # h1 + h2 + bullet + h2 + bullet ≥ 4
    # httpx.post 호출 검증
    assert fake_httpx.post.called
    call_args = fake_httpx.post.call_args
    body = json.loads(call_args.kwargs["content"].decode("utf-8"))
    assert body["parent"]["page_id"] == "parent-x"
    assert body["properties"]["title"]["title"][0]["text"]["content"] == "2026-07-03 리포트"
