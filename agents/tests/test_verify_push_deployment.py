# -*- coding: utf-8 -*-
"""
Phase Ops-2 회귀 (2026-07-04): verify_push_deployment 공용 검증기.

라운드 16 directive 준수: 매 push 후 primary deploy 만 확인하는 위장 패턴 차단.

Tests:
T-VPD-1: summarize_runs — success / failure / other 분류
T-VPD-2: check_freshness — mtime 기반 stale 감지
T-VPD-3: check_freshness — generated_at json 우선 사용
T-VPD-4: check_freshness — 파일 부재 감지
T-VPD-5: verify() 종합 — 모든 workflow success + Pages OK + fresh → exit 0
T-VPD-6: verify() — workflow failure 시 exit 2 + failures 리스트에 포함
T-VPD-7: verify() — freshness 실패만 있으면 exit 5
T-VPD-8: render_human — 성공/실패 시각화 문자열
T-VPD-9: _extract_ts — 다양한 timestamp 포맷 파싱
T-VPD-10: main --sha 짧으면 EXIT_INVALID_ARGS
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "verify_push_deployment.py"


@pytest.fixture(scope="module")
def vpd():
    spec = importlib.util.spec_from_file_location("verify_push_deployment", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_T_VPD_1_summarize_runs(vpd):
    runs = [
        {"name": "A", "conclusion": "success", "status": "completed",
         "html_url": "https://x/a", "id": 1},
        {"name": "B", "conclusion": "failure", "status": "completed",
         "html_url": "https://x/b", "id": 2},
        {"name": "C", "conclusion": "cancelled", "status": "completed",
         "html_url": "https://x/c", "id": 3},
        {"name": "D", "conclusion": None, "status": "in_progress",
         "html_url": "https://x/d", "id": 4},
    ]
    s = vpd.summarize_runs(runs)
    assert s["total"] == 4
    assert s["success_count"] == 1
    assert s["failure_count"] == 2  # failure + cancelled
    assert s["other_count"] == 1


def test_T_VPD_2_freshness_mtime_stale(vpd, tmp_path):
    p = tmp_path / "output" / "test.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    # 오래된 mtime 강제 설정
    import os
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    os.utime(p, (old.timestamp(), old.timestamp()))
    ok, results = vpd.check_freshness(
        ["output/test.json"], tmp_path, max_hours=24,
    )
    assert ok is False
    assert results[0]["fresh"] is False
    assert "stale" in results[0]["reason"]


def test_T_VPD_3_freshness_generated_at_wins(vpd, tmp_path):
    """generated_at 필드가 mtime 대신 사용됨."""
    p = tmp_path / "output" / "test.json"
    p.parent.mkdir(parents=True)
    # generated_at 은 fresh, mtime 은 stale
    fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    p.write_text(json.dumps({"generated_at": fresh_ts}), encoding="utf-8")
    import os
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    os.utime(p, (old.timestamp(), old.timestamp()))
    ok, results = vpd.check_freshness(
        ["output/test.json"], tmp_path, max_hours=24,
    )
    assert ok is True
    assert results[0]["fresh"] is True
    assert results[0]["source"] == "json.generated_at"


def test_T_VPD_4_freshness_missing_file(vpd, tmp_path):
    ok, results = vpd.check_freshness(
        ["output/nonexistent.json"], tmp_path, max_hours=24,
    )
    assert ok is False
    assert results[0]["exists"] is False
    assert results[0]["reason"] == "missing"


def test_T_VPD_5_verify_all_pass(vpd, tmp_path, monkeypatch):
    """모든 workflow success + Pages OK + fresh → exit 0."""
    # fresh 파일 준비
    p = tmp_path / "output" / "final_results.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat()
    }), encoding="utf-8")

    monkeypatch.setattr(vpd, "list_workflow_runs", lambda sha, repo, token="": [
        {"name": "Deploy", "conclusion": "success", "status": "completed",
         "html_url": "https://x/1", "id": 1},
        {"name": "Pipeline", "conclusion": "success", "status": "completed",
         "html_url": "https://x/2", "id": 2},
    ])
    monkeypatch.setattr(
        vpd, "check_pages_content",
        lambda url, keywords, timeout=15: (True, "HTTP 200 · sentinel found"),
    )

    report = vpd.verify(
        sha="abc1234", wait_min=1, base_dir=tmp_path,
        freshness_files=["output/final_results.json"],
    )
    assert report["exit_code"] == vpd.EXIT_OK
    assert report["workflows"]["success_count"] == 2
    assert report["pages"]["ok"] is True
    assert report["freshness"]["all_fresh"] is True
    assert report["failures"] == []


def test_T_VPD_6_verify_workflow_fail(vpd, tmp_path, monkeypatch):
    """workflow 하나 실패 → exit 2 + failures 명시."""
    p = tmp_path / "output" / "x.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat()
    }), encoding="utf-8")

    monkeypatch.setattr(vpd, "list_workflow_runs", lambda sha, repo, token="": [
        {"name": "Deploy", "conclusion": "success", "status": "completed",
         "html_url": "https://x/1", "id": 1},
        {"name": "Credential Audit", "conclusion": "failure",
         "status": "completed", "html_url": "https://x/2", "id": 2},
    ])
    monkeypatch.setattr(
        vpd, "check_pages_content",
        lambda url, keywords, timeout=15: (True, "OK"),
    )

    report = vpd.verify(
        sha="def5678", wait_min=1, base_dir=tmp_path,
        freshness_files=["output/x.json"],
    )
    assert report["exit_code"] == vpd.EXIT_WORKFLOW_FAIL
    assert any("Credential Audit" in f for f in report["failures"])


def test_T_VPD_7_verify_freshness_only_fail(vpd, tmp_path, monkeypatch):
    """workflow OK / Pages OK / stale → exit 5."""
    p = tmp_path / "output" / "old.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    }), encoding="utf-8")

    monkeypatch.setattr(vpd, "list_workflow_runs", lambda sha, repo, token="": [
        {"name": "Deploy", "conclusion": "success", "status": "completed",
         "html_url": "https://x/1", "id": 1},
    ])
    monkeypatch.setattr(
        vpd, "check_pages_content",
        lambda url, keywords, timeout=15: (True, "OK"),
    )

    report = vpd.verify(
        sha="deadbee", wait_min=1, base_dir=tmp_path,
        freshness_files=["output/old.json"],
    )
    assert report["exit_code"] == vpd.EXIT_FRESHNESS_FAIL


def test_T_VPD_8_render_human_shows_failures(vpd):
    report = {
        "sha": "1234567890abcdef",
        "repo": "x/y",
        "started_at": "2026-07-04T00:00:00+00:00",
        "completed_at": "2026-07-04T00:05:00+00:00",
        "workflows": {
            "total": 2, "success_count": 1, "failure_count": 1, "other_count": 0,
            "timed_out": False,
            "successes": [{"name": "A", "conclusion": "success"}],
            "failures": [{"name": "B", "conclusion": "failure",
                          "url": "https://x/2"}],
            "others": [],
        },
        "pages": {"url": "https://y/", "ok": False, "detail": "sentinel 누락"},
        "freshness": {"all_fresh": True, "details": [], "max_hours": 24},
        "exit_code": 2,
        "failures": ["WORKFLOW_FAIL: B", "CONTENT_FAIL: sentinel 누락"],
    }
    out = vpd.render_human(report)
    assert "❌ B" in out
    assert "sentinel 누락" in out
    assert "exit_code=2" in out


def test_T_VPD_9_extract_ts_various_formats(vpd):
    assert vpd._extract_ts({"generated_at": "2026-07-04T10:00:00Z"},
                           "generated_at") is not None
    assert vpd._extract_ts({"generated_at": "2026-07-04T10:00:00+00:00"},
                           "generated_at") is not None
    assert vpd._extract_ts({"meta": {"generated_at": "2026-07-04T10:00:00"}},
                           "generated_at") is not None
    assert vpd._extract_ts({"generated_at": "not-a-date"}, "generated_at") is None
    assert vpd._extract_ts({}, "generated_at") is None


def test_T_VPD_10_main_short_sha_invalid(vpd, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["verify_push_deployment.py", "--sha", "abc"])
    rc = vpd.main()
    assert rc == vpd.EXIT_INVALID_ARGS


# ─── Step 2 신규 (2026-07-04): --remote 옵션 회귀 ─────────────────

def test_T_VPD_11_remote_freshness_fresh(vpd, monkeypatch):
    """원격 raw URL 이 fresh generated_at 반환 → all_fresh=True."""
    fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fake_body = json.dumps({"generated_at": fresh_ts}).encode("utf-8")

    class FakeResp:
        status = 200
        def read(self): return fake_body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(vpd.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    ok, results = vpd.check_freshness_remote(
        ["output/x.json"], sha="abc123", repo="o/r", max_hours=24,
    )
    assert ok is True
    assert results[0]["fresh"] is True
    assert "remote.json.generated_at" in results[0]["source"]
    assert "raw.githubusercontent.com" in results[0]["url"]


def test_T_VPD_12_remote_freshness_stale(vpd, monkeypatch):
    """원격 파일 timestamp 오래됨 → stale."""
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    fake_body = json.dumps({"generated_at": old_ts}).encode("utf-8")

    class FakeResp:
        status = 200
        def read(self): return fake_body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(vpd.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    ok, results = vpd.check_freshness_remote(
        ["output/x.json"], sha="abc123", repo="o/r", max_hours=24,
    )
    assert ok is False
    assert "stale" in results[0]["reason"]


def test_T_VPD_13_remote_freshness_http_error(vpd, monkeypatch):
    """404 등 HTTP 오류 → fresh=False + reason 명시."""
    import urllib.error
    def _raise(*a, **k):
        raise urllib.error.HTTPError(
            "https://x", 404, "Not Found", {}, None,
        )
    monkeypatch.setattr(vpd.urllib.request, "urlopen", _raise)
    ok, results = vpd.check_freshness_remote(
        ["output/missing.json"], sha="abc123", repo="o/r", max_hours=24,
    )
    assert ok is False
    assert "fetch" in results[0]["reason"] or "404" in results[0]["reason"]


def test_T_VPD_14_verify_remote_flag_uses_remote(vpd, tmp_path, monkeypatch):
    """verify(remote_freshness=True) → check_freshness_remote 호출."""
    called = {"remote": 0, "local": 0}
    monkeypatch.setattr(vpd, "list_workflow_runs",
                        lambda sha, repo, token="": [
                            {"name": "X", "conclusion": "success",
                             "status": "completed", "html_url": "u", "id": 1}
                        ])
    monkeypatch.setattr(vpd, "check_pages_content",
                        lambda url, kws, timeout=15: (True, "OK"))

    def _mock_remote(files, sha, repo, max_hours, now=None):
        called["remote"] += 1
        return True, [{"file": f, "fresh": True, "age_hours": 0.5,
                       "source": "remote.json.generated_at",
                       "ts": "2026-07-04T00:00:00+00:00",
                       "url": f"https://raw/{sha}/{f}", "exists": True}
                      for f in files]

    def _mock_local(files, base_dir, max_hours, now=None):
        called["local"] += 1
        return True, []

    monkeypatch.setattr(vpd, "check_freshness_remote", _mock_remote)
    monkeypatch.setattr(vpd, "check_freshness", _mock_local)

    report = vpd.verify(
        sha="deadbeef123", wait_min=1, base_dir=tmp_path,
        freshness_files=["output/x.json"],
        remote_freshness=True,
    )
    assert called["remote"] == 1
    assert called["local"] == 0
    assert report["freshness"]["scope"] == "remote"
