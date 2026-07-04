# -*- coding: utf-8 -*-
"""Mock-only tests for smoke_fetch (Data Agent unit)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus import smoke_fetch as sf  # noqa: E402


def _allow_robots(_rurl):
    return 200, "User-agent: *\nAllow: /\n"


def _deny_robots(_rurl):
    return 200, "User-agent: *\nDisallow: /\n"


def _ok_page_fetcher(html_bytes=b"<html>ok</html>"):
    def _f(_url, _ua, _to):
        return {
            "status": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body_bytes": html_bytes,
            "error": None,
        }
    return _f


def _err_page_fetcher(status=500):
    def _f(_url, _ua, _to):
        return {
            "status": status,
            "headers": {},
            "body_bytes": b"",
            "error": f"HTTPError {status}",
        }
    return _f


def test_smoke_flag_required(tmp_path):
    r = sf.smoke_fetch(
        ticker="000660", out_dir=str(tmp_path), smoke=False,
        robots_fetcher=_allow_robots, page_fetcher=_ok_page_fetcher(),
    )
    assert r["exit_code"] == sf.EXIT_SMOKE_FLAG_MISSING


def test_unknown_ticker_blocked(tmp_path):
    r = sf.smoke_fetch(
        ticker="999999", out_dir=str(tmp_path), smoke=True,
        robots_fetcher=_allow_robots, page_fetcher=_ok_page_fetcher(),
    )
    assert r["exit_code"] == sf.EXIT_INVALID_ARGS


def test_robots_denied_blocks_fetch(tmp_path):
    r = sf.smoke_fetch(
        ticker="000660", out_dir=str(tmp_path), smoke=True,
        robots_fetcher=_deny_robots, page_fetcher=_ok_page_fetcher(),
    )
    assert r["exit_code"] == sf.EXIT_ROBOTS_DENIED
    # G1 invariant: page fetcher must not be called when robots denied.
    assert r["http_status"] is None


def test_http_error_returns_exit_3(tmp_path):
    r = sf.smoke_fetch(
        ticker="000660", out_dir=str(tmp_path), smoke=True,
        robots_fetcher=_allow_robots, page_fetcher=_err_page_fetcher(500),
    )
    assert r["exit_code"] == sf.EXIT_HTTP_ERROR


def test_happy_path_writes_raw_and_manifest(tmp_path):
    html = b"<html><body>SK hynix</body></html>"
    r = sf.smoke_fetch(
        ticker="000660", out_dir=str(tmp_path), smoke=True,
        robots_fetcher=_allow_robots, page_fetcher=_ok_page_fetcher(html),
    )
    assert r["exit_code"] == sf.EXIT_OK
    assert r["http_status"] == 200
    assert r["bytes"] == len(html)
    raw_path = Path(r["raw_html_path"])
    manifest_path = Path(r["manifest_path"])
    assert raw_path.exists()
    assert manifest_path.exists()
    assert raw_path.read_bytes() == html
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ticker"] == "000660"
    assert manifest["company"] == "SK hynix"
    assert manifest["sha256"] == r["sha256"]


def test_known_ticker_table_includes_sk_hynix():
    assert sf.KNOWN_TICKERS["000660"] == "SK hynix"


def test_url_pattern_uses_naver_finance():
    url = sf.naver_consensus_url("000660")
    assert url.startswith("https://finance.naver.com/")
    assert "code=000660" in url


def test_no_retries_after_http_error(tmp_path, monkeypatch):
    """If HTTP fetch fails, the tool must NOT call the page fetcher twice."""
    calls = {"page": 0}

    def _counting(_url, _ua, _to):
        calls["page"] += 1
        return {
            "status": 503, "headers": {}, "body_bytes": b"",
            "error": "HTTPError 503",
        }

    r = sf.smoke_fetch(
        ticker="000660", out_dir=str(tmp_path), smoke=True,
        robots_fetcher=_allow_robots, page_fetcher=_counting,
    )
    assert r["exit_code"] == sf.EXIT_HTTP_ERROR
    assert calls["page"] == 1


def test_main_cli_returns_smoke_missing(monkeypatch, tmp_path):
    code = sf.main([
        "--ticker", "000660", "--out-dir", str(tmp_path),
    ])
    assert code == sf.EXIT_SMOKE_FLAG_MISSING
