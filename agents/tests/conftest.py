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
