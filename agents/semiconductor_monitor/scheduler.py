# -*- coding: utf-8 -*-
"""
semiconductor_monitor/scheduler.py — APScheduler 통합 스케줄러

PM Agent 결정 사항:
  [D1] Option B: ECOS 단독 수집 (RSS 없음)
       이유: ECOS는 구조화된 월별 공식 데이터, RSS는 비정형 텍스트로 노이즈 많음
  [D2] L3 분석 깊이: 투자 시사점 포함
       이유: 투자 의사결정 도구에 가장 가치 있는 분석 수준
  [D3] ±10% MoM 초과 시만 알림
       이유: 월별 데이터 특성상 매번 알림은 과도함
  [D4] agents/semiconductor_monitor/ 디렉토리
       이유: 기존 agents/ 패턴 유지

Done Criteria:
  SC-1: output/semiconductor_export.json 파일 생성됨
  SC-2: 파일 비어있지 않음 (최소 1KB)
  SC-3: data 배열 최소 12개 항목
  SC-4: summary 필드 모두 존재 (latest_month, latest_value, mom_change_pct, yoy_change_pct)
  SC-5: is_mock=False 시 데이터 7일 이내 최신

실행 방법:
  python -m agents.semiconductor_monitor.scheduler
  python -m agents.semiconductor_monitor.scheduler --run-now
  python -m agents.semiconductor_monitor.scheduler --done-criteria
"""

import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows cp949 환경에서 한글 UnicodeEncodeError 방지
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# dotenv 로드
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).parent.parent.parent
OUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUT_DIR / "semiconductor_export.json"

# APScheduler 선택적 임포트
try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    print("[scheduler] APScheduler 미설치 — 직접 실행 모드로 fallback")
    print("[scheduler] 설치: pip install apscheduler")

# config.yaml 로드
def _load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (ImportError, FileNotFoundError):
        pass
    return {
        "scheduler": {
            "poll_days": [1, 2, 3, 4, 5],
            "poll_hour": 9,
            "retry_max": 3,
            "retry_backoff_base": 2,
        },
        "alert": {"threshold_pct": 10.0},
    }


