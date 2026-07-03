# -*- coding: utf-8 -*-
"""Phase Ops-1 (2026-07-04) — GitHub Actions workflow 분리 회귀 test.

배경:
  기존 `.github/workflows/deploy-dashboard.yml` 은 pipeline 실행 job 과 pages 배포 job 을
  `concurrency: pages` 그룹으로 묶어, 사용자 push 진행 중 09:10 KST 스케줄이 skip 되는
  사고 발생 (2026-06-26, 07-01, 07-03, 07-04 실측).

  옵션 C 로 두 workflow 를 완전 분리했다:
    - run-pipeline.yml   → concurrency: pipeline-schedule
    - pages-deploy.yml   → concurrency: pages
    - deploy-dashboard.yml 은 폐기.

  이 test 는 분리가 유지되고 두 파일의 계약이 지켜지는지 검증한다.
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WF_DIR = REPO_ROOT / ".github" / "workflows"
RUN_PIPELINE = WF_DIR / "run-pipeline.yml"
PAGES_DEPLOY = WF_DIR / "pages-deploy.yml"
LEGACY = WF_DIR / "deploy-dashboard.yml"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _trigger(doc: dict) -> dict:
    """YAML 1.1 은 'on' 을 boolean True 로 파싱한다. 두 키 모두 대응."""
    if True in doc:
        return doc[True]
    return doc.get("on", {})


# ─────────────────────────────────────────────────────────────────
# T-WS-1: run-pipeline.yml 파싱 + 필수 필드
# ─────────────────────────────────────────────────────────────────
def test_T_WS_1_run_pipeline_parses_and_has_required_fields():
    assert RUN_PIPELINE.exists(), "run-pipeline.yml missing"
    doc = _load(RUN_PIPELINE)
    assert "name" in doc
    trig = _trigger(doc)
    assert "schedule" in trig, "run-pipeline must have schedule trigger"
    assert "workflow_dispatch" in trig, "run-pipeline must allow manual dispatch"
    assert "jobs" in doc
    assert "concurrency" in doc


# ─────────────────────────────────────────────────────────────────
# T-WS-2: pages-deploy.yml 파싱 + 필수 필드
# ─────────────────────────────────────────────────────────────────
def test_T_WS_2_pages_deploy_parses_and_has_required_fields():
    assert PAGES_DEPLOY.exists(), "pages-deploy.yml missing"
    doc = _load(PAGES_DEPLOY)
    assert "name" in doc
    trig = _trigger(doc)
    assert "push" in trig, "pages-deploy must be push-triggered"
    assert "workflow_dispatch" in trig
    assert "jobs" in doc
    assert "concurrency" in doc


# ─────────────────────────────────────────────────────────────────
# T-WS-3: run-pipeline concurrency group != 'pages'
# ─────────────────────────────────────────────────────────────────
def test_T_WS_3_run_pipeline_concurrency_not_pages():
    doc = _load(RUN_PIPELINE)
    grp = doc["concurrency"]["group"]
    assert grp != "pages", (
        f"run-pipeline must NOT share 'pages' concurrency (got {grp!r}) — "
        "would recreate the very race the split eliminated"
    )
    assert grp == "pipeline-schedule"


# ─────────────────────────────────────────────────────────────────
# T-WS-4: pages-deploy concurrency group == 'pages'
# ─────────────────────────────────────────────────────────────────
def test_T_WS_4_pages_deploy_concurrency_pages():
    doc = _load(PAGES_DEPLOY)
    assert doc["concurrency"]["group"] == "pages"


# ─────────────────────────────────────────────────────────────────
# T-WS-5: run-pipeline cron 정확 ('10 0 * * *')
# ─────────────────────────────────────────────────────────────────
def test_T_WS_5_run_pipeline_cron_exact():
    doc = _load(RUN_PIPELINE)
    trig = _trigger(doc)
    schedules = trig["schedule"]
    crons = [s["cron"] for s in schedules]
    assert "10 0 * * *" in crons, f"expected '10 0 * * *', got {crons}"


# ─────────────────────────────────────────────────────────────────
# T-WS-6: 두 workflow 가 참조하는 핵심 secrets 일관성
# 파이프라인이 필요로 하는 8개 secret + Pages 배포 job 의 permissions.
# ─────────────────────────────────────────────────────────────────
def test_T_WS_6_secrets_consistency():
    text = RUN_PIPELINE.read_text(encoding="utf-8")
    required = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "FRED_API_KEY",
        "KRX_ID",
        "KRX_PW",
        "ECOS_API_KEY",
        "ANTHROPIC_API_KEY",
        "CUSTOMS_API_KEY",
        "NOTION_TOKEN",
    ]
    for key in required:
        assert f"secrets.{key}" in text, (
            f"run-pipeline.yml missing secret reference: {key}"
        )

    # Pages 배포는 secret 을 안 쓰지만 permissions 는 필수
    doc = _load(PAGES_DEPLOY)
    deploy_job = doc["jobs"]["deploy"]
    perms = deploy_job["permissions"]
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"


# ─────────────────────────────────────────────────────────────────
# T-WS-7: legacy deploy-dashboard.yml 존재하지 않음 (폐기 확인)
# ─────────────────────────────────────────────────────────────────
def test_T_WS_7_legacy_deploy_dashboard_removed():
    assert not LEGACY.exists(), (
        "deploy-dashboard.yml must be removed after Phase Ops-1 split — "
        "leaving it in place would cause double schedule firing"
    )
