# -*- coding: utf-8 -*-
"""Phase 14-0-B2 — Single-source smoke fetch (Data Agent).

Performs ONE HTTP GET to fetch a consensus page after passing the
robots.txt check (Audit Agent's gate G1). Saves raw HTML + manifest.

Hard constraints:
  - Requires explicit --smoke flag (default deny — Phase 14-0-A1 invariant).
  - At most ONE consensus page fetch per invocation (plus one robots.txt).
  - No retries. No follow-up GETs. No POST. No cookies.

Exit codes:
  0 - fetch succeeded, raw HTML + manifest written
  1 - invalid args / config
  2 - output write failed
  3 - HTTP error (non-2xx)
  4 - missing --smoke flag (default-deny gate)
  7 - robots.txt denied the fetch
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

try:
    from tools.consensus.robots_check import check_robots, DEFAULT_UA
except ImportError:  # CLI invocation from repo root without -m
    import os.path as _osp
    sys.path.insert(0, _osp.dirname(_osp.dirname(_osp.dirname(
        _osp.abspath(__file__)
    ))))
    from tools.consensus.robots_check import check_robots, DEFAULT_UA


EXIT_OK = 0
EXIT_INVALID_ARGS = 1
EXIT_WRITE_FAILED = 2
EXIT_HTTP_ERROR = 3
EXIT_SMOKE_FLAG_MISSING = 4
EXIT_ROBOTS_DENIED = 7


KNOWN_TICKERS = {
    "000660": "SK hynix",
    "005930": "Samsung Electronics",
    "035420": "NAVER",
    "035720": "Kakao",
    "207940": "Samsung Biologics",
}


def naver_consensus_url(ticker: str) -> str:
    """Naver Finance 종목분석 main page (1차 시도 - 보통 robots disallow 됨)."""
    return f"https://finance.naver.com/item/main.naver?code={ticker}"


def wisereport_consensus_url(ticker: str) -> str:
    """WiseReport (FnGuide) 종목분석 페이지 - Naver iframe target. robots 404
    → default allow per RFC 9309. 컨센서스 + 추정실적 + 증권사별 의견 포함."""
    return (
        "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"
        f"?cn=&cmp_cd={ticker}"
    )


SOURCE_URL_BUILDERS = {
    "naver": naver_consensus_url,
    "wisereport": wisereport_consensus_url,
}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def fetch_once(
    url: str,
    user_agent: str = DEFAULT_UA,
    timeout: float = 15.0,
    fetcher=None,
) -> dict:
    """Perform one GET. Returns dict with status/body/headers/error."""
    if fetcher is None:
        def _default(rurl, ua, to):
            req = urllib.request.Request(rurl, headers={"User-Agent": ua})
            try:
                with urllib.request.urlopen(req, timeout=to) as resp:
                    body_bytes = resp.read()
                    return {
                        "status": resp.status,
                        "headers": {k: v for k, v in resp.headers.items()},
                        "body_bytes": body_bytes,
                        "error": None,
                    }
            except urllib.error.HTTPError as e:
                try:
                    body_bytes = e.read()
                except Exception:
                    body_bytes = b""
                return {
                    "status": e.code,
                    "headers": dict(e.headers) if e.headers else {},
                    "body_bytes": body_bytes,
                    "error": f"HTTPError {e.code}",
                }
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return {
                    "status": None,
                    "headers": {},
                    "body_bytes": b"",
                    "error": f"{type(e).__name__}: {e!r}",
                }
        return _default(url, user_agent, timeout)
    return fetcher(url, user_agent, timeout)


def _detect_encoding(body_bytes: bytes, headers: dict) -> str:
    """Best-effort: prefer Content-Type charset, fall back to utf-8."""
    ct = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            ct = v.lower()
            break
    if "charset=" in ct:
        return ct.split("charset=", 1)[1].split(";")[0].strip()
    # Naver Finance pages are EUC-KR historically; sniff for the meta hint
    head = body_bytes[:2048].decode("latin-1", errors="replace").lower()
    if "euc-kr" in head:
        return "euc-kr"
    if "utf-8" in head:
        return "utf-8"
    return "utf-8"


def smoke_fetch(
    ticker: str,
    out_dir: str,
    smoke: bool,
    source: str = "wisereport",
    user_agent: str = DEFAULT_UA,
    timeout: float = 15.0,
    robots_fetcher=None,
    page_fetcher=None,
    now_fn=_now_iso,
) -> dict:
    """Top-level pipeline call for one smoke fetch.

    Returns a result dict with exit_code and metadata.
    """
    result = {
        "ticker": ticker,
        "company": KNOWN_TICKERS.get(ticker),
        "source": source,
        "url": None,
        "robots_decision": None,
        "fetched_at": now_fn(),
        "http_status": None,
        "bytes": 0,
        "sha256": None,
        "raw_html_path": None,
        "manifest_path": None,
        "errors": [],
        "exit_code": EXIT_OK,
    }

    if not smoke:
        result["errors"].append(
            "missing_smoke_flag: --smoke is required (default-deny)"
        )
        result["exit_code"] = EXIT_SMOKE_FLAG_MISSING
        return result

    # Stock Agent's job: validate ticker
    if ticker not in KNOWN_TICKERS:
        result["errors"].append(f"unknown_ticker: {ticker}")
        result["exit_code"] = EXIT_INVALID_ARGS
        return result

    if source not in SOURCE_URL_BUILDERS:
        result["errors"].append(f"unknown_source: {source}")
        result["exit_code"] = EXIT_INVALID_ARGS
        return result
    url = SOURCE_URL_BUILDERS[source](ticker)
    result["url"] = url

    # GATE G1: robots.txt check BEFORE fetch (Audit Agent handoff)
    decision = check_robots(
        url, user_agent=user_agent, fetcher=robots_fetcher
    )
    result["robots_decision"] = decision
    if not decision["allowed"]:
        result["errors"].append(
            f"robots_denied: {decision['reason']}"
        )
        result["exit_code"] = EXIT_ROBOTS_DENIED
        return result

    # Single GET
    resp = fetch_once(
        url, user_agent=user_agent, timeout=timeout, fetcher=page_fetcher
    )
    result["http_status"] = resp["status"]
    if resp["status"] is None or resp["status"] >= 400:
        result["errors"].append(
            f"http_error: status={resp['status']} err={resp['error']}"
        )
        result["exit_code"] = EXIT_HTTP_ERROR
        return result

    body_bytes = resp["body_bytes"]
    result["bytes"] = len(body_bytes)
    result["sha256"] = hashlib.sha256(body_bytes).hexdigest()
    encoding = _detect_encoding(body_bytes, resp["headers"])
    result["encoding_detected"] = encoding

    # Persist
    try:
        os.makedirs(out_dir, exist_ok=True)
        date_str = result["fetched_at"][:10]
        raw_path = os.path.join(
            out_dir, f"{ticker}_{date_str}_raw.html"
        )
        manifest_path = os.path.join(
            out_dir, f"{ticker}_{date_str}_fetch.json"
        )
        with open(raw_path, "wb") as fh:
            fh.write(body_bytes)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            manifest = {k: v for k, v in result.items()
                        if k != "raw_html_path" and k != "manifest_path"}
            manifest["raw_html_path"] = raw_path
            json.dump(manifest, fh, ensure_ascii=False, indent=2,
                      sort_keys=True)
            fh.write("\n")
        result["raw_html_path"] = raw_path
        result["manifest_path"] = manifest_path
    except OSError as e:
        result["errors"].append(f"write_failed: {e!r}")
        result["exit_code"] = EXIT_WRITE_FAILED
        return result

    result["exit_code"] = EXIT_OK
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 14-0-B2 single-source smoke fetch"
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--out-dir", default="output/consensus_snapshot")
    parser.add_argument(
        "--source", default="wisereport",
        choices=sorted(SOURCE_URL_BUILDERS.keys()),
        help="data source (default: wisereport)"
    )
    parser.add_argument("--smoke", action="store_true",
                        help="REQUIRED -- confirms intent to make a network call")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    result = smoke_fetch(
        ticker=args.ticker,
        out_dir=args.out_dir,
        smoke=args.smoke,
        source=args.source,
        timeout=args.timeout,
    )

    # Summarize to stdout (ASCII-safe; no em-dash)
    msg = (
        f"smoke_fetch: ticker={result['ticker']} "
        f"http_status={result['http_status']} "
        f"bytes={result['bytes']} "
        f"sha256={result['sha256']} "
        f"exit_code={result['exit_code']}"
    )
    if result["errors"]:
        msg += " errors=" + "; ".join(result["errors"])[:200]
    sys.stdout.write(msg + "\n")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
