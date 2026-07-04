# -*- coding: utf-8 -*-
"""Phase 14-0-B2 — robots.txt safety check (Audit Agent).

Performs ONE network call: fetches robots.txt for the target domain.
No other URLs are fetched by this module.

Exit codes (CLI):
  0 - fetch allowed (robots.txt permits the path)
  7 - fetch denied (robots.txt disallows the path, or fetch failed)
  1 - invalid arguments
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from urllib import robotparser
from urllib.parse import urlparse


EXIT_ALLOWED = 0
EXIT_INVALID_ARGS = 1
EXIT_DENIED = 7


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def check_robots(
    url: str,
    user_agent: str = DEFAULT_UA,
    timeout: float = 10.0,
    fetcher=None,
) -> dict:
    """Return decision dict. Does NOT raise on network failure.

    Args:
      url: full URL whose path is being checked
      user_agent: UA string used in the can_fetch() lookup
      timeout: seconds for robots.txt fetch
      fetcher: optional callable(robots_url) -> (status:int, body:str)
               for mock-based testing. If None, uses urllib.request.

    Returns:
      {
        "url": original_url,
        "robots_url": robots.txt URL,
        "robots_status": int (200/404/etc) or None on failure,
        "allowed": bool,
        "reason": str,
        "user_agent": user_agent,
      }
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {
            "url": url,
            "robots_url": None,
            "robots_status": None,
            "allowed": False,
            "reason": "invalid_url",
            "user_agent": user_agent,
        }
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if fetcher is None:
        def _default_fetcher(rurl: str):
            req = urllib.request.Request(rurl, headers={"User-Agent": user_agent})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status, resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                # Try to read body, fall back to empty
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                return e.code, body
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return None, f"fetch_error: {e!r}"
        fetcher = _default_fetcher

    status, body = fetcher(robots_url)

    if status is None:
        return {
            "url": url,
            "robots_url": robots_url,
            "robots_status": None,
            "allowed": False,
            "reason": f"robots_fetch_failed: {body[:200]}",
            "user_agent": user_agent,
        }

    if status == 404:
        # RFC: if robots.txt is missing, all fetches are allowed.
        return {
            "url": url,
            "robots_url": robots_url,
            "robots_status": 404,
            "allowed": True,
            "reason": "robots_missing_default_allow",
            "user_agent": user_agent,
        }

    if status != 200:
        return {
            "url": url,
            "robots_url": robots_url,
            "robots_status": status,
            "allowed": False,
            "reason": f"robots_unexpected_status_{status}",
            "user_agent": user_agent,
        }

    parser = robotparser.RobotFileParser()
    parser.parse(body.splitlines())
    can_fetch = parser.can_fetch(user_agent, url)
    return {
        "url": url,
        "robots_url": robots_url,
        "robots_status": 200,
        "allowed": bool(can_fetch),
        "reason": "robots_allow" if can_fetch else "robots_disallow",
        "user_agent": user_agent,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="robots.txt safety check")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=None,
                        help="optional path to write decision JSON")
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    args = parser.parse_args(argv)

    decision = check_robots(args.url, user_agent=args.user_agent)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(decision, fh, ensure_ascii=False, indent=2,
                          sort_keys=True)
                fh.write("\n")
        except OSError as e:
            sys.stderr.write(f"failed to write {args.out}: {e}\n")
            return EXIT_INVALID_ARGS

    sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
    return EXIT_ALLOWED if decision["allowed"] else EXIT_DENIED


if __name__ == "__main__":
    raise SystemExit(main())
