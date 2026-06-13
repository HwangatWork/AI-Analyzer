# -*- coding: utf-8 -*-
"""
REQ-SA4 Done Criteria 회귀 테스트
T-SA4-1: exit(1) when output file missing
T-SA4-2: exit(1) when output file empty
T-SA4-3: exit(1) when row count is 0
T-SA4-4: exit(0) when all conditions met
T-SA4-5: exit(1) when newest row older than 7 days
"""
import sys, os, subprocess, tempfile
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import pytest

# Import _verify_done_criteria from refresh_data (safe: module is now __main__-guarded)
sys.path.insert(0, str(Path(__file__).parent.parent))
from refresh_data import _verify_done_criteria, _PARTIAL_FAIL_FLAG


def _run_dc(output_path: str, date_col: str = "date", min_rows: int = 1,
            set_partial_flag: bool = False) -> int:
    """Run _verify_done_criteria in a subprocess, return exit code."""
    flag_path = str(_PARTIAL_FAIL_FLAG)
    if set_partial_flag:
        Path(flag_path).write_text("test_flag")
    else:
        if Path(flag_path).exists():
            Path(flag_path).unlink()

    code = (
        "import sys, os; sys.path.insert(0, r'" + str(Path(__file__).parent.parent) + "'); "
        "import pandas as pd; "
        "from refresh_data import _verify_done_criteria; "
        f"_verify_done_criteria({output_path!r}, {date_col!r}, {min_rows!r})"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, timeout=15,
    )
    # cleanup flag after test
    if Path(flag_path).exists():
        Path(flag_path).unlink()
    return result.returncode


def test_T_SA4_1_missing_file():
    """T-SA4-1: exit(1) when output file does not exist."""
    nonexistent = "/tmp/does_not_exist_sa4_test.parquet"
    exit_code = _run_dc(nonexistent)
    assert exit_code == 1, f"T-SA4-1 FAIL: expected exit(1) for missing file, got {exit_code}"


def test_T_SA4_2_empty_file():
    """T-SA4-2: exit(1) when output file is empty (0 bytes)."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    try:
        # Write empty file
        open(tmp_path, "w").close()
        exit_code = _run_dc(tmp_path)
        assert exit_code == 1, f"T-SA4-2 FAIL: expected exit(1) for empty file, got {exit_code}"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_T_SA4_3_zero_rows():
    """T-SA4-3: exit(1) when parquet has 0 rows (min_rows=1)."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    try:
        # Write parquet with 0 rows
        df_empty = pd.DataFrame({"date": pd.Series([], dtype="datetime64[ns]"),
                                  "value": pd.Series([], dtype=float)})
        df_empty.to_parquet(tmp_path, index=False)
        exit_code = _run_dc(tmp_path, min_rows=1)
        assert exit_code == 1, f"T-SA4-3 FAIL: expected exit(1) for 0 rows, got {exit_code}"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_T_SA4_4_all_pass():
    """T-SA4-4: exit(0) when file exists, non-empty, rows >= min, date fresh."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    try:
        # Write parquet with 100 fresh rows
        today = pd.Timestamp.now().normalize()
        dates = [today - pd.Timedelta(days=i) for i in range(100)]
        df = pd.DataFrame({"date": dates, "value": [50.0 + i * 0.1 for i in range(100)]})
        df.to_parquet(tmp_path, index=False)
        exit_code = _run_dc(tmp_path, min_rows=50)
        assert exit_code == 0, f"T-SA4-4 FAIL: expected exit(0) for valid file, got {exit_code}"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_T_SA4_5_stale_data():
    """T-SA4-5: exit(1) when newest row is older than 7 days."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    try:
        # Write parquet with newest date = 30 days ago
        old_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
        dates = [old_date - pd.Timedelta(days=i) for i in range(100)]
        df = pd.DataFrame({"date": dates, "value": [50.0 + i * 0.1 for i in range(100)]})
        df.to_parquet(tmp_path, index=False)
        exit_code = _run_dc(tmp_path, min_rows=50)
        assert exit_code == 1, f"T-SA4-5 FAIL: expected exit(1) for stale data, got {exit_code}"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
