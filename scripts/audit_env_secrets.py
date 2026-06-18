# -*- coding: utf-8 -*-
"""
scripts/audit_env_secrets.py — 3-Environment Credential Consistency Audit

Modes:
  (default)   full audit: .env vs workflow vs GitHub Secrets (needs `gh` auth)
  --no-gh     skip GitHub Secrets check (no auth needed, local-only)
  --ci        CI mode: check os.environ has all secrets referenced in workflow

Exit codes:
  0 = all consistent (or only INFO/WARN, no FAIL)
  1 = FAIL — critical inconsistency found
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
WORKFLOW_FILE = BASE_DIR / ".github" / "workflows" / "deploy-dashboard.yml"

# Keys that are intentionally CI-only (not needed in .env)
CI_ONLY_KEYS = {"GITHUB_TOKEN"}


def _load_env_keys() -> set[str]:
    if not ENV_FILE.exists():
        return set()
    keys = set()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def _load_workflow_secret_refs() -> set[str]:
    """Return all secrets.KEY_NAME referenced in the workflow."""
    if not WORKFLOW_FILE.exists():
        print(f"[audit] workflow not found: {WORKFLOW_FILE}")
        return set()
    content = WORKFLOW_FILE.read_text(encoding="utf-8")
    refs = re.findall(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}", content)
    return set(refs)


def _load_workflow_env_key_names() -> set[str]:
    """Return left-hand-side key names from workflow env: blocks."""
    if not WORKFLOW_FILE.exists():
        return set()
    content = WORKFLOW_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{8,}([A-Z][A-Z0-9_]+)\s*:", content, re.MULTILINE))


def _load_github_secrets() -> set[str] | None:
    try:
        result = subprocess.run(
            ["gh", "secret", "list", "--json", "name"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return {item["name"] for item in data}
    except Exception:
        return None


def _header(title: str) -> None:
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def audit_local(check_gh: bool = True) -> int:
    """Local mode: .env vs workflow vs (optionally) GitHub Secrets."""
    _header("Credential Consistency Audit — Local")

    env_keys = _load_env_keys()
    workflow_refs = _load_workflow_secret_refs()
    gh_secrets = _load_github_secrets() if check_gh else None

    print(f"\n[1] .env keys:              {sorted(env_keys)}")
    print(f"[2] Workflow secret refs:   {sorted(workflow_refs)}")
    if gh_secrets is not None:
        print(f"[3] GitHub Secrets (gh):    {sorted(gh_secrets)}")
    else:
        print("[3] GitHub Secrets:         (skipped - gh not available)")

    issues: list[str] = []
    print("\n── Gap Analysis ──────────────────────────────────────────")

    # Keys workflow references as secrets that are missing from .env (no local fallback)
    for key in sorted(workflow_refs - CI_ONLY_KEYS):
        if key not in env_keys:
            issues.append(f"WARN  {key}: workflow needs it but not in .env")

    # Keys in .env + workflow but missing from GitHub Secrets → CI will break
    if gh_secrets is not None:
        for key in sorted(env_keys):
            if key in workflow_refs and key not in gh_secrets:
                issues.append(f"FAIL  {key}: in .env + workflow but MISSING from GitHub Secrets")

    # Keys in .env not referenced in workflow (possibly forgotten)
    for key in sorted(env_keys - workflow_refs):
        issues.append(f"INFO  {key}: in .env but not referenced in workflow")

    return _print_result(issues)


def audit_ci() -> int:
    """
    CI mode: verify all secrets referenced in workflow are present as env vars.
    In GitHub Actions, workflow env: blocks inject secrets as environment variables.
    """
    _header("Credential Consistency Audit — CI Mode")

    workflow_refs = _load_workflow_secret_refs()
    expected = workflow_refs - CI_ONLY_KEYS

    print(f"\n[1] Expected from workflow:  {sorted(expected)}")
    issues: list[str] = []
    print("\n── Env Var Presence Check ────────────────────────────────")

    for key in sorted(expected):
        val = os.environ.get(key, "")
        if not val:
            issues.append(f"FAIL  {key}: referenced in workflow env: but empty/missing in environment")
        else:
            print(f"  OK    {key}: present ({len(val)} chars)")

    return _print_result(issues)


def _print_result(issues: list[str]) -> int:
    if not issues:
        print("  OK — All environments consistent")
        print("=" * 60)
        print("AUDIT: PASS")
        return 0

    for issue in issues:
        print(f"  {issue}")

    fail_count = sum(1 for i in issues if i.startswith("FAIL"))
    warn_count = sum(1 for i in issues if i.startswith("WARN"))
    info_count = sum(1 for i in issues if i.startswith("INFO"))
    print("=" * 60)

    if fail_count > 0:
        print(f"AUDIT: FAIL — {fail_count} critical, {warn_count} warnings, {info_count} info")
        return 1
    print(f"AUDIT: WARN — {warn_count} warnings, {info_count} info (no critical failures)")
    return 0


if __name__ == "__main__":
    if "--ci" in sys.argv:
        sys.exit(audit_ci())
    check_gh = "--no-gh" not in sys.argv
    sys.exit(audit_local(check_gh=check_gh))
