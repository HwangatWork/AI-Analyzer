# -*- coding: utf-8 -*-
"""Generate dates.json index for each ticker's snapshot history.

Static Pages cannot list directories, so the dashboard needs a JSON index
listing available snapshot dates per ticker. This script scans the
`output/consensus_snapshot/history/{ticker}/` tree and writes
`dates.json` in each ticker folder.

Usage:
    python scripts/generate_snapshot_index.py \
        [--history-root output/consensus_snapshot/history]

Idempotent. Safe to re-run.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


def _is_iso_date(name: str) -> bool:
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    try:
        _dt.date.fromisoformat(name)
        return True
    except ValueError:
        return False


def build_ticker_index(ticker_dir: Path) -> dict:
    """Scan a single ticker directory. Returns {"dates": [...], "count": N,
    "latest": "YYYY-MM-DD"|null}."""
    dates: list[str] = []
    for entry in ticker_dir.iterdir():
        if not entry.is_dir():
            continue
        if not _is_iso_date(entry.name):
            continue
        if (entry / "manifest.json").exists():
            dates.append(entry.name)
    dates.sort()
    return {
        "dates": dates,
        "count": len(dates),
        "latest": dates[-1] if dates else None,
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-root",
        default="output/consensus_snapshot/history",
    )
    args = parser.parse_args(argv)

    root = Path(args.history_root)
    if not root.exists():
        sys.stderr.write(f"history root does not exist: {root}\n")
        return 1

    tickers_processed = 0
    for ticker_dir in sorted(root.iterdir()):
        if not ticker_dir.is_dir():
            continue
        index = build_ticker_index(ticker_dir)
        out_path = ticker_dir / "dates.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        sys.stdout.write(
            f"generated: {out_path} count={index['count']} latest={index['latest']}\n"
        )
        tickers_processed += 1

    if tickers_processed == 0:
        sys.stderr.write("no ticker directories found under history root\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
