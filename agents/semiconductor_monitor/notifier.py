# -*- coding: utf-8 -*-
"""
semiconductor_monitor/notifier.py — Telegram 알림 발송

PM Agent 결정 사항:
  [D3] ±10% MoM 초과 시만 알림
       이유: 월별 데이터 특성상 매번 알림은 과도함
  [D4] agents/semiconductor_monitor/ 디렉토리
       이유: 기존 agents/ 패턴 유지

구현 방침:
  run_telegram_agent._telegram_api import 재사용 (중복 작성 금지)
  알림 조건: abs(MoM 변화율) > threshold_pct (기본 10.0%)
"""

import io
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

# run_telegram_agent._telegram_api 재사용 (중복 작성 금지)
sys.path.insert(0, str(Path(__file__).parent.parent))
from run_telegram_agent import _telegram_api  # noqa: E402

CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def _build_alert_message(export_data: dict, analysis: str) -> str:
    """알림 메시지 빌드 (HTML 포맷)."""
    summary = export_data.get("summary", {})
    mom = summary.get("mom_change_pct", 0.0)
    yoy = summary.get("yoy_change_pct", 0.0)
    latest_val = summary.get("latest_value", 0.0)
    latest_month = summary.get("latest_month", "")
    share_pct = summary.get("export_share_pct", 0.0)
    is_mock = export_data.get("is_mock", False)

    # 월 레이블
    if len(latest_month) == 6:
        month_label = f"{latest_month[:4]}년 {latest_month[4:]}월"
    else:
        month_label = latest_month

    # MoM 방향 이모지
    if mom > 0:
        mom_emoji = "📈"
        mom_str = f"+{mom:.1f}%"
    else:
        mom_emoji = "📉"
        mom_str = f"{mom:.1f}%"

    mock_notice = "\n<i>⚠ mock 데이터 (ECOS_API_KEY 미설정)</i>" if is_mock else ""
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    lines = [
        f"{mom_emoji} <b>반도체 수출 이상 변동 감지</b>",
        f"<i>{month_label}</i>",
        "",
        f"<b>수출액:</b> {latest_val:,.0f} 백만달러",
        f"<b>MoM 변화:</b> {mom_str}  (YoY {yoy:+.1f}%)",
        f"<b>수출 비중:</b> {share_pct:.1f}%",
        "",
        "<b>AI 분석:</b>",
        analysis,
        mock_notice,
        "",
        f"<i>{now_str} | AI Analyzer — 반도체 수출 모니터</i>",
    ]
    return "\n".join(lines)


def send_alert(
    export_data: dict,
    analysis: str,
    threshold_pct: float = 10.0,
) -> bool:
    """
    [D3] ±10% MoM 초과 시만 알림 발송.

    Args:
        export_data: fetch_semiconductor_export() 반환값
        analysis: analyze_export_data() 반환값 (한국어 분석 텍스트)
        threshold_pct: 알림 임계값 (MoM 절댓값, 기본 10.0%)

    Returns:
        True — 알림 발송됨
        False — 임계값 미달 또는 발송 실패
    """
    summary = export_data.get("summary", {})
    mom = summary.get("mom_change_pct", 0.0)

    # [D3] 임계값 조건 확인
    if abs(mom) <= threshold_pct:
        print(
            f"[notifier] MoM {mom:+.1f}% — 임계값 {threshold_pct:.1f}% 미초과, 알림 생략"
        )
        return False

    direction = "급증" if mom > 0 else "급감"
    print(
        f"[notifier] MoM {mom:+.1f}% {direction} 감지 "
        f"(임계값 ±{threshold_pct:.1f}%) — Telegram 알림 발송"
    )

    if not CHAT_ID:
        print("[notifier] TELEGRAM_CHAT_ID 없음 — 알림 건너뜀")
        return False

    try:
        msg = _build_alert_message(export_data, analysis)
        result = _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
        })
        message_id = result.get("result", {}).get("message_id")
        print(f"[notifier] Telegram 전송 완료 — message_id={message_id}")
        return True
    except Exception as exc:
        print(f"[notifier] Telegram 전송 실패: {exc}")
        return False


def send_monthly_summary(export_data: dict, analysis: str) -> bool:
    """
    매월 정기 요약 발송 (임계값 무관, 월초 정기 리포트용).

    Returns:
        True — 발송 성공
        False — 발송 실패
    """
    if not CHAT_ID:
        print("[notifier] TELEGRAM_CHAT_ID 없음 — 요약 건너뜀")
        return False

    summary = export_data.get("summary", {})
    mom = summary.get("mom_change_pct", 0.0)
    yoy = summary.get("yoy_change_pct", 0.0)
    latest_val = summary.get("latest_value", 0.0)
    latest_month = summary.get("latest_month", "")
    is_mock = export_data.get("is_mock", False)

    if len(latest_month) == 6:
        month_label = f"{latest_month[:4]}년 {latest_month[4:]}월"
    else:
        month_label = latest_month

    mock_notice = "\n<i>⚠ mock 데이터 (ECOS_API_KEY 미설정)</i>" if is_mock else ""
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    lines = [
        "📊 <b>반도체 수출 월간 리포트</b>",
        f"<i>{month_label}</i>",
        "",
        f"<b>수출액:</b> {latest_val:,.0f} 백만달러",
        f"<b>MoM:</b> {mom:+.1f}%  |  <b>YoY:</b> {yoy:+.1f}%",
        "",
        "<b>분석:</b>",
        analysis,
        mock_notice,
        "",
        f"<i>{now_str} | AI Analyzer — 반도체 수출 모니터</i>",
    ]
    msg = "\n".join(lines)

    try:
        result = _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
        })
        message_id = result.get("result", {}).get("message_id")
        print(f"[notifier] 월간 요약 전송 완료 — message_id={message_id}")
        return True
    except Exception as exc:
        print(f"[notifier] 월간 요약 전송 실패: {exc}")
        return False


if __name__ == "__main__":
    # 테스트: mock 데이터로 임계값 초과 시나리오
    mock_data = {
        "is_mock": True,
        "summary": {
            "latest_month": "202405",
            "latest_value": 12500.0,
            "mom_change_pct": 12.5,
            "yoy_change_pct": 18.0,
            "export_share_pct": 18.4,
        },
    }
    sent = send_alert(mock_data, "테스트 분석: 반도체 수출 급증세. 투자시사점: 반도체 비중 확대 고려.", threshold_pct=10.0)
    print(f"[테스트] 알림 발송: {sent}")
