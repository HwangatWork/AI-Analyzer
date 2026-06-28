# -*- coding: utf-8 -*-
# Exclude standalone DC scripts (test_dc_*.py) — they have module-level sys.exit
# and are run directly as scripts, not as pytest test cases.
collect_ignore = ["test_dc_data.py", "test_dc_stock.py", "test_dc_ui.py"]

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _block_pending_writes(monkeypatch):
    """FIX-G: pm_utils.register_pending는 BASE_DIR/pending_requests.json (절대경로) 직접 수정.
    여러 테스트가 pm_quality_checks()를 호출하며 실제 파일을 오염시킴. 전역 격리.
    ([[operational-lessons]] OL-6)
    """
    try:
        import pm_utils
        monkeypatch.setattr(pm_utils, "register_pending", lambda *a, **k: None)
    except ImportError:
        pass
    try:
        import pm_quality
        if hasattr(pm_quality, "register_pending"):
            monkeypatch.setattr(pm_quality, "register_pending", lambda *a, **k: None)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _block_telegram(monkeypatch):
    """pm_utils._tg_send 내부 urllib.request.urlopen 무효화 → 4 호출 모듈
    (pm_orchestrator/pm_quality/run_pm_agent/pm_utils) 의 `from pm_utils import _tg_send`
    별도 binding + 간접 채널 (_tg_step/_quality_alert) 모두 자동 차단.

    배경: audit-agent (2026-06-29) 가 catch — `monkeypatch.setattr(pm_utils, "_tg_send")`
    는 import binding 격리로 차단 불가. 네트워크 레벨 mock이 단일 지점 해결.

    예: test_T_64_4_check_repeat_failures_detects → _check_repeat_failures →
        _tg_send → urllib.request.urlopen (이전: 실제 Telegram 발송, 이후: no-op).
    """
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: None)
