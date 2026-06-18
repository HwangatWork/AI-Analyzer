# -*- coding: utf-8 -*-
"""
scripts/install_hooks.py — Install git hooks for this project.

Installs:
  .git/hooks/pre-commit → runs scripts/pre_commit_env_check.py

Run once after cloning:
  python scripts/install_hooks.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
GIT_HOOKS_DIR = BASE_DIR / ".git" / "hooks"
PRE_COMMIT_HOOK = GIT_HOOKS_DIR / "pre-commit"

HOOK_CONTENT = f"""#!/usr/bin/env python
# Auto-installed by scripts/install_hooks.py
import subprocess, sys
result = subprocess.run(
    [sys.executable, r"{BASE_DIR / 'scripts' / 'pre_commit_env_check.py'}"],
    cwd=r"{BASE_DIR}"
)
sys.exit(result.returncode)
"""


def main() -> int:
    if not GIT_HOOKS_DIR.exists():
        print(f"[install_hooks] .git/hooks not found at {GIT_HOOKS_DIR}")
        print("  Is this a git repository? Run: git init")
        return 1

    PRE_COMMIT_HOOK.write_text(HOOK_CONTENT, encoding="utf-8")
    try:
        import stat
        PRE_COMMIT_HOOK.chmod(PRE_COMMIT_HOOK.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass  # Windows doesn't use chmod the same way

    print(f"[install_hooks] Installed: {PRE_COMMIT_HOOK}")
    print("  pre-commit hook will block commits when deploy-dashboard.yml has credential inconsistencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
