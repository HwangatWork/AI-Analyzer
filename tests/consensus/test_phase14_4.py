# -*- coding: utf-8 -*-
"""Phase 14-4 unit tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.consensus.global_ib_news import (  # noqa: E402
    canonicalize_ib, _normalize_korean_money,
    IB_NAME_ALIASES, CANONICAL_IBS, load_manual_targets,
    merge_named_global_ib, _try_extract_report_date,
    _assign_confidence, _dedupe_entries,
)
from tools.consensus.analyze_snapshot import analyze  # noqa: E402


# ---------- canonicalize ----------

def test_canonicalize_jpm_aliases():
    assert canonicalize_ib("JP모건") == "JPMorgan"
    assert canonicalize_ib("JPMorgan") == "JPMorgan"
    assert canonicalize_ib("제이피모간") == "JPMorgan"


def test_canonicalize_goldman_aliases():
    assert canonicalize_ib("골드만삭스") == "Goldman Sachs"
    assert canonicalize_ib("Goldman Sachs") == "Goldman Sachs"


def test_canonicalize_unknown_returns_none():
    assert canonicalize_ib("unknown_firm") is None
    assert canonicalize_ib("") is None
    assert canonicalize_ib(None) is None


def test_canonicalize_covers_14_ibs():
    """At least 14 canonical IBs should be present."""
    assert len(CANONICAL_IBS) >= 14
    assert "JPMorgan" in CANONICAL_IBS
    assert "Goldman Sachs" in CANONICAL_IBS
    assert "Morgan Stanley" in CANONICAL_IBS
    assert "CLSA" in CANONICAL_IBS


# ---------- number normalization ----------

def test_normalize_man_shorthand():
    assert _normalize_korean_money("24만") == 240_000
    assert _normalize_korean_money("21만5375") == 215_375
    assert _normalize_korean_money("21만 5375") == 215_375


def test_normalize_comma_separated():
    assert _normalize_korean_money("215,375") == 215_375
    assert _normalize_korean_money("4,200,000") == 4_200_000


def test_normalize_decimal_man():
    assert _normalize_korean_money("4.2만") == 42_000
    assert _normalize_korean_money("24.5만") == 245_000


def test_normalize_handles_won_suffix():
    assert _normalize_korean_money("24만원") == 240_000
    assert _normalize_korean_money("215,375원") == 215_375


def test_normalize_invalid_returns_none():
    assert _normalize_korean_money("abc") is None
    assert _normalize_korean_money("") is None


# ---------- report_date extraction ----------

def test_report_date_from_hankyung_url():
    assert _try_extract_report_date(
        "https://www.hankyung.com/article/202606246047g"
    ) == "2026-06-24"


def test_report_date_handles_missing():
    assert _try_extract_report_date("https://example.com/foo") is None


# ---------- dedupe + confidence ----------

def test_dedupe_collapses_repeats():
    entries = [
        {"firm": "JPMorgan", "target_price": 240_000, "report_date": "2026-02-04",
         "source_url": "url1", "extraction_method": "news_regex",
         "proximity_chars": 26},
        {"firm": "JPMorgan", "target_price": 240_000, "report_date": "2026-02-04",
         "source_url": "url2", "extraction_method": "news_regex",
         "proximity_chars": 26},
        {"firm": "JPMorgan", "target_price": 280_000, "report_date": "2026-03-01",
         "source_url": "url3", "extraction_method": "news_regex",
         "proximity_chars": 30},
    ]
    deduped = _dedupe_entries(entries)
    assert len(deduped) == 2  # two distinct (target, date) combos
    first = next(d for d in deduped if d["target_price"] == 240_000)
    assert first["source_count"] == 2


def test_confidence_high_requires_two_sources():
    e = {"extraction_method": "news_regex", "proximity_chars": 50,
         "source_count": 2}
    assert _assign_confidence(e) == "high"


def test_confidence_medium_for_single_source():
    e = {"extraction_method": "news_regex", "proximity_chars": 50,
         "source_count": 1}
    assert _assign_confidence(e) == "medium"


def test_confidence_low_for_far_proximity():
    e = {"extraction_method": "news_regex", "proximity_chars": 250,
         "source_count": 1}
    assert _assign_confidence(e) == "low"


def test_confidence_user_verified_for_manual():
    e = {"extraction_method": "manual", "proximity_chars": 999}
    assert _assign_confidence(e) == "user_verified"


# ---------- manual targets loader ----------

def test_load_manual_targets_missing_file(tmp_path):
    result = load_manual_targets("000660",
                                   path=str(tmp_path / "missing.json"))
    assert result == []


def test_load_manual_targets_unknown_firm_filtered(tmp_path):
    p = tmp_path / "manual.json"
    p.write_text(json.dumps({
        "000660": [
            {"firm": "JPMorgan", "target_price": 4_200_000, "currency": "KRW",
             "report_date": "2026-06-15", "source": "manual_pdf"},
            {"firm": "MadeUpBank", "target_price": 9_999_999, "currency": "KRW",
             "report_date": "2026-06-15", "source": "manual_pdf"},
        ]
    }), encoding="utf-8")
    result = load_manual_targets("000660", path=str(p))
    assert len(result) == 1
    assert result[0]["firm"] == "JPMorgan"
    assert result[0]["confidence"] == "user_verified"


def test_load_manual_targets_negative_price_filtered(tmp_path):
    p = tmp_path / "manual.json"
    p.write_text(json.dumps({
        "000660": [
            {"firm": "JPMorgan", "target_price": -1000, "currency": "KRW",
             "report_date": "2026-06-15", "source": "manual_pdf"},
        ]
    }), encoding="utf-8")
    result = load_manual_targets("000660", path=str(p))
    assert result == []


# ---------- merge precedence ----------

def test_merge_manual_overrides_news():
    news = [
        {"firm": "JPMorgan", "target_price": 247_000, "report_date": "2026-02-04",
         "confidence": "medium", "extraction_method": "news_regex"},
    ]
    manual = [
        {"firm": "JPMorgan", "target_price": 4_200_000, "report_date": "2026-06-15",
         "confidence": "user_verified", "extraction_method": "manual"},
    ]
    merged = merge_named_global_ib(news, manual)
    assert len(merged) == 1
    assert merged[0]["target_price"] == 4_200_000
    assert merged[0]["confidence"] == "user_verified"


def test_merge_distinct_firms_kept():
    news = [
        {"firm": "JPMorgan", "target_price": 247_000, "report_date": "2026-02-04",
         "confidence": "medium", "extraction_method": "news_regex"},
    ]
    manual = [
        {"firm": "Goldman Sachs", "target_price": 4_500_000, "report_date": "2026-06-15",
         "confidence": "user_verified", "extraction_method": "manual"},
    ]
    merged = merge_named_global_ib(news, manual)
    assert len(merged) == 2


def test_merge_marks_stale():
    """Entries older than 60 days from today are flagged is_stale."""
    import datetime as _dt
    old = (_dt.date.today() - _dt.timedelta(days=80)).isoformat()
    news = [
        {"firm": "JPMorgan", "target_price": 247_000, "report_date": old,
         "confidence": "medium", "extraction_method": "news_regex"},
    ]
    merged = merge_named_global_ib(news, [])
    assert merged[0]["is_stale"] is True


# ---------- Q5 integration ----------

def test_q5_named_partial_when_n_equals_1():
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083, "target_price_change_1m_pct": 28.61,
        "estimates": {}, "target_price_series": [], "parser_warnings": [],
        "global_ib": {"found": True, "n_analysts": 37, "target_mean": 3_105_259.0},
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
        "global_ib_named": [
            {"firm": "JPMorgan", "target_price": 4_200_000,
             "confidence": "user_verified", "extraction_method": "manual"},
        ],
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q5_global_vs_domestic"] == "GLOBAL_NAMED_PARTIAL"


def test_q5_aligned_by_named_global_ib_when_two_high_conf():
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083, "target_price_change_1m_pct": 28.61,
        "estimates": {}, "target_price_series": [], "parser_warnings": [],
        "global_ib": {"found": True, "n_analysts": 37, "target_mean": 3_105_259.0},
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
        "global_ib_named": [
            {"firm": "JPMorgan", "target_price": 4_200_000,
             "confidence": "user_verified", "extraction_method": "manual"},
            {"firm": "Goldman Sachs", "target_price": 4_000_000,
             "confidence": "user_verified", "extraction_method": "manual"},
        ],
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    assert out["answers"]["Q5_global_vs_domestic"] == "ALIGNED_BY_NAMED_GLOBAL_IB"
    details = out["answers"]["Q5_details"]
    assert details["per_firm_jpm_gs_available"] is True
    assert "JPMorgan" in details["firms_named"]
    assert "Goldman Sachs" in details["firms_named"]


def test_q5_falls_back_to_phase14_3_when_named_low_confidence():
    """All medium-confidence named entries should NOT promote to ALIGNED_BY_NAMED."""
    parsed = {
        "investment_opinion": 4.0, "n_analysts": 24,
        "latest_target_price": 3_177_083, "target_price_change_1m_pct": 28.61,
        "estimates": {}, "target_price_series": [], "parser_warnings": [],
        "global_ib": {"found": True, "n_analysts": 37, "target_mean": 3_105_259.0},
        "per_firm_targets": {"n_firms": 25, "mean_target": 3_106_000.0},
        "global_ib_named": [
            {"firm": "JPMorgan", "target_price": 247_000,
             "confidence": "medium", "extraction_method": "news_regex"},
            {"firm": "Goldman Sachs", "target_price": 260_000,
             "confidence": "medium", "extraction_method": "news_regex"},
        ],
    }
    out = analyze(parsed, ticker="000660", company="SK hynix")
    # Should NOT be ALIGNED_BY_NAMED_GLOBAL_IB; should be GLOBAL_NAMED_PARTIAL
    # because N=2 but neither is high/user_verified
    q5 = out["answers"]["Q5_global_vs_domestic"]
    assert q5 != "ALIGNED_BY_NAMED_GLOBAL_IB"


# ---------- IB alias round-trip (X18 mirror) ----------

def test_every_alias_round_trips_to_a_known_canonical():
    for alias in IB_NAME_ALIASES:
        canon = canonicalize_ib(alias)
        assert canon is not None, f"alias {alias} -> None"
        assert canon in IB_NAME_ALIASES, (
            f"canonical {canon} for alias {alias} not in IB_NAME_ALIASES"
        )
