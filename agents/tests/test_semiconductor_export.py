# -*- coding: utf-8 -*-
"""
REQ-KITA-001 회귀 테스트: 관세청 반도체 수출 데이터 (5개)

T-SEM-1: fetch_customs_semiconductor() — CUSTOMS_API_KEY 없으면 빈 DataFrame 반환 (graceful skip)
T-SEM-2: _verify_semiconductor_dc() — DC-1 FAIL when file missing
T-SEM-3: _verify_semiconductor_dc() — DC-3 FAIL when row count < 12
T-SEM-4: _verify_semiconductor_dc() — DC-5 FAIL when newest row > 45 days old
T-SEM-5: fetch_customs_semiconductor() 반환 DataFrame 필수 컬럼 존재 확인 (mock 환경)
"""
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import utf8_setup  # noqa: F401

from run_data_agent_v2 import fetch_customs_semiconductor, _verify_semiconductor_dc


# ── T-SEM-1 ───────────────────────────────────────────────────────────────

def test_T_SEM_1_no_key_returns_empty():
    """T-SEM-1: CUSTOMS_API_KEY 없으면 빈 DataFrame 반환 (graceful skip)."""
    with patch.dict(os.environ, {}, clear=False):
        env = os.environ.copy()
        env.pop("CUSTOMS_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            df = fetch_customs_semiconductor()
    assert isinstance(df, pd.DataFrame), "T-SEM-1 FAIL: 반환값이 DataFrame 아님"
    assert df.empty, "T-SEM-1 FAIL: 키 없는데 빈 DataFrame 아님"


# ── T-SEM-2 ───────────────────────────────────────────────────────────────

def test_T_SEM_2_dc1_fail_file_missing(tmp_path):
    """T-SEM-2: DC-1 FAIL — 파일 미존재 시 sys.exit(1)."""
    missing = str(tmp_path / "SEMICONDUCTOR_EXPORT.parquet")
    with pytest.raises(SystemExit) as exc_info:
        _verify_semiconductor_dc(missing)
    assert exc_info.value.code == 1, "T-SEM-2 FAIL: exit code != 1"


# ── T-SEM-3 ───────────────────────────────────────────────────────────────

def test_T_SEM_3_dc3_fail_row_count_low(tmp_path):
    """T-SEM-3: DC-3 FAIL — row count < 12 시 sys.exit(1)."""
    path = tmp_path / "SEMICONDUCTOR_EXPORT.parquet"
    # 11행 (12 미만)
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=11, freq="MS"),
        "hs_code": "8542",
        "export_usd": [1000.0] * 11,
        "import_usd": [500.0] * 11,
        "unit": "USD_thousand",
    })
    df.to_parquet(path, index=False)
    with pytest.raises(SystemExit) as exc_info:
        _verify_semiconductor_dc(str(path))
    assert exc_info.value.code == 1, "T-SEM-3 FAIL: exit code != 1"


# ── T-SEM-4 ───────────────────────────────────────────────────────────────

def test_T_SEM_4_dc5_fail_stale_data(tmp_path):
    """T-SEM-4: DC-5 FAIL — 최신 행이 45일 초과 시 sys.exit(1)."""
    path = tmp_path / "SEMICONDUCTOR_EXPORT.parquet"
    stale_end = datetime.now() - timedelta(days=60)
    df = pd.DataFrame({
        "date": pd.date_range(end=stale_end, periods=12, freq="MS"),
        "hs_code": "8542",
        "export_usd": [1000.0] * 12,
        "import_usd": [500.0] * 12,
        "unit": "USD_thousand",
    })
    df.to_parquet(path, index=False)
    with pytest.raises(SystemExit) as exc_info:
        _verify_semiconductor_dc(str(path))
    assert exc_info.value.code == 1, "T-SEM-4 FAIL: exit code != 1"


# ── T-SEM-5 ───────────────────────────────────────────────────────────────

def test_T_SEM_5_required_columns(monkeypatch):
    """T-SEM-5: fetch_customs_semiconductor() 반환 DataFrame 필수 컬럼 확인 (mock XML API).

    구현이 XML 파싱을 사용하므로 resp.text에 유효한 XML을 반환.
    priodTitle='총계' 항목 포함 → 월별 합계로 인식됨.
    """
    required_cols = {"date", "hs_code", "export_usd", "import_usd", "unit"}

    MOCK_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<response><header><resultCode>00</resultCode><resultMsg>정상서비스.</resultMsg></header>"
        "<body><items>"
        "<item><expUsdAmt>12345</expUsdAmt><impUsdAmt>6789</impUsdAmt><priodTitle>총계</priodTitle></item>"
        "</items></body></response>"
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = MOCK_XML

    monkeypatch.setenv("CUSTOMS_API_KEY", "test_key_dummy")

    import httpx
    with patch.object(httpx, "get", return_value=mock_response):
        df = fetch_customs_semiconductor()

    assert not df.empty, "T-SEM-5 FAIL: mock API인데 빈 DataFrame"
    missing = required_cols - set(df.columns)
    assert not missing, f"T-SEM-5 FAIL: 필수 컬럼 누락 {missing}"
