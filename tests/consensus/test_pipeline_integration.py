# -*- coding: utf-8 -*-
"""End-to-end pipeline integration test (PM Agent).

Uses fixture HTML — NO network access. Asserts all four gates G1-G4
execute and produce artifacts in the expected paths.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.consensus_pipeline import run_pipeline  # noqa: E402


FIXTURE = (
    Path(__file__).parent / "fixtures" / "wisereport_000660_sample.html"
)


def test_fixture_mode_runs_end_to_end(tmp_path):
    r = run_pipeline(
        ticker="000660",
        out_dir=str(tmp_path),
        smoke=False,  # not required in fixture mode
        from_fixture=str(FIXTURE),
    )
    assert r["exit_code"] == 0
    # Artifacts exist
    assert r["parsed_json_path"]
    assert r["analysis_json_path"]
    assert r["report_md_path"]
    assert Path(r["parsed_json_path"]).exists()
    assert Path(r["analysis_json_path"]).exists()
    assert Path(r["report_md_path"]).exists()


def test_gates_all_evaluated(tmp_path):
    r = run_pipeline(
        ticker="000660",
        out_dir=str(tmp_path),
        smoke=False,
        from_fixture=str(FIXTURE),
    )
    gates = r["gate_results"]
    # G1 bypassed because fixture mode skips fetch
    assert gates["G1_robots_check"] == "BYPASSED_FIXTURE_MODE"
    # G2: integer count of fields parsed
    assert isinstance(gates["G2_parse_fields_present"], int)
    assert gates["G2_parse_fields_present"] >= 2
    # G3: a quadrant string
    assert isinstance(
        gates["G3_q4_classified_or_insufficient"], str
    )
    # G4: meta-audit labels boolean
    assert gates["G4_meta_audit_labels_present"] is True


def test_analysis_json_has_all_q_answers(tmp_path):
    r = run_pipeline(
        ticker="000660",
        out_dir=str(tmp_path),
        smoke=False,
        from_fixture=str(FIXTURE),
    )
    data = json.loads(
        Path(r["analysis_json_path"]).read_text(encoding="utf-8")
    )
    answers = data["answers"]
    for q in ("Q1_direction", "Q2_direction", "Q3_direction",
              "Q4_quadrant", "Q5_global_vs_domestic"):
        assert q in answers


def test_report_md_contains_kcmi_and_bradshaw(tmp_path):
    r = run_pipeline(
        ticker="000660",
        out_dir=str(tmp_path),
        smoke=False,
        from_fixture=str(FIXTURE),
    )
    text = Path(r["report_md_path"]).read_text(encoding="utf-8")
    assert "KCMI" in text
    assert "Bradshaw" in text
    assert "Ljungqvist" in text


def test_unknown_ticker_rejected(tmp_path):
    r = run_pipeline(
        ticker="999999",
        out_dir=str(tmp_path),
        smoke=False,
        from_fixture=str(FIXTURE),
    )
    assert r["exit_code"] == 1
    assert any("unknown_ticker" in e for e in r["errors"])


def test_fixture_missing_returns_invalid(tmp_path):
    r = run_pipeline(
        ticker="000660",
        out_dir=str(tmp_path),
        smoke=False,
        from_fixture=str(tmp_path / "does_not_exist.html"),
    )
    assert r["exit_code"] == 1
    assert any("fixture_read_failed" in e for e in r["errors"])
