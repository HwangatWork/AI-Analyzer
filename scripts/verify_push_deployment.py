# -*- coding: utf-8 -*-
"""
verify_push_deployment.py — Post-push comprehensive verification (2026-07-04).

사용자 요구사항 (라운드 16 directive 완전 준수):
- 매 push 후 primary deploy 만 검증 → "성공" 보고 = PASS 위장 패턴 차단
- ALL workflows on the SHA + 완료까지 대기 + content + freshness + 정직 보고

## 검증 항목 (모두 통과해야 exit 0)
1. GitHub Actions API: SHA 로 트리거된 ALL workflows conclusion == success
2. Pages URL HTTP 200 (기본 https://hwangatwork.github.io/AI-Analyzer/)
3. Pages 콘텐츠에 예상 sentinel 포함
4. output/*.json 신선도 (generated_at 또는 mtime 24h 이내)
5. 실패 시 workflow name + conclusion + URL 명시

## 사용법
    python scripts/verify_push_deployment.py --sha <SHA>
    python scripts/verify_push_deployment.py --sha $(git rev-parse HEAD)
    python scripts/verify_push_deployment.py --sha <SHA> --wait-min 20 --json

## Exit codes
    0 = 모든 workflow 성공 + content OK + freshness OK
    2 = 하나 이상 workflow failure (사용자 조치 필요)
    3 = poll timeout (완료 안 됨)
    4 = content 검증 실패 (Pages HTTP 오류 or sentinel 부재)
    5 = freshness 실패 (데이터 stale)
    1 = invalid args
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "HwangatWork/AI-Analyzer"
DEFAULT_PAGES_URL = "https://hwangatwork.github.io/AI-Analyzer/"
DEFAULT_WAIT_MIN = 20
POLL_INTERVAL_SEC = 30
DEFAULT_SENTINEL_KEYWORDS = ["AI Analyzer", "dashboard", "market"]
DEFAULT_FRESHNESS_FILES = [
    "output/final_results.json",
    "output/decision.json",
]
FRESHNESS_MAX_HOURS = 24

EXIT_OK = 0
EXIT_INVALID_ARGS = 1
EXIT_WORKFLOW_FAIL = 2
EXIT_POLL_TIMEOUT = 3
EXIT_CONTENT_FAIL = 4
EXIT_FRESHNESS_FAIL = 5


def _gh_api(path: str, token: str = "") -> dict:
    """GitHub API GET. token 있으면 인증, 401 시 unauth fallback (public repo 가능)."""
    url = f"https://api.github.com{path}"
    base_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "verify-push-deployment/1.0",
    }

    def _do(headers: dict) -> dict:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    if token:
        try:
            return _do({**base_headers, "Authorization": f"Bearer {token}"})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                # 만료 or 잘못된 토큰 → unauth 재시도 (public repo 만)
                return _do(base_headers)
            raise
    return _do(base_headers)


def list_workflow_runs(sha: str, repo: str, token: str = "") -> list[dict]:
    """SHA 로 트리거된 모든 workflow run 조회."""
    path = f"/repos/{repo}/actions/runs?head_sha={sha}&per_page=100"
    data = _gh_api(path, token=token)
    return data.get("workflow_runs", []) or []


def poll_until_complete(
    sha: str,
    repo: str,
    token: str = "",
    max_wait_sec: int = DEFAULT_WAIT_MIN * 60,
    poll_interval: int = POLL_INTERVAL_SEC,
    stderr=sys.stderr,
) -> tuple[list[dict], bool]:
    """모든 workflow run 이 completed 될 때까지 poll.

    Returns:
        (runs, timed_out): terminal runs + timeout 여부
    """
    start = time.time()
    while True:
        try:
            runs = list_workflow_runs(sha, repo, token=token)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"[verify] API 오류: {e} — 재시도 예정", file=stderr)
            runs = []

        if runs:
            non_terminal = [r for r in runs if r.get("status") != "completed"]
            if not non_terminal:
                return runs, False
            print(
                f"[verify] {len(runs)} runs 중 {len(non_terminal)} 진행 중 "
                f"(경과 {int(time.time()-start)}s / 한계 {max_wait_sec}s)",
                file=stderr,
            )
        else:
            print(
                f"[verify] workflow run 아직 없음 (경과 {int(time.time()-start)}s)",
                file=stderr,
            )

        if time.time() - start >= max_wait_sec:
            return runs, True
        time.sleep(poll_interval)


def check_pages_content(
    pages_url: str,
    sentinel_keywords: list[str],
    timeout: int = 15,
) -> tuple[bool, str]:
    """Pages URL fetch + sentinel 포함 여부."""
    try:
        req = urllib.request.Request(
            pages_url,
            headers={"User-Agent": "verify-push-deployment/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            body = resp.read().decode("utf-8", errors="replace")
        found = [k for k in sentinel_keywords if k.lower() in body.lower()]
        missing = [k for k in sentinel_keywords if k.lower() not in body.lower()]
        if missing:
            return False, f"sentinel 누락: {missing} (found: {found})"
        return True, f"HTTP 200 · sentinel {found} 모두 포함 ({len(body)} bytes)"
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        return False, f"fetch 실패: {e}"


def check_freshness_remote(
    files: list[str],
    sha: str,
    repo: str,
    max_hours: int,
    now: datetime | None = None,
) -> tuple[bool, list[dict]]:
    """원격 (raw.githubusercontent.com) 파일 신선도.

    2026-07-04 UX fix: 로컬이 pull 안 되면 stale 오탐. --remote 는
    실 원격 파일 fetch 후 generated_at/computed_at 확인.

    반환 shape 은 check_freshness 와 동일. source 필드에 "remote.<key>" 표기.
    """
    now = now or datetime.now(timezone.utc)
    results = []
    all_fresh = True
    for rel in files:
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{rel}"
        entry = {"file": rel, "url": url}
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "verify-push-deployment/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    entry.update({"exists": False, "fresh": False,
                                  "reason": f"HTTP {resp.status}"})
                    all_fresh = False
                    results.append(entry)
                    continue
                body = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            entry.update({"exists": False, "fresh": False,
                          "reason": f"fetch: {e}"})
            all_fresh = False
            results.append(entry)
            continue

        entry["exists"] = True
        ts = None
        source = None
        if rel.endswith(".json"):
            try:
                data = json.loads(body)
                for key in ("generated_at", "computed_at"):
                    v = _extract_ts(data, key)
                    if v:
                        ts = v
                        source = f"remote.json.{key}"
                        break
            except json.JSONDecodeError:
                pass
        if ts is None:
            # non-json 또는 timestamp 필드 부재 → 원격 mtime 불가 → last-modified 헤더
            entry.update({"fresh": False,
                          "reason": "원격 파일에 timestamp 필드 부재"})
            all_fresh = False
            results.append(entry)
            continue

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now - ts).total_seconds() / 3600
        fresh = age_hours <= max_hours
        entry.update({
            "fresh": fresh,
            "age_hours": round(age_hours, 2),
            "source": source,
            "ts": ts.isoformat(timespec="seconds"),
        })
        if not fresh:
            entry["reason"] = f"stale: {age_hours:.1f}h > {max_hours}h"
            all_fresh = False
        results.append(entry)
    return all_fresh, results


def check_freshness(
    files: list[str],
    base_dir: Path,
    max_hours: int,
    now: datetime | None = None,
) -> tuple[bool, list[dict]]:
    """각 파일의 generated_at 또는 mtime 이 max_hours 이내인지."""
    now = now or datetime.now(timezone.utc)
    results = []
    all_fresh = True
    for rel in files:
        p = base_dir / rel
        entry = {"file": rel, "exists": p.exists()}
        if not p.exists():
            entry["fresh"] = False
            entry["reason"] = "missing"
            all_fresh = False
            results.append(entry)
            continue

        # JSON 이면 generated_at / computed_at 시도, 아니면 mtime
        ts = None
        source = "mtime"
        if rel.endswith(".json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for key in ("generated_at", "computed_at"):
                    v = _extract_ts(data, key)
                    if v:
                        ts = v
                        source = f"json.{key}"
                        break
            except (OSError, json.JSONDecodeError):
                pass
        if ts is None:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

        # ts 가 naive 이면 UTC assume
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        age_hours = (now - ts).total_seconds() / 3600
        fresh = age_hours <= max_hours
        entry.update({
            "fresh": fresh,
            "age_hours": round(age_hours, 2),
            "source": source,
            "ts": ts.isoformat(timespec="seconds"),
        })
        if not fresh:
            entry["reason"] = f"stale: {age_hours:.1f}h > {max_hours}h"
            all_fresh = False
        results.append(entry)
    return all_fresh, results


def _extract_ts(data: dict, key: str) -> datetime | None:
    """dict 어디에서든 key 를 찾아 datetime 파싱. 얕은 탐색만."""
    v = data.get(key) if isinstance(data, dict) else None
    if not v and isinstance(data, dict):
        # 1-depth nested
        for _, val in data.items():
            if isinstance(val, dict):
                v = val.get(key)
                if v:
                    break
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def summarize_runs(runs: list[dict]) -> dict:
    """workflow runs 요약. 실패 항목 detail 포함."""
    total = len(runs)
    successes = []
    failures = []
    others = []
    for r in runs:
        name = r.get("name") or r.get("workflow_id", "?")
        conclusion = r.get("conclusion")
        html_url = r.get("html_url", "")
        entry = {
            "name": name,
            "conclusion": conclusion,
            "status": r.get("status"),
            "url": html_url,
            "run_id": r.get("id"),
        }
        if conclusion == "success":
            successes.append(entry)
        elif conclusion in ("failure", "cancelled", "timed_out", "action_required"):
            failures.append(entry)
        else:
            others.append(entry)
    return {
        "total": total,
        "success_count": len(successes),
        "failure_count": len(failures),
        "other_count": len(others),
        "successes": successes,
        "failures": failures,
        "others": others,
    }


def verify(
    sha: str,
    repo: str = DEFAULT_REPO,
    pages_url: str = DEFAULT_PAGES_URL,
    wait_min: int = DEFAULT_WAIT_MIN,
    sentinel_keywords: list[str] | None = None,
    freshness_files: list[str] | None = None,
    freshness_hours: int = FRESHNESS_MAX_HOURS,
    token: str = "",
    base_dir: Path | None = None,
    stderr=sys.stderr,
    remote_freshness: bool = False,
) -> dict:
    """전체 검증. dict 반환 (exit_code 포함)."""
    sentinel_keywords = sentinel_keywords or DEFAULT_SENTINEL_KEYWORDS
    freshness_files = freshness_files or DEFAULT_FRESHNESS_FILES
    base_dir = base_dir or BASE_DIR

    report = {
        "sha": sha,
        "repo": repo,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workflows": None,
        "pages": None,
        "freshness": None,
        "exit_code": EXIT_OK,
        "failures": [],
    }

    # 1. Workflow poll
    print(f"[verify] SHA {sha[:8]} 의 모든 workflow poll 시작 (최대 {wait_min}min)",
          file=stderr)
    runs, timed_out = poll_until_complete(
        sha, repo, token=token,
        max_wait_sec=wait_min * 60,
        stderr=stderr,
    )
    summary = summarize_runs(runs)
    report["workflows"] = {**summary, "timed_out": timed_out}

    if timed_out:
        report["exit_code"] = EXIT_POLL_TIMEOUT
        report["failures"].append(
            f"POLL_TIMEOUT: {wait_min}min 내 완료 안 됨 (진행 중: {summary['other_count']})"
        )
    elif summary["failure_count"] > 0:
        report["exit_code"] = EXIT_WORKFLOW_FAIL
        for f in summary["failures"]:
            report["failures"].append(
                f"WORKFLOW_FAIL: '{f['name']}' → {f['conclusion']} · {f['url']}"
            )

    # 2. Pages content check (workflow 실패해도 실행 — 사용자 관점 확인)
    print(f"[verify] Pages content check: {pages_url}", file=stderr)
    ok, msg = check_pages_content(pages_url, sentinel_keywords)
    report["pages"] = {"url": pages_url, "ok": ok, "detail": msg}
    if not ok:
        if report["exit_code"] == EXIT_OK:
            report["exit_code"] = EXIT_CONTENT_FAIL
        report["failures"].append(f"CONTENT_FAIL: {msg}")

    # 3. Freshness check (remote or local)
    scope = "remote" if remote_freshness else "local"
    print(f"[verify] Freshness ({scope}): {len(freshness_files)} 파일",
          file=stderr)
    if remote_freshness:
        all_fresh, fresh_details = check_freshness_remote(
            freshness_files, sha, repo, freshness_hours,
        )
    else:
        all_fresh, fresh_details = check_freshness(
            freshness_files, base_dir, freshness_hours,
        )
    report["freshness"] = {"all_fresh": all_fresh, "details": fresh_details,
                            "max_hours": freshness_hours, "scope": scope}
    if not all_fresh:
        if report["exit_code"] == EXIT_OK:
            report["exit_code"] = EXIT_FRESHNESS_FAIL
        for d in fresh_details:
            if not d.get("fresh"):
                report["failures"].append(
                    f"FRESHNESS_FAIL: {d['file']} — {d.get('reason', 'stale')}"
                )

    report["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


def render_human(report: dict) -> str:
    """사람 판독용 요약."""
    lines = []
    lines.append(f"╔═══ Push Verification Report — SHA {report['sha'][:8]} ═══")
    lines.append(f"║ repo: {report['repo']}")
    lines.append(f"║ started: {report['started_at']} → completed: {report.get('completed_at', '?')}")

    wf = report.get("workflows") or {}
    lines.append(f"║")
    lines.append(f"║ [1] Workflows: total={wf.get('total', 0)}, "
                 f"success={wf.get('success_count', 0)}, "
                 f"failure={wf.get('failure_count', 0)}, "
                 f"other={wf.get('other_count', 0)}, "
                 f"timed_out={wf.get('timed_out', False)}")
    for f in wf.get("successes", []):
        lines.append(f"║   ✅ {f['name']} · {f['conclusion']}")
    for f in wf.get("failures", []):
        lines.append(f"║   ❌ {f['name']} · {f['conclusion']}")
        lines.append(f"║      → {f['url']}")
    for f in wf.get("others", []):
        lines.append(f"║   ⏳ {f['name']} · {f.get('status')} ({f.get('conclusion') or 'in-progress'})")

    p = report.get("pages") or {}
    lines.append(f"║")
    lines.append(f"║ [2] Pages: {'✅' if p.get('ok') else '❌'} {p.get('url', '?')}")
    lines.append(f"║   → {p.get('detail', '?')}")

    fr = report.get("freshness") or {}
    lines.append(f"║")
    scope = fr.get("scope", "local")
    lines.append(f"║ [3] Freshness ({scope}, ≤{fr.get('max_hours', '?')}h): "
                 f"{'✅' if fr.get('all_fresh') else '❌'}")
    for d in fr.get("details") or []:
        icon = "✅" if d.get("fresh") else "❌"
        detail = (f"{d.get('age_hours', '?')}h ({d.get('source', '?')})"
                  if d.get("fresh") is not None else d.get("reason", "?"))
        lines.append(f"║   {icon} {d['file']} · {detail}")

    lines.append(f"║")
    if report.get("failures"):
        lines.append(f"║ ⚡ Actionable failures ({len(report['failures'])}):")
        for f in report["failures"]:
            lines.append(f"║   • {f}")
    else:
        lines.append(f"║ ✅ 전체 통과 — 사용자 보고 '배포 완료' 가능")
    lines.append(f"║ exit_code={report['exit_code']}")
    lines.append(f"╚════════════════════════════════════")
    return "\n".join(lines)


def _force_utf8_stdio() -> None:
    """Windows cp949 환경에서 이모지/em-dash 출력 크래시 방지."""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def main() -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(
        description="Post-push comprehensive deployment verification"
    )
    ap.add_argument("--sha", required=True, help="commit SHA (git rev-parse HEAD)")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo")
    ap.add_argument("--pages-url", default=DEFAULT_PAGES_URL)
    ap.add_argument("--wait-min", type=int, default=DEFAULT_WAIT_MIN,
                    help="workflow poll timeout minutes")
    ap.add_argument("--freshness-hours", type=int, default=FRESHNESS_MAX_HOURS)
    ap.add_argument("--json", action="store_true", help="JSON output only")
    ap.add_argument("--sentinel", action="append", default=None,
                    help="Pages sentinel keyword (repeat for multi)")
    ap.add_argument("--freshness-file", action="append", default=None,
                    help="파일 경로 (repeat for multi)")
    ap.add_argument("--remote", action="store_true",
                    help="원격 (raw.githubusercontent.com) 파일 신선도 확인 — 로컬 미pull 오탐 방지")
    args = ap.parse_args()

    token = os.getenv("GITHUB_TOKEN", "").strip()

    if not args.sha or len(args.sha) < 7:
        print("[verify] --sha 필수 (min 7 chars)", file=sys.stderr)
        return EXIT_INVALID_ARGS

    # GitHub API head_sha 는 40자 full SHA 만 매칭. short SHA 시 auto-resolve.
    if len(args.sha) < 40:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", args.sha],
                capture_output=True, text=True, timeout=5,
                cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                full_sha = result.stdout.strip()
                if len(full_sha) == 40:
                    print(f"[verify] short SHA '{args.sha}' → full '{full_sha[:12]}...'",
                          file=sys.stderr)
                    args.sha = full_sha
        except Exception:
            pass  # git 없거나 실패 시 그대로 진행 (사용자가 이미 full SHA 줬을 수도)

    report = verify(
        sha=args.sha,
        repo=args.repo,
        pages_url=args.pages_url,
        wait_min=args.wait_min,
        sentinel_keywords=args.sentinel,
        freshness_files=args.freshness_file,
        freshness_hours=args.freshness_hours,
        token=token,
        remote_freshness=args.remote,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
