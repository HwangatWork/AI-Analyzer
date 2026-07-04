# -*- coding: utf-8 -*-
"""Consensus Revision Tracker - Phase 0-A1 Static Source Access Audit.

Static configuration audit only. Default mode makes ZERO network calls.
This phase MUST NOT fetch financial data.

Exit codes:
  0 - audit completed, output written
  1 - invalid source config
  2 - output write failed
  4 - unsafe flag requested (--live, --fetch-data)
  5 - invalid policy keyword config
  6 - output schema verification failed

Required CLI:
  python tools/consensus/source_access_audit.py \
    --config configs/consensus_sources.json \
    --policy configs/policy_keywords.json \
    --out output/consensus_audit/source_access_audit.json

Forbidden flags (rejected with exit code 4):
  --live
  --fetch-data
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import socket
import sys
from typing import Any


EXIT_OK = 0
EXIT_INVALID_SOURCES = 1
EXIT_WRITE_FAILED = 2
EXIT_UNSAFE_FLAG = 4
EXIT_INVALID_POLICY = 5
EXIT_SCHEMA_FAILED = 6


REQUIRED_SOURCE_FIELDS = (
    "source_provider",
    "source_type",
    "homepage_url",
    "robots_url",
    "terms_url",
    "requires_login",
    "requires_api_key",
    "expected_data_roles",
    "live_audit_allowed",
    "financial_data_fetch_allowed",
    "notes",
)

REQUIRED_POLICY_CATEGORIES = (
    "automation",
    "redistribution",
    "login",
    "api_key",
    "storage",
    "commercial_use",
)

REQUIRED_OUTPUT_TOP_LEVEL = (
    "generated_at",
    "mode",
    "network_calls_made",
    "target",
    "defaults",
    "config_valid",
    "policy_keywords_valid",
    "sources",
    "summary",
    "errors",
)

REQUIRED_OUTPUT_SOURCE_FIELDS = (
    "source_provider",
    "source_type",
    "homepage_url",
    "robots_url",
    "terms_url",
    "requires_login",
    "requires_api_key",
    "expected_data_roles",
    "live_audit_allowed",
    "financial_data_fetch_allowed",
    "config_status",
    "license_risk",
    "risk_reason_codes",
    "point_in_time_status",
    "ready_for_future_live_policy_audit",
    "ready_for_future_data_smoke_test",
    "errors",
)


class NetworkAccessForbidden(RuntimeError):
    """Raised if any code path attempts socket access during dry-run."""


def _install_network_guard() -> None:
    """Replace socket.socket and socket.create_connection with refusers.

    Phase 0-A1 is metadata-only. Any attempt to open a socket indicates a
    programming error and must hard-fail rather than silently leak traffic.
    """
    def _blocked(*_a: Any, **_kw: Any) -> Any:
        raise NetworkAccessForbidden(
            "Phase 0-A1 must make zero network calls. "
            "socket access attempted in dry-run mode."
        )

    socket.socket = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_sources_config(cfg: Any) -> tuple[bool, list[str]]:
    """Return (ok, errors). Strict: every required field must be present.

    Also enforces:
      - at least 7 sources
      - unique source_provider names
      - financial_data_fetch_allowed is False everywhere (Phase 0-A1 invariant)
    """
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return False, ["sources_config: root must be an object"]
    sources = cfg.get("sources")
    if not isinstance(sources, list):
        return False, ["sources_config: 'sources' must be a list"]
    if len(sources) < 7:
        errors.append(
            f"sources_config: at least 7 sources required, found {len(sources)}"
        )
    seen: set[str] = set()
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            errors.append(f"sources[{idx}]: must be an object")
            continue
        for field in REQUIRED_SOURCE_FIELDS:
            if field not in src:
                errors.append(f"sources[{idx}]: missing required field '{field}'")
        provider = src.get("source_provider")
        if isinstance(provider, str):
            if provider in seen:
                errors.append(
                    f"sources[{idx}]: duplicate source_provider '{provider}'"
                )
            seen.add(provider)
        if src.get("financial_data_fetch_allowed") is True:
            errors.append(
                f"sources[{idx}] ({provider!r}): financial_data_fetch_allowed must be "
                "false in Phase 0-A1"
            )
    return (not errors), errors


def validate_policy_config(cfg: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return False, ["policy_keywords: root must be an object"]
    categories = cfg.get("categories")
    if not isinstance(categories, dict):
        return False, ["policy_keywords: 'categories' must be an object"]
    for cat in REQUIRED_POLICY_CATEGORIES:
        if cat not in categories:
            errors.append(f"policy_keywords: missing category '{cat}'")
            continue
        entry = categories[cat]
        if not isinstance(entry, dict):
            errors.append(f"policy_keywords[{cat}]: must be an object")
            continue
        for lang in ("ko", "en"):
            terms = entry.get(lang)
            if not isinstance(terms, list) or not terms:
                errors.append(
                    f"policy_keywords[{cat}][{lang}]: must be a non-empty list"
                )
    return (not errors), errors


def assess_license_risk(src: dict[str, Any]) -> tuple[str, list[str]]:
    """Heuristic risk classification at config-audit time.

    Decision tree (Phase 0-A1, before any live policy audit):
      - high   : requires_login OR live_audit_allowed=False is paired with
                 strong third-party-friendly provider concerns (Investing/yfinance)
      - medium : requires_api_key only OR public_page with notes hinting risk
      - low    : official_api with explicit redistribution-controlled framing
                 and no login wall (e.g. DART)
      - unknown: anything we cannot classify with config alone
    """
    reason_codes: list[str] = []
    provider = src.get("source_provider", "")
    s_type = src.get("source_type", "")
    requires_login = bool(src.get("requires_login"))
    requires_api_key = bool(src.get("requires_api_key"))

    if requires_login:
        reason_codes.append("login_required")
    if requires_api_key:
        reason_codes.append("api_key_required")
    if s_type == "public_page":
        reason_codes.append("public_page_html_dependency")
    if s_type == "library":
        reason_codes.append("unofficial_wrapper")
    if provider in {"Investing", "yfinance"}:
        reason_codes.append("provider_anti_automation_history")
    if provider == "DART":
        reason_codes.append("government_open_data")

    if "government_open_data" in reason_codes and not requires_login:
        return "low", reason_codes
    if "provider_anti_automation_history" in reason_codes or requires_login:
        return "high", reason_codes
    if requires_api_key or "public_page_html_dependency" in reason_codes:
        return "medium", reason_codes
    return "unknown", reason_codes


def build_output(
    sources_cfg: dict[str, Any],
    policy_cfg: dict[str, Any],
    config_valid: bool,
    config_errors: list[str],
    policy_valid: bool,
    policy_errors: list[str],
) -> dict[str, Any]:
    target = sources_cfg.get("target") if isinstance(sources_cfg, dict) else None
    if not isinstance(target, dict):
        target = {"ticker": "000660", "company": "SK hynix"}

    source_entries: list[dict[str, Any]] = []
    raw_sources = (
        sources_cfg.get("sources", [])
        if isinstance(sources_cfg, dict) else []
    )
    for src in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(src, dict):
            continue
        risk, reasons = assess_license_risk(src)
        entry: dict[str, Any] = {
            "source_provider": src.get("source_provider"),
            "source_type": src.get("source_type"),
            "homepage_url": src.get("homepage_url"),
            "robots_url": src.get("robots_url"),
            "terms_url": src.get("terms_url"),
            "requires_login": bool(src.get("requires_login")),
            "requires_api_key": bool(src.get("requires_api_key")),
            "expected_data_roles": list(src.get("expected_data_roles") or []),
            "live_audit_allowed": bool(src.get("live_audit_allowed")),
            "financial_data_fetch_allowed": bool(
                src.get("financial_data_fetch_allowed")
            ),
            "config_status": "ok" if config_valid else "config_invalid",
            "license_risk": risk,
            "risk_reason_codes": reasons,
            "point_in_time_status": "unknown",
            "ready_for_future_live_policy_audit": (
                config_valid
                and not bool(src.get("requires_login"))
                and risk in {"low", "medium"}
            ),
            "ready_for_future_data_smoke_test": False,
            "errors": [],
        }
        source_entries.append(entry)

    accessible = sum(
        1 for e in source_entries
        if e["config_status"] == "ok" and e["license_risk"] != "high"
    )
    blocked = sum(1 for e in source_entries if e["license_risk"] == "high")
    unknown = sum(1 for e in source_entries if e["license_risk"] == "unknown")
    ready = [
        e["source_provider"] for e in source_entries
        if e["ready_for_future_live_policy_audit"]
    ]

    return {
        "generated_at": _now_iso(),
        "mode": "dry_run_static_audit",
        "network_calls_made": 0,
        "target": target,
        "defaults": {
            "purpose": "llm_report_assistant",
            "budget_krw_monthly": 0,
            "external_distribution": False,
            "collection_mode": "metadata_only",
            "live_network": False,
            "ticker": target.get("ticker"),
        },
        "config_valid": config_valid,
        "policy_keywords_valid": policy_valid,
        "sources": source_entries,
        "summary": {
            "total_sources": len(source_entries),
            "accessible_sources": accessible,
            "blocked_sources": blocked,
            "unknown_license_sources": unknown,
            "ready_for_smoke_test": ready,
        },
        "errors": {
            "sources_config": config_errors,
            "policy_keywords": policy_errors,
        },
    }


def verify_output_schema(obj: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["output: root must be an object"]
    for f in REQUIRED_OUTPUT_TOP_LEVEL:
        if f not in obj:
            errors.append(f"output: missing top-level field '{f}'")
    if obj.get("network_calls_made", -1) != 0:
        errors.append("output: network_calls_made must be 0 in dry-run")
    if obj.get("mode") != "dry_run_static_audit":
        errors.append("output: mode must be 'dry_run_static_audit'")
    sources = obj.get("sources")
    if not isinstance(sources, list):
        errors.append("output: 'sources' must be a list")
    else:
        for idx, entry in enumerate(sources):
            if not isinstance(entry, dict):
                errors.append(f"output.sources[{idx}]: must be an object")
                continue
            for f in REQUIRED_OUTPUT_SOURCE_FIELDS:
                if f not in entry:
                    errors.append(
                        f"output.sources[{idx}]: missing field '{f}'"
                    )
    return (not errors), errors


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Phase 0-A1 Static Source Access Audit (no network)."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    # Forbidden flags are intentionally declared so argparse accepts them
    # and main() can return EXIT_UNSAFE_FLAG with a clear message.
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fetch-data", dest="fetch_data", action="store_true")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, unknown = _parse_args(list(sys.argv[1:]) if argv is None else argv)

    if args.live or args.fetch_data or any(
        u in {"--live", "--fetch-data"} for u in unknown
    ):
        sys.stderr.write(
            "ERROR: --live and --fetch-data are forbidden in Phase 0-A1. "
            "This phase must make zero network calls.\n"
        )
        return EXIT_UNSAFE_FLAG

    _install_network_guard()

    # Load configs
    try:
        sources_cfg = _load_json(args.config)
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: source config not found: {args.config}\n")
        return EXIT_INVALID_SOURCES
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: source config JSON invalid: {exc}\n")
        return EXIT_INVALID_SOURCES

    try:
        policy_cfg = _load_json(args.policy)
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: policy keywords file not found: {args.policy}\n")
        return EXIT_INVALID_POLICY
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: policy keywords JSON invalid: {exc}\n")
        return EXIT_INVALID_POLICY

    config_ok, config_errors = validate_sources_config(sources_cfg)
    policy_ok, policy_errors = validate_policy_config(policy_cfg)

    if not config_ok:
        for e in config_errors:
            sys.stderr.write(f"sources_config: {e}\n")
        return EXIT_INVALID_SOURCES

    if not policy_ok:
        for e in policy_errors:
            sys.stderr.write(f"policy_keywords: {e}\n")
        return EXIT_INVALID_POLICY

    output = build_output(
        sources_cfg,
        policy_cfg,
        config_ok,
        config_errors,
        policy_ok,
        policy_errors,
    )

    schema_ok, schema_errors = verify_output_schema(output)
    if not schema_ok:
        for e in schema_errors:
            sys.stderr.write(f"schema: {e}\n")
        return EXIT_SCHEMA_FAILED

    try:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(output, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write(f"ERROR: failed to write output {args.out}: {exc}\n")
        return EXIT_WRITE_FAILED

    sys.stdout.write(
        "DONE_CRITERIA: PASS -- "
        f"sources={len(output['sources'])} "
        f"network_calls_made={output['network_calls_made']} "
        f"ready_for_smoke_test={len(output['summary']['ready_for_smoke_test'])}\n"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
