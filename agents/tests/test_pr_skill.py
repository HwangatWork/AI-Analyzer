# -*- coding: utf-8 -*-
"""
/pr Peer Review Skill regression tests (T-PR-1 ~ T-PR-9)

T-PR-1: SKILL.md exists + frontmatter has name/description/argument-hint
T-PR-2: critic-agent.md frontmatter valid (name == critic-agent, tools present)
T-PR-3: pr_round_response.schema.json is a valid Draft 2020-12 JSON Schema
T-PR-4: settings.json registers pr_schema_check hook with critic-agent in matcher
T-PR-5: pr_schema_check.py — valid round-1 JSON → exit 0 (subprocess)
T-PR-6: pr_schema_check.py — missing required field → exit 2 (subprocess)
T-PR-7: pr_schema_check.py — no .active flag → exit 0 (gate off)
T-PR-8: SKILL.md body keeps spec keywords (anti-regression)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "pr" / "SKILL.md"
_CRITIC_MD = _REPO_ROOT / ".claude" / "agents" / "critic-agent.md"
_SCHEMA = _REPO_ROOT / "schemas" / "pr_round_response.schema.json"
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "pr_schema_check.py"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"
_ACTIVE_FLAG = _REPO_ROOT / "output" / "peer_review_pr" / ".active"


def _frontmatter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{md_path.name}: frontmatter block missing"
    fm = {}
    for line in m.group(1).splitlines():
        if re.match(r"^[A-Za-z_-]+:", line):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def _run_hook(stdin_payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(stdin_payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8",
        timeout=30, cwd=_REPO_ROOT,
    )


@pytest.fixture
def pr_flag_on():
    """Create .active flag for the hook gate; restore prior state afterward."""
    _ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    had = _ACTIVE_FLAG.exists()
    saved = _ACTIVE_FLAG.read_text(encoding="utf-8") if had else None
    _ACTIVE_FLAG.write_text("pytest-pr-skill", encoding="utf-8")
    yield
    if saved is not None:
        _ACTIVE_FLAG.write_text(saved, encoding="utf-8")
    elif _ACTIVE_FLAG.exists():
        _ACTIVE_FLAG.unlink()


@pytest.fixture
def pr_flag_off():
    """Ensure .active flag absent; restore prior state afterward."""
    had = _ACTIVE_FLAG.exists()
    saved = _ACTIVE_FLAG.read_text(encoding="utf-8") if had else None
    if had:
        _ACTIVE_FLAG.unlink()
    yield
    if saved is not None:
        _ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVE_FLAG.write_text(saved, encoding="utf-8")


_VALID_R1 = {
    "agent": "critic-agent",
    "round": 1,
    "stance": "conditional",
    "key_points": ["walk-forward split rationale absent from code (no file:line)"],
    "risks": ["p-value unreliable below 30 samples", "no lookahead-leak test exists"],
    "consensus_ready": False,
}


def test_T_PR_1_skill_md_frontmatter():
    assert _SKILL_MD.exists(), f"{_SKILL_MD} missing"
    fm = _frontmatter(_SKILL_MD)
    assert fm.get("name") == "pr", f"name != pr — {fm.get('name')!r}"
    assert fm.get("description"), "description missing"
    assert "argument-hint" in fm, "argument-hint missing"
    assert fm.get("disable-model-invocation") == "true", \
        "disable-model-invocation must be true (user-invoked only)"


def test_T_PR_2_critic_agent_frontmatter():
    assert _CRITIC_MD.exists(), f"{_CRITIC_MD} missing"
    fm = _frontmatter(_CRITIC_MD)
    assert fm.get("name") == "critic-agent", f"name != critic-agent — {fm.get('name')!r}"
    tools = fm.get("tools", "")
    for t in ("Read", "Grep"):
        assert t in tools, f"critic-agent tools missing {t}: {tools!r}"


def test_T_PR_3_schema_is_valid():
    from jsonschema import Draft202012Validator
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    v.validate(_VALID_R1)  # round-1 fixture must pass
    # round 2 without feedback_addressed must fail
    r2 = dict(_VALID_R1, round=2)
    errors = list(v.iter_errors(r2))
    assert errors, "round-2 without feedback_addressed must be rejected"


def test_T_PR_4_settings_hook_registered():
    cfg = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    entries = cfg.get("hooks", {}).get("SubagentStop", [])
    pr_entries = [
        e for e in entries
        if any("pr_schema_check.py" in " ".join(h.get("args", []) or [h.get("command", "")])
               for h in e.get("hooks", []))
    ]
    assert pr_entries, "pr_schema_check.py not registered in SubagentStop hooks"
    matcher = pr_entries[0].get("matcher", "")
    assert "critic" in matcher, f"matcher must include critic-agent: {matcher!r}"


def test_T_PR_5_hook_valid_json_exit0(pr_flag_on):
    msg = "Round result:\n```json\n" + json.dumps(_VALID_R1) + "\n```"
    proc = _run_hook({"agent_type": "critic-agent", "last_assistant_message": msg})
    assert proc.returncode == 0, \
        f"exit {proc.returncode} (expected 0); stderr={proc.stderr[:300]}"
    assert "PR schema PASS" in proc.stdout, f"success context missing: {proc.stdout[:200]}"


def test_T_PR_6_hook_invalid_json_exit2(pr_flag_on):
    bad = {k: v for k, v in _VALID_R1.items() if k != "stance"}
    msg = "```json\n" + json.dumps(bad) + "\n```"
    proc = _run_hook({"agent_type": "critic-agent", "last_assistant_message": msg})
    assert proc.returncode == 2, \
        f"exit {proc.returncode} (expected 2); stdout={proc.stdout[:200]}"
    assert "FAIL" in proc.stderr, f"stderr feedback missing: {proc.stderr[:200]}"


def test_T_PR_7_hook_gate_off_exit0(pr_flag_off):
    bad = {"totally": "unrelated"}
    msg = "```json\n" + json.dumps(bad) + "\n```"
    proc = _run_hook({"agent_type": "critic-agent", "last_assistant_message": msg})
    assert proc.returncode == 0, \
        f"gate off must exit 0 — got {proc.returncode}; stderr={proc.stderr[:200]}"


def test_T_PR_8_skill_md_spec_keywords():
    text = _SKILL_MD.read_text(encoding="utf-8")
    for keyword in (
        "general-purpose",            # persona prohibition
        "5 rounds total",             # round cap
        "pm-agent",                   # mandatory PM call
        "critic-agent",               # mandatory critic participation
        "feedback_addressed",         # mutual feedback enforcement
        "pr_round_response.schema.json",
        "agent_activity.jsonl",       # invocation evidence cross-check
        "history.jsonl",              # permanent history
    ):
        assert keyword in text, f"SKILL.md missing spec keyword: {keyword!r}"


def test_T_PR_9_final_report_standard_keywords():
    """PR-REPORT-STANDARD-1: SKILL.md holds the final-report standard; CLAUDE.md points to it."""
    skill = _SKILL_MD.read_text(encoding="utf-8")
    for keyword in (
        "Final Report Standard & Self-Improving Review Loop",
        "executive_summary",
        "fix_request_candidates",
        "self_improvement_findings",
        "pass_disguise_detection",
        "deterministic",
        "HOLD",
        "N/A —",                      # no-omission rule for inapplicable sections
        "Never auto-implement",       # self-improvement loop safety
        "pending_requests.json",      # candidate registration target
    ):
        assert keyword in skill, f"SKILL.md missing report-standard keyword: {keyword!r}"

    claude_md = (_REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Final Report Standard" in claude_md, \
        "CLAUDE.md must point to the /pr Final Report Standard"
    assert "Final Report Standard & Self-Improving Review Loop" in claude_md, \
        "CLAUDE.md pointer must name the SKILL.md section"
