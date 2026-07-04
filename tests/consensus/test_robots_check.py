# -*- coding: utf-8 -*-
"""Mock-only tests for robots_check.

NO test makes a real network call. All tests use the `fetcher` injection.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus import robots_check as rc  # noqa: E402


def _make_fetcher(status, body):
    def _f(_url):
        return status, body
    return _f


def test_allowed_when_robots_allows():
    body = "User-agent: *\nAllow: /\n"
    d = rc.check_robots(
        "https://example.com/page", fetcher=_make_fetcher(200, body)
    )
    assert d["allowed"] is True
    assert d["robots_status"] == 200
    assert d["reason"] == "robots_allow"


def test_denied_when_robots_disallows_path():
    body = "User-agent: *\nDisallow: /private\n"
    d = rc.check_robots(
        "https://example.com/private/x", fetcher=_make_fetcher(200, body)
    )
    assert d["allowed"] is False
    assert d["reason"] == "robots_disallow"


def test_robots_404_defaults_allow():
    d = rc.check_robots(
        "https://example.com/page", fetcher=_make_fetcher(404, "")
    )
    assert d["allowed"] is True
    assert d["robots_status"] == 404
    assert d["reason"] == "robots_missing_default_allow"


def test_robots_500_blocks_fetch():
    d = rc.check_robots(
        "https://example.com/page", fetcher=_make_fetcher(500, "")
    )
    assert d["allowed"] is False
    assert d["robots_status"] == 500


def test_network_failure_blocks_fetch():
    d = rc.check_robots(
        "https://example.com/page",
        fetcher=_make_fetcher(None, "fetch_error: <fake>"),
    )
    assert d["allowed"] is False
    assert d["reason"].startswith("robots_fetch_failed")


def test_invalid_url_blocks():
    d = rc.check_robots("not-a-url", fetcher=_make_fetcher(200, ""))
    assert d["allowed"] is False
    assert d["reason"] == "invalid_url"


def test_robots_url_is_root_derived():
    body = "User-agent: *\nAllow: /\n"
    d = rc.check_robots(
        "https://sub.example.com/deep/path?q=1",
        fetcher=_make_fetcher(200, body),
    )
    assert d["robots_url"] == "https://sub.example.com/robots.txt"


def test_main_cli_writes_json(tmp_path, monkeypatch, capsys):
    body = "User-agent: *\nAllow: /\n"

    def _patch(url, user_agent=rc.DEFAULT_UA, timeout=10.0, fetcher=None):
        return {
            "url": url,
            "robots_url": "https://example.com/robots.txt",
            "robots_status": 200,
            "allowed": True,
            "reason": "robots_allow",
            "user_agent": user_agent,
        }
    monkeypatch.setattr(rc, "check_robots", _patch)
    out = tmp_path / "decision.json"
    code = rc.main(["--url", "https://example.com/page", "--out", str(out)])
    assert code == rc.EXIT_ALLOWED
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["allowed"] is True


def test_main_cli_returns_denied_exit_code(monkeypatch, capsys):
    def _patch(url, user_agent=rc.DEFAULT_UA, timeout=10.0, fetcher=None):
        return {
            "url": url,
            "robots_url": "https://example.com/robots.txt",
            "robots_status": 200,
            "allowed": False,
            "reason": "robots_disallow",
            "user_agent": user_agent,
        }
    monkeypatch.setattr(rc, "check_robots", _patch)
    code = rc.main(["--url", "https://example.com/x"])
    assert code == rc.EXIT_DENIED