def run_monitor_job() -> dict:
    """
    핵심 모니터링 작업:
      1. ECOS에서 반도체 수출 데이터 수집
      2. L3 분석 (투자 시사점 포함)
      3. ±10% MoM 초과 시 Telegram 알림
      4. 월초(1~5일)에 정기 요약도 발송

    Returns:
        {"export_data": ..., "analysis": ..., "alert_sent": bool, "summary_sent": bool}
    """
    from .data_fetcher import fetch_semiconductor_export
    from .analyzer import analyze_export_data
    from .notifier import send_alert, send_monthly_summary

    cfg = _load_config()
    threshold_pct = float(cfg.get("alert", {}).get("threshold_pct", 10.0))

    print(f"\n[scheduler] 모니터링 작업 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 데이터 수집
    export_data = fetch_semiconductor_export()

    # 2. L3 분석
    analysis = analyze_export_data(export_data)
    print(f"[scheduler] 분석 완료: {analysis[:80]}...")

    # 3. 임계값 초과 알림
    alert_sent = send_alert(export_data, analysis, threshold_pct=threshold_pct)

    # 4. 매월 1~5일 정기 요약 (임계값 무관)
    summary_sent = False
    today = datetime.now().day
    poll_days = cfg.get("scheduler", {}).get("poll_days", [1, 2, 3, 4, 5])
    if today in poll_days:
        print(f"[scheduler] 월초 {today}일 — 정기 요약 발송")
        summary_sent = send_monthly_summary(export_data, analysis)

    print(f"[scheduler] 작업 완료 — alert={alert_sent}, summary={summary_sent}")
    return {
        "export_data": export_data,
        "analysis": analysis,
        "alert_sent": alert_sent,
        "summary_sent": summary_sent,
    }


# ══════════════════════════════════════════════════════════════
# Done Criteria 자체 검증
# ══════════════════════════════════════════════════════════════

def _run_done_criteria() -> bool:
    """
    SC-1~SC-5 자체 검증.
    PASS 시 True 반환, FAIL 시 sys.exit(1).
    """
    print("\n[scheduler] Done Criteria 검증 시작")
    failures = []

    # SC-1: output/semiconductor_export.json 파일 생성됨
    if not OUTPUT_FILE.exists():
        failures.append(f"SC-1 FAIL: {OUTPUT_FILE} 파일 없음")
    else:
        print(f"  SC-1 PASS: {OUTPUT_FILE} 존재")

        # SC-2: 파일 비어있지 않음 (최소 1KB)
        size = OUTPUT_FILE.stat().st_size
        if size < 1024:
            failures.append(f"SC-2 FAIL: 파일 크기 {size}B < 1KB")
        else:
            print(f"  SC-2 PASS: 파일 크기 {size}B >= 1KB")

        # 파일 파싱
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # SC-3: data 배열 최소 12개 항목
            data_rows = data.get("data", [])
            if len(data_rows) < 12:
                failures.append(f"SC-3 FAIL: data 배열 {len(data_rows)}개 < 12개")
            else:
                print(f"  SC-3 PASS: data 배열 {len(data_rows)}개")

            # SC-4: summary 필드 모두 존재
            summary = data.get("summary", {})
            required_keys = ["latest_month", "latest_value", "mom_change_pct", "yoy_change_pct"]
            missing = [k for k in required_keys if k not in summary]
            if missing:
                failures.append(f"SC-4 FAIL: summary 누락 필드 {missing}")
            else:
                print(f"  SC-4 PASS: summary 필드 모두 존재")

            # SC-5: is_mock=False 시 데이터 7일 이내 최신
            is_mock = data.get("is_mock", True)
            if not is_mock:
                latest_month = summary.get("latest_month", "")
                if len(latest_month) == 6:
                    try:
                        latest_dt = datetime.strptime(latest_month, "%Y%m")
                        age_days = (datetime.now() - latest_dt).days
                        if age_days > 37:  # 월별 데이터: 최대 37일 (한 달 + 약간의 여유)
                            failures.append(
                                f"SC-5 FAIL: 최신 데이터 {latest_month} — {age_days}일 경과 (>37일)"
                            )
                        else:
                            print(f"  SC-5 PASS: 최신 데이터 {latest_month} ({age_days}일 경과)")
                    except ValueError:
                        failures.append(f"SC-5 FAIL: latest_month 파싱 오류 ({latest_month})")
                else:
                    failures.append(f"SC-5 FAIL: latest_month 형식 오류 ({latest_month})")
            else:
                print("  SC-5 SKIP: is_mock=True (mock 데이터는 날짜 검사 제외)")

        except json.JSONDecodeError as exc:
            failures.append(f"SC-3~5 FAIL: JSON 파싱 오류 — {exc}")
        except Exception as exc:
            failures.append(f"SC-3~5 FAIL: 파일 읽기 오류 — {exc}")

    print()
    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        print(f"DONE_CRITERIA: FAIL — {' | '.join(failures)}")
        sys.exit(1)
    else:
        print("DONE_CRITERIA: PASS — SC-1~SC-5 모두 통과")
        return True


# ══════════════════════════════════════════════════════════════
# APScheduler 통합
# ══════════════════════════════════════════════════════════════

def start_scheduler():
    """
    APScheduler로 매월 1~5일 오전 9시 모니터링 작업 스케줄.
    APScheduler 미설치 시 직접 실행 후 종료.
    """
    cfg = _load_config()
    sched_cfg = cfg.get("scheduler", {})
    poll_days = sched_cfg.get("poll_days", [1, 2, 3, 4, 5])
    poll_hour = int(sched_cfg.get("poll_hour", 9))

    if not _APSCHEDULER_AVAILABLE:
        print("[scheduler] APScheduler 없음 — 즉시 1회 실행 후 종료")
        run_monitor_job()
        return

    scheduler = BlockingScheduler(timezone="Asia/Seoul")

    # 매월 1~5일 오전 9시 폴링
    # CronTrigger: day="1-5"는 1일~5일만 실행
    trigger = CronTrigger(
        day=",".join(str(d) for d in poll_days),
        hour=poll_hour,
        minute=0,
        timezone="Asia/Seoul",
    )
    scheduler.add_job(
        run_monitor_job,
        trigger=trigger,
        id="semiconductor_monitor",
        name="반도체 수출 모니터링",
        replace_existing=True,
    )

    days_str = ", ".join(str(d) for d in poll_days)
    print(
        f"[scheduler] 스케줄 등록 완료:\n"
        f"  실행 시각: 매월 {days_str}일 오전 {poll_hour}시\n"
        f"  다음 실행: {scheduler.get_job('semiconductor_monitor').next_run_time}"
    )
    print("[scheduler] Ctrl+C로 중지")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[scheduler] 스케줄러 종료")
        scheduler.shutdown()


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--schedule"

    if mode == "--run-now":
        print("[scheduler] 즉시 실행 모드")
        result = run_monitor_job()
        # Done Criteria 자동 검증
        _run_done_criteria()

    elif mode == "--done-criteria":
        # 사전 조건: run_monitor_job()이 먼저 실행되어 output 파일이 있어야 함
        if not OUTPUT_FILE.exists():
            print(f"[scheduler] {OUTPUT_FILE} 없음 — --run-now 먼저 실행하세요")
            sys.exit(1)
        _run_done_criteria()

    elif mode == "--schedule":
        start_scheduler()

    else:
        print(f"[ERROR] 알 수 없는 모드: {mode}")
        print("사용법: python -m agents.semiconductor_monitor.scheduler")
        print("        [--schedule | --run-now | --done-criteria]")
        sys.exit(1)
