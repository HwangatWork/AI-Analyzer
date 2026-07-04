# -*- coding: utf-8 -*-
"""Phase 14-0-C — snapshot_store unit tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.snapshot_store import (  # noqa: E402
    write_snapshot, load_snapshot, list_snapshots,
    verify_snapshot_integrity, detect_gaps, get_snapshot_batch,
    compute_pit_q1_change,
    SnapshotExistsError, QualityGateError, QUALITY_MIN,
)


def _valid_analysis(target=3_000_000, score=0.9):
    return {
        "answers": {"Q1_direction": "UP", "Q2_direction": "UP",
                     "Q3_direction": "UP", "Q4_quadrant": "TRUE_UPGRADE",
                     "Q5_global_vs_domestic": "GLOBAL_DATA_INSUFFICIENT"},
        "raw_inputs": {"latest_target_price": target},
        "data_quality": {"score": score, "components": {}},
        "meta_audit": {"kr_buy_bias_warning": True,
                        "kr_buy_bias_source": "t",
                        "point_in_time_status": "snapshot",
                        "point_in_time_note": "t",
                        "target_price_role": "sentiment_valuation_proxy",
                        "target_price_role_source": "t"},
    }


# ---------- write ----------

def test_write_creates_all_four_files(tmp_path):
    write_snapshot(
        ticker="TEST", parsed={"x": 1}, analysis=_valid_analysis(),
        report_md="# hi\n", date="2026-07-03", history_root=str(tmp_path),
    )
    d = tmp_path / "TEST" / "2026-07-03"
    for f in ("parsed.json", "analysis.json", "report.md", "manifest.json"):
        assert (d / f).exists(), f"{f} missing"


def test_write_manifest_has_all_shas(tmp_path):
    m = write_snapshot(
        ticker="TEST", parsed={"x": 1}, analysis=_valid_analysis(),
        report_md="# hi\n", date="2026-07-03", history_root=str(tmp_path),
    )
    assert set(m["files"].keys()) == {"parsed.json", "analysis.json", "report.md"}
    for sha in m["files"].values():
        assert len(sha) == 64
    assert len(m["top_sha256"]) == 64


def test_write_refuses_duplicate_without_force(tmp_path):
    write_snapshot(
        ticker="T", parsed={}, analysis=_valid_analysis(),
        report_md="# a\n", date="2026-07-03", history_root=str(tmp_path),
    )
    with pytest.raises(SnapshotExistsError):
        write_snapshot(
            ticker="T", parsed={}, analysis=_valid_analysis(),
            report_md="# b\n", date="2026-07-03", history_root=str(tmp_path),
        )


def test_write_allows_force(tmp_path):
    write_snapshot(
        ticker="T", parsed={}, analysis=_valid_analysis(),
        report_md="# a\n", date="2026-07-03", history_root=str(tmp_path),
    )
    m2 = write_snapshot(
        ticker="T", parsed={}, analysis=_valid_analysis(),
        report_md="# b\n", date="2026-07-03", history_root=str(tmp_path),
        force=True,
    )
    assert m2["top_sha256"] is not None


def test_write_refuses_below_quality(tmp_path):
    with pytest.raises(QualityGateError):
        write_snapshot(
            ticker="T", parsed={}, analysis=_valid_analysis(score=0.4),
            report_md="# a\n", date="2026-07-03", history_root=str(tmp_path),
        )


# ---------- read ----------

def test_load_returns_none_for_missing(tmp_path):
    assert load_snapshot("nope", "2026-07-03", history_root=str(tmp_path)) is None


def test_load_returns_full_dict(tmp_path):
    write_snapshot(
        ticker="T", parsed={"a": 1}, analysis=_valid_analysis(),
        report_md="# hi\n", date="2026-07-03", history_root=str(tmp_path),
    )
    snap = load_snapshot("T", "2026-07-03", history_root=str(tmp_path))
    assert snap["parsed"] == {"a": 1}
    assert snap["analysis"]["data_quality"]["score"] == 0.9
    assert snap["report_md"] == "# hi\n"
    assert snap["manifest"]["ticker"] == "T"


def test_list_snapshots_returns_ordered(tmp_path):
    for d in ("2026-07-05", "2026-07-01", "2026-07-03"):
        write_snapshot(ticker="T", parsed={}, analysis=_valid_analysis(),
                        report_md="# x\n", date=d, history_root=str(tmp_path))
    assert list_snapshots("T", history_root=str(tmp_path)) == [
        "2026-07-01", "2026-07-03", "2026-07-05",
    ]


def test_list_snapshots_empty_for_unknown_ticker(tmp_path):
    assert list_snapshots("nope", history_root=str(tmp_path)) == []


def test_batch_load(tmp_path):
    for t in ("A", "B"):
        write_snapshot(ticker=t, parsed={"who": t}, analysis=_valid_analysis(),
                        report_md="# x\n", date="2026-07-03",
                        history_root=str(tmp_path))
    batch = get_snapshot_batch(["A", "B", "C"], "2026-07-03",
                                 history_root=str(tmp_path))
    assert batch["A"]["parsed"] == {"who": "A"}
    assert batch["B"]["parsed"] == {"who": "B"}
    assert batch["C"] is None


# ---------- integrity ----------

def test_integrity_ok_on_clean_write(tmp_path):
    write_snapshot(ticker="T", parsed={}, analysis=_valid_analysis(),
                    report_md="# x\n", date="2026-07-03",
                    history_root=str(tmp_path))
    v = verify_snapshot_integrity("T", "2026-07-03",
                                    history_root=str(tmp_path))
    assert v["ok"] is True
    assert v["checked"] == 3
    assert v["mismatches"] == []


def test_integrity_detects_report_md_tamper(tmp_path):
    write_snapshot(ticker="T", parsed={}, analysis=_valid_analysis(),
                    report_md="# original\n", date="2026-07-03",
                    history_root=str(tmp_path))
    (tmp_path / "T" / "2026-07-03" / "report.md").write_text(
        "# TAMPERED\n", encoding="utf-8"
    )
    v = verify_snapshot_integrity("T", "2026-07-03",
                                    history_root=str(tmp_path))
    assert v["ok"] is False
    assert len(v["mismatches"]) >= 1
    assert any("report.md" in m for m in v["mismatches"])


def test_integrity_detects_analysis_json_tamper(tmp_path):
    write_snapshot(ticker="T", parsed={}, analysis=_valid_analysis(),
                    report_md="# x\n", date="2026-07-03",
                    history_root=str(tmp_path))
    (tmp_path / "T" / "2026-07-03" / "analysis.json").write_text(
        "{}\n", encoding="utf-8"
    )
    v = verify_snapshot_integrity("T", "2026-07-03",
                                    history_root=str(tmp_path))
    assert v["ok"] is False


# ---------- immutability across writes ----------

def test_prior_snapshot_unchanged_after_new_write(tmp_path):
    m1 = write_snapshot(ticker="T", parsed={"d": 1}, analysis=_valid_analysis(),
                         report_md="# d1\n", date="2026-07-01",
                         history_root=str(tmp_path))
    before = load_snapshot("T", "2026-07-01", history_root=str(tmp_path))
    write_snapshot(ticker="T", parsed={"d": 3}, analysis=_valid_analysis(),
                    report_md="# d3\n", date="2026-07-03",
                    history_root=str(tmp_path))
    after = load_snapshot("T", "2026-07-01", history_root=str(tmp_path))
    assert before == after
    assert m1["top_sha256"] == after["manifest"]["top_sha256"]


# ---------- gap detection ----------

def test_detect_gaps_flags_more_than_2_days():
    dates = ["2026-07-01", "2026-07-03", "2026-07-09"]
    gaps = detect_gaps(dates, max_gap_days=2)
    assert len(gaps) == 1
    assert gaps[0] == ("2026-07-03", "2026-07-09", 6)


def test_detect_no_gaps_within_threshold():
    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert detect_gaps(dates) == []


# ---------- PIT Q1 helper ----------

def test_pit_q1_returns_none_when_no_history(tmp_path):
    assert compute_pit_q1_change(
        "T", 3_000_000, history_root=str(tmp_path),
    ) is None


def test_pit_q1_returns_change_when_history_present(tmp_path):
    write_snapshot(
        ticker="T", parsed={}, analysis=_valid_analysis(target=2_500_000),
        report_md="# x\n", date="2026-05-01", history_root=str(tmp_path),
    )
    pit = compute_pit_q1_change(
        "T", current_target=3_100_000, reference_days=30,
        history_root=str(tmp_path),
    )
    assert pit is not None
    assert pit["source"] == "snapshot_pit_prior_day"
    assert pit["prior_target"] == 2_500_000
    assert pit["change_pct"] == pytest.approx((3_100_000 - 2_500_000) / 2_500_000 * 100)


# ---------- no destructive functions exposed ----------

def test_module_has_no_destructive_functions():
    from tools.consensus import snapshot_store as ss
    for name in dir(ss):
        low = name.lower()
        assert not low.startswith("delete_"), f"{name} exposed"
        assert not low.startswith("remove_"), f"{name} exposed"
        assert not low.startswith("edit_"), f"{name} exposed"
