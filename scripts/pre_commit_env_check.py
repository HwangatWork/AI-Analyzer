# -*- coding: utf-8 -*-
"""
scripts/pre_commit_env_check.py - Git pre-commit hook for workflow credential consistency.

Triggered when deploy-dashboard.yml is staged for commit.
Runs audit_env_secrets.py --no-gh and blocks commit on FAIL.

Install via: python scripts/install_hooks.py
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _staged_files() -> list[str]:
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=str(BASE_DIR), timeout=10,
        )
        return r.stdout.strip().splitlines()
    except Exception:
        return []


def main() -> int:
    staged = _staged_files()
    workflow_staged = any(".github/workflows" in f or "deploy-dashboard.yml" in f for f in staged)

    if not workflow_staged:
        return 0  # nothing credential-related staged, allow commit

    print("[pre-commit] Workflow file staged - running credential consistency audit...")
    audit_script = BASE_DIR / "scripts" / "audit_env_secrets.py"
    if not audit_script.exists():
        print("[pre-commit] audit_env_secrets.py not found - skipping")
        return 0

    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(audit_script), "--no-gh"],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print("\n[pre-commit] BLOCKED - credential inconsistency detected.")
        print("  Fix the issues above, then re-run: git commit")
        return 1

    print("[pre-commit] Audit PASS - commit allowed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
