# -*- coding: utf-8 -*-
"""
Phase 14-0-A2 회귀: Static robots.txt analyzer (zero-network).

Tests: T-SRA-1 ~ T-SRA-8
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO_ROOT / "tests" / "consensus" / "fixtures"

import sys
sys.path.insert(0, str(_REPO_ROOT))
from tools.consensus import static_robots_analyzer as sra


def test_T_SRA_1_allowed_with_disallow_rules():
    p = _FIXTURES / "robots_sample_allowed.txt"
    r = sra.analyze_robots(p, path_to_check="/", user_agent="*")
    assert r["allowed"] is True
    assert "/admin/" in r["disallow_rules"]
    assert "/private/" in r["disallow_rules"]


def test_T_SRA_2_full_disallow_flagged():
    p = _FIXTURES / "robots_sample_denied_all.txt"
    r = sra.analyze_robots(p, path_to_check="/", user_agent="*")
    assert r["allowed"] is False
    assert "full_disallow_for_all_ua" in r["risk_flags"]


def test_T_SRA_3_sha256_reproducible():
    p = _FIXTURES / "robots_sample_allowed.txt"
    r1 = sra.analyze_robots(p)
    r2 = sra.analyze_robots(p)
    assert r1["sha256"] == r2["sha256"]
    assert len(r1["sha256"]) == 64


def test_T_SRA_4_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sra.analyze_robots(tmp_path / "nonexistent.txt")


def test_T_SRA_5_crawl_delay_float_sec():
    p = _FIXTURES / "robots_sample_allowed.txt"
    r = sra.analyze_robots(p, user_agent="*")
    assert r["crawl_delay"] == 2.0
    assert isinstance(r["crawl_delay"], float)


def test_T_SRA_6_no_sitemap_flagged():
    p = _FIXTURES / "robots_sample_denied_all.txt"
    r = sra.analyze_robots(p)
    assert "no_sitemap_declared" in r["risk_flags"]


def test_T_SRA_7_cli_exit_zero(capsys):
    p = _FIXTURES / "robots_sample_allowed.txt"
    rc = sra.main(["--cached", str(p), "--path", "/", "--ua", "*"])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["allowed"] is True


def test_T_SRA_8_analyzed_at_iso_utc():
    p = _FIXTURES / "robots_sample_allowed.txt"
    r = sra.analyze_robots(p)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", r["analyzed_at"])
    assert "+00:00" in r["analyzed_at"] or r["analyzed_at"].endswith("Z")
