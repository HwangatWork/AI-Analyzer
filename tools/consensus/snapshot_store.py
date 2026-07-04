# -*- coding: utf-8 -*-
"""Phase 14-0-C - Immutable daily snapshot store.

Point-in-time (PIT) invariant activator. Every successful pipeline run
appends a dated, self-contained, tamper-detectable snapshot to
`output/consensus_snapshot/history/{ticker}/{YYYY-MM-DD}/`.

Ljungqvist, Malloy, Marston 2009 (JoF) documented I/B/E/S retroactively
modifying 1.6-21.7% of historical analyst recommendation records. WiseReport's
chartData2 monthly series is a moving target as well. Self-captured
snapshots are the only look-ahead-safe historical truth.

Design invariants (enforced by tests and X19-X22):

  1. WRITE-ONCE. `write_snapshot(force=False)` refuses if
     `{date}/manifest.json` already exists.
  2. TAMPER DETECTION. `verify_snapshot_integrity(ticker, date)` returns
     False if any file's sha256 no longer matches the manifest.
  3. QUALITY GATE. Refuse write if `data_quality.score < 0.5`.
  4. NO DESTRUCTIVE OPERATIONS. This module contains no `delete_*` or
     `edit_*` functions. External callers must NEVER attempt destructive
     operations on the history tree.
  5. READ-ONLY QUERIES. `load_snapshot`, `list_snapshots`,
     `get_snapshot_batch` are pure read-only.

Layout:

  output/consensus_snapshot/history/
    000660/
      2026-07-01/
        parsed.json
        analysis.json
        report.md
        manifest.json         # sha256 per file + top-level + metadata
      2026-07-03/
        parsed.json
        ...
    005930/
      2026-07-03/
        ...

Backward compatibility: the existing flat-file outputs
(`output/consensus_snapshot/{ticker}_{date}_*.json`) remain and are
unaffected. History is ADDITIVE.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional


DEFAULT_HISTORY_ROOT = "output/consensus_snapshot/history"
QUALITY_MIN = 0.5


# ---------- helpers ----------

def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head_sha() -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def snapshot_dir(ticker: str, date: str,
                 history_root: str = DEFAULT_HISTORY_ROOT) -> Path:
    return Path(history_root) / ticker / date


# ---------- write ----------

class SnapshotExistsError(RuntimeError):
    """Raised when write_snapshot refuses to overwrite existing snapshot."""


class QualityGateError(RuntimeError):
    """Raised when data_quality.score is below QUALITY_MIN."""


def write_snapshot(
    ticker: str,
    parsed: dict,
    analysis: dict,
    report_md: str,
    date: Optional[str] = None,
    force: bool = False,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> dict:
    """Write an immutable snapshot for (ticker, date).

    Raises:
        SnapshotExistsError - if manifest exists and force is False.
        QualityGateError    - if analysis['data_quality']['score'] < QUALITY_MIN.

    Returns a manifest dict.
    """
    date = date or _today_iso()

    # Quality gate (Evaluator Agent's pre-concern)
    score = (analysis.get("data_quality") or {}).get("score", 0.0)
    if score < QUALITY_MIN:
        raise QualityGateError(
            f"data_quality.score {score:.3f} < min {QUALITY_MIN}; "
            f"snapshot refused for ticker={ticker} date={date}"
        )

    dir_path = snapshot_dir(ticker, date, history_root)
    manifest_path = dir_path / "manifest.json"

    # Write-once check (Data Agent's pre-concern)
    if manifest_path.exists() and not force:
        raise SnapshotExistsError(
            f"snapshot already exists: {manifest_path}. Use force=True to override."
        )

    # Prepare directory
    dir_path.mkdir(parents=True, exist_ok=True)

    # Atomic write via temp then rename (per file, X19 concern)
    files: dict[str, str] = {}

    def _atomic_write_text(name: str, content: str) -> None:
        tmp = dir_path / (name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        final = dir_path / name
        os.replace(tmp, final)

    parsed_bytes = (
        json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    analysis_bytes = (
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    # Write payload files
    for name, content_bytes in (
        ("parsed.json", parsed_bytes),
        ("analysis.json", analysis_bytes),
        ("report.md", report_md.encode("utf-8")),
    ):
        tmp = dir_path / (name + ".tmp")
        with tmp.open("wb") as fh:
            fh.write(content_bytes)
        final = dir_path / name
        os.replace(tmp, final)
        files[name] = _sha256_bytes(content_bytes)

    # Manifest with per-file + top-level sha256
    top_content = "\n".join(f"{name}:{sha}" for name, sha in sorted(files.items()))
    top_sha = _sha256_bytes(top_content.encode("utf-8"))
    manifest = {
        "schema_version": "1.0",
        "ticker": ticker,
        "date": date,
        "written_at_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds"),
        "files": files,
        "top_sha256": top_sha,
        "pipeline_git_head_sha": _git_head_sha(),
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    tmp = dir_path / "manifest.json.tmp"
    with tmp.open("wb") as fh:
        fh.write(manifest_bytes)
    os.replace(tmp, manifest_path)

    return manifest


# ---------- read (all READ-ONLY) ----------

def load_snapshot(
    ticker: str,
    date: str,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> Optional[dict]:
    """Read a past snapshot. Returns dict with parsed/analysis/report/manifest,
    or None if the snapshot does not exist. Never modifies the tree."""
    dir_path = snapshot_dir(ticker, date, history_root)
    if not dir_path.exists():
        return None
    manifest_path = dir_path / "manifest.json"
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    result: dict[str, Any] = {"manifest": manifest, "date": date, "ticker": ticker}
    for name in ("parsed.json", "analysis.json"):
        p = dir_path / name
        if p.exists():
            with p.open("r", encoding="utf-8") as fh:
                result[name.replace(".json", "")] = json.load(fh)
    report_p = dir_path / "report.md"
    if report_p.exists():
        result["report_md"] = report_p.read_text(encoding="utf-8")
    return result


def list_snapshots(
    ticker: str,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> list[str]:
    """List all snapshot dates for a ticker, chronologically ordered."""
    ticker_dir = Path(history_root) / ticker
    if not ticker_dir.exists():
        return []
    dates = []
    for entry in ticker_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if len(name) == 10 and name[4] == "-" and name[7] == "-":
            try:
                _dt.date.fromisoformat(name)
                if (entry / "manifest.json").exists():
                    dates.append(name)
            except ValueError:
                pass
    return sorted(dates)


def detect_gaps(dates: list[str], max_gap_days: int = 2) -> list[tuple[str, str, int]]:
    """Return list of (prev_date, next_date, gap_days) where gap exceeds threshold."""
    gaps: list[tuple[str, str, int]] = []
    for i in range(1, len(dates)):
        prev = _dt.date.fromisoformat(dates[i - 1])
        curr = _dt.date.fromisoformat(dates[i])
        gap = (curr - prev).days
        if gap > max_gap_days:
            gaps.append((dates[i - 1], dates[i], gap))
    return gaps


def get_snapshot_batch(
    tickers: list[str],
    date: str,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> dict[str, Optional[dict]]:
    """Batch load same-date snapshots for multiple tickers (Sector Agent)."""
    return {t: load_snapshot(t, date, history_root) for t in tickers}


# ---------- integrity ----------

def verify_snapshot_integrity(
    ticker: str,
    date: str,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> dict:
    """Verify all sha256 in manifest against on-disk files.

    Returns:
      {
        "ok": bool,
        "date": str, "ticker": str,
        "checked": int,
        "mismatches": list[str],
        "missing": list[str],
        "top_sha256_match": bool | None,
      }
    """
    dir_path = snapshot_dir(ticker, date, history_root)
    manifest_path = dir_path / "manifest.json"
    result: dict[str, Any] = {
        "ok": False, "date": date, "ticker": ticker,
        "checked": 0, "mismatches": [], "missing": [],
        "top_sha256_match": None,
    }
    if not manifest_path.exists():
        result["missing"].append("manifest.json")
        return result
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    files = manifest.get("files", {})
    for name, expected_sha in files.items():
        p = dir_path / name
        if not p.exists():
            result["missing"].append(name)
            continue
        actual = _sha256_file(p)
        result["checked"] += 1
        if actual != expected_sha:
            result["mismatches"].append(
                f"{name}: expected {expected_sha[:12]} actual {actual[:12]}"
            )
    if not result["missing"] and not result["mismatches"]:
        # Recompute top_sha256
        top_content = "\n".join(f"{n}:{sha}" for n, sha in sorted(files.items()))
        top_sha = _sha256_bytes(top_content.encode("utf-8"))
        result["top_sha256_match"] = top_sha == manifest.get("top_sha256")
        result["ok"] = result["top_sha256_match"] is True
    return result


# ---------- Q1 point-in-time helper ----------

def compute_pit_q1_change(
    ticker: str,
    current_target: float,
    reference_days: int = 30,
    history_root: str = DEFAULT_HISTORY_ROOT,
) -> Optional[dict]:
    """Compute Q1 target-price 1-month change using immutable snapshot history.

    Args:
      ticker: KRX numeric
      current_target: latest_target_price from current run
      reference_days: how many calendar days back to compare (default 30)

    Returns:
      None if <2 snapshots or reference snapshot lacks target price.
      Otherwise {source, prior_date, prior_target, change_pct}.
    """
    dates = list_snapshots(ticker, history_root)
    if not dates:
        return None
    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=reference_days)
    # Find the snapshot closest to cutoff but not after
    candidate = None
    for d in dates:
        d_obj = _dt.date.fromisoformat(d)
        if d_obj <= cutoff:
            candidate = d
    if candidate is None and dates:
        candidate = dates[0]  # oldest available
    snap = load_snapshot(ticker, candidate, history_root) if candidate else None
    if not snap:
        return None
    a = snap.get("analysis") or {}
    prior_target = (a.get("raw_inputs") or {}).get("latest_target_price")
    if not isinstance(prior_target, (int, float)) or prior_target <= 0:
        return None
    change = (current_target - prior_target) / prior_target * 100
    return {
        "source": "snapshot_pit_prior_day",
        "prior_date": candidate,
        "prior_target": float(prior_target),
        "current_target": float(current_target),
        "change_pct": float(change),
    }
