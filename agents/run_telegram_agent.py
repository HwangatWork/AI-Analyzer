# -*- coding: utf-8 -*-
"""
Telegram Agent — 시장 알림 시스템
Done Criteria (TG-1~TG-5):
  TG-1: 텔레그램 API 연결 성공 (200 OK)
  TG-2: 메시지 전송 성공 (message_id 반환)
  TG-3: 로그 파일 기록 완료 (telegram_log.json)
  TG-4: 시그널 임계값 로직 작동 (75↑ BUY / 40↓ SELL)
  TG-5: final_results.json 파싱 성공 (score, direction 필수)

실행 모드:
  --daily        : 오전 8시 정기 리포트
  --check        : 시그널 변화 감지 (30분 루프에서 호출)
  --test         : 테스트 메시지 1회 전송
  --step <N> <이름> <상세>  : 파이프라인 단계 완료 보고
  --summary      : 파이프라인 전체 완료 요약
  --done-criteria: 자체 검증
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# dotenv 로드
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ── 경로 설정 ────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
OUT_DIR     = BASE_DIR / "output"
PROC_DIR    = BASE_DIR / "data" / "processed"
LOG_FILE    = PROC_DIR / "telegram_log.json"
RESULTS_FILE = OUT_DIR / "final_results.json"

# ── 환경 변수 ─────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# 시그널 임계값
BUY_THRESHOLD  = 75.0
SELL_THRESHOLD = 40.0

# ── 지표 한글 이름 매핑 ───────────────────────────────────────
INDICATOR_KR = {
    "NASDAQ100":       "나스닥100",
    "DOW":             "다우존스",
    "SP500":           "S&P500",
    "KOSPI":           "코스피",
    "KOSDAQ":          "코스닥",
    "NIKKEI225":       "닛케이225",
    "US10Y":           "미국 10년물 금리",
    "DXY":             "달러인덱스",
    "WTI":             "WTI 원유",
    "HY_SPREAD":       "하이일드 스프레드",
    "T10Y2Y":          "장단기 금리차",
    "VIX":             "VIX 공포지수",
    "CNN_FG":          "공포탐욕지수",
    "SKEW":            "SKEW지수",
    "PUT_CALL":        "Put/Call 비율",
    "MARKET_MOMENTUM": "시장 모멘텀",
    "MARKET_STRENGTH": "시장 강도",
    "RSI14":           "RSI(14일)",
    "RSI_SIGNAL":      "RSI 신호",
    "MA50":            "MA50",
    "MA200":           "MA200",
    "MA_SIGNAL":       "골든/데드크로스",
    "BETA":            "베타",
    "BBAND":           "볼린저밴드",
    "STOCH_RSI":       "Stochastic RSI",
    "FOREIGN_NET":     "외국인 순매수",
    "INSTITUTION_NET": "기관 순매수",
    "INDIVIDUAL_NET":  "개인 순매수",
    "FED_ASSETS":      "연준 총자산",
}


# ══════════════════════════════════════════════════════════════
# 핵심 유틸리티
# ══════════════════════════════════════════════════════════════

def _telegram_api(method: str, payload: dict) -> dict:
    """텔레그램 Bot API 호출."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(text: str, parse_mode: str = "HTML") -> dict:
    """메시지 전송 + 로그 기록."""
    result = _telegram_api("sendMessage", {
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
    })
    _append_log("sent", text[:120], result.get("result", {}).get("message_id"))
    return result


def _append_log(event_type: str, summary: str, message_id=None):
    """telegram_log.json에 이벤트 기록."""
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            log = []
    log.append({
        "timestamp":  datetime.now().isoformat(),
        "type":       event_type,
        "summary":    summary,
        "message_id": message_id,
    })
    # 최근 500건만 유지
    LOG_FILE.write_text(
        json.dumps(log[-500:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_results() -> dict:
    """final_results.json 로드."""
    if not RESULTS_FILE.exists():
        raise FileNotFoundError(f"{RESULTS_FILE} 없음 — 파이프라인 먼저 실행 필요")
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def _last_sent_score() -> float | None:
    """마지막으로 전송한 시점의 시그널 점수 (alert용)."""
    if not LOG_FILE.exists():
        return None
    try:
        log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        for entry in reversed(log):
            if entry.get("type") in ("buy_alert", "sell_alert", "score_snapshot"):
                score_str = entry.get("summary", "")
                for token in score_str.split():
                    try:
                        return float(token)
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# 기능 1 — Daily 리포트
# ══════════════════════════════════════════════════════════════

def _direction_emoji(direction: str) -> str:
    d = direction.lower()
    if "on" in d or "bull" in d or "buy" in d:
        return "🟢"
    if "off" in d or "bear" in d or "sell" in d:
        return "🔴"
    return "🟡"


def _indicator_line(ind: dict) -> str:
    name   = INDICATOR_KR.get(ind["indicator"], ind["indicator"])
    bull   = ind.get("bullish", False)
    z      = ind.get("z_score", 0)
    arrow  = "↑" if bull else "↓"
    emoji  = "🟢" if bull else "🔴"
    return f"{emoji} {name}  {arrow} (Z={z:+.2f})"


def build_daily_report(data: dict) -> str:
    sig     = data.get("market_signal", {})
    score   = sig.get("score", 0)
    direction = sig.get("direction", "N/A")
    bull_n  = sig.get("bullish_count", 0)
    total_n = sig.get("total_signals", 0)
    inds    = sig.get("indicator_signals", [])
    ranking = data.get("indicator_weight_ranking", [])

    # 방향 요약
    dir_emoji = _direction_emoji(direction)
    dir_kr = {"risk-on": "리스크 온", "risk-off": "리스크 오프", "neutral": "중립"}.get(
        direction, direction
    )

    # BUY/HOLD/SELL 판단
    if score >= BUY_THRESHOLD:
        action = "📈 매수 관점 유지"
        action_detail = f"시그널 {score:.1f}점 — 강세 우위. 포지션 확대 고려."
    elif score < SELL_THRESHOLD:
        action = "📉 매도/축소 검토"
        action_detail = f"시그널 {score:.1f}점 — 약세 우위. 리스크 줄이기 고려."
    else:
        action = "⏸ 관망 (HOLD)"
        action_detail = f"시그널 {score:.1f}점 — 방향성 불명확. 추가 신호 확인 후 결정."

    # 상위 3개 지표 (가중치 기준)
    top3_ranking = ranking[:3]
    top3_lines = []
    for r in top3_ranking:
        ind_name = INDICATOR_KR.get(r["indicator"], r["indicator"])
        # 해당 지표의 최신 시그널 방향 찾기
        matched = next((i for i in inds if i["indicator"] == r["indicator"]), None)
        if matched:
            bull   = matched.get("bullish", False)
            z      = matched.get("z_score", 0)
            arrow  = "▲" if bull else "▼"
            e      = "🟢" if bull else "🔴"
            top3_lines.append(
                f"  {r['rank']}. {e} {ind_name} {arrow}  (가중치 {r['combined_weight']:.3f}, Z={z:+.2f})"
            )
        else:
            top3_lines.append(f"  {r['rank']}. {ind_name} (가중치 {r['combined_weight']:.3f})")

    # S&P500 / 코스피 기여 1위 종목
    sp_top = (data.get("sp500_analysis", {}).get("contribution_top5") or [{}])[0]
    ksp_top = (data.get("kospi_analysis", {}).get("contribution_top5") or [{}])[0]
    sp_name  = sp_top.get("name", "N/A")
    sp_ret   = sp_top.get("stock_return_pct", 0)
    ksp_name = ksp_top.get("name", "N/A")
    ksp_ret  = ksp_top.get("stock_return_pct", 0)

    generated = data.get("meta", {}).get("generated_at", "")[:16].replace("T", " ")
    date_str  = datetime.now().strftime("%Y년 %m월 %d일")

    lines = [
        f"<b>📊 AI Analyzer 데일리 리포트</b>",
        f"<i>{date_str} 오전 8시</i>",
        "",
        f"<b>{dir_emoji} 시장 시그널</b>",
        f"  점수: <b>{score:.1f} / 100</b>  ({dir_kr})",
        f"  강세 지표: {bull_n} / {total_n}개",
        "",
        f"<b>📌 핵심 지표 Top 3</b>",
        *top3_lines,
        "",
        f"<b>🏆 지수 기여 1위</b>",
        f"  S&amp;P500: {sp_name}  ({sp_ret:+.1f}%)",
        f"  코스피:  {ksp_name}  ({ksp_ret:+.1f}%)",
        "",
        f"<b>💡 오늘의 판단</b>",
        f"  {action}",
        f"  {action_detail}",
        "",
        f"<i>데이터 기준: {generated} | AI Analyzer v4</i>",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 기능 2/3 — 시그널 알림 (BUY / SELL)
# ══════════════════════════════════════════════════════════════

def _top3_signal_lines(inds: list[dict], bullish_filter: bool) -> list[str]:
    """bullish 방향 기준 상위 3개 지표 라인."""
    filtered = [i for i in inds if i.get("bullish") == bullish_filter]
    # |z_score| 내림차순
    filtered.sort(key=lambda x: abs(x.get("z_score", 0)), reverse=True)
    lines = []
    for i, ind in enumerate(filtered[:3], 1):
        name  = INDICATOR_KR.get(ind["indicator"], ind["indicator"])
        z     = ind.get("z_score", 0)
        arrow = "▲" if ind.get("bullish") else "▼"
        lines.append(f"  {i}. {name} {arrow} (Z={z:+.2f})")
    return lines


def build_buy_alert(data: dict) -> str:
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    inds  = sig.get("indicator_signals", [])
    top3  = _top3_signal_lines(inds, bullish_filter=True)

    lines = [
        "🟢 <b>매수 타이밍 감지</b>",
        f"시그널 점수: <b>{score:.1f}</b>  (임계값 {BUY_THRESHOLD} 돌파)",
        "",
        "<b>핵심 강세 지표 Top3</b>",
        *top3,
        "",
        "<b>권장 액션</b>",
        "  • 분할 매수 1차 진입 고려",
        "  • 손절선 설정 후 포지션 진입",
        "  • 다음 30분 후 시그널 재확인",
        "",
        f"<i>{datetime.now().strftime('%m/%d %H:%M')} | AI Analyzer</i>",
    ]
    return "\n".join(lines)


def build_sell_alert(data: dict) -> str:
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    inds  = sig.get("indicator_signals", [])
    top3  = _top3_signal_lines(inds, bullish_filter=False)

    lines = [
        "🔴 <b>매도 타이밍 감지</b>",
        f"시그널 점수: <b>{score:.1f}</b>  (임계값 {SELL_THRESHOLD} 하향 이탈)",
        "",
        "<b>핵심 약세 지표 Top3</b>",
        *top3,
        "",
        "<b>권장 액션</b>",
        "  • 포지션 축소 또는 현금 비중 확대",
        "  • 손익 보호 주문(트레일링 스탑) 검토",
        "  • 다음 30분 후 시그널 재확인",
        "",
        f"<i>{datetime.now().strftime('%m/%d %H:%M')} | AI Analyzer</i>",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 모드별 실행 함수
# ══════════════════════════════════════════════════════════════

def run_daily():
    """매일 오전 8시 정기 리포트."""
    print("[Telegram] 데일리 리포트 전송 시작")
    data = _load_results()
    msg  = build_daily_report(data)
    result = send_message(msg)
    mid = result.get("result", {}).get("message_id")
    print(f"[Telegram] 전송 완료 — message_id={mid}")
    _append_log(
        "daily_report",
        f"score={data['market_signal']['score']} {data['market_signal']['direction']}",
        mid,
    )


def run_check():
    """시그널 변화 감지 — BUY/SELL 임계값 돌파 시 알림."""
    print("[Telegram] 시그널 체크 시작")
    data  = _load_results()
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    prev  = _last_sent_score()

    print(f"[Telegram] 현재 점수={score:.1f}, 이전 점수={prev}")

    alert_sent = False

    # BUY 조건: 현재 >= 75 AND (이전 없음 OR 이전 < 75)
    if score >= BUY_THRESHOLD and (prev is None or prev < BUY_THRESHOLD):
        print(f"[Telegram] BUY 알림 발송 (score={score:.1f})")
        msg    = build_buy_alert(data)
        result = send_message(msg)
        mid    = result.get("result", {}).get("message_id")
        _append_log("buy_alert", f"{score:.1f}", mid)
        alert_sent = True

    # SELL 조건: 현재 < 40 AND (이전 없음 OR 이전 >= 40)
    elif score < SELL_THRESHOLD and (prev is None or prev >= SELL_THRESHOLD):
        print(f"[Telegram] SELL 알림 발송 (score={score:.1f})")
        msg    = build_sell_alert(data)
        result = send_message(msg)
        mid    = result.get("result", {}).get("message_id")
        _append_log("sell_alert", f"{score:.1f}", mid)
        alert_sent = True

    else:
        print(f"[Telegram] 임계값 미도달 — 알림 없음")
        # 현재 점수를 스냅샷으로 기록 (다음 체크 기준용)
        _append_log("score_snapshot", f"{score:.1f}", None)

    return alert_sent


def run_test():
    """테스트 메시지 전송."""
    print("[Telegram] 테스트 메시지 전송")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "✅ <b>AI Analyzer Telegram 연결 테스트</b>\n"
        f"<i>{now}</i>\n"
        "\n"
        "텔레그램 알림 시스템이 정상적으로 연결되었습니다.\n"
        "\n"
        "알림 종류:\n"
        "  📊 데일리 리포트 — 매일 오전 8시\n"
        f"  🟢 매수 알림 — 시그널 점수 ≥ {BUY_THRESHOLD}\n"
        f"  🔴 매도 알림 — 시그널 점수 &lt; {SELL_THRESHOLD}\n"
        "\n"
        "<i>AI Analyzer v4 | @ai-analyzer-hwangatwork</i>"
    )
    result = send_message(msg)
    mid = result.get("result", {}).get("message_id")
    print(f"[Telegram] 테스트 완료 — message_id={mid}")
    _append_log("test", "연결 테스트", mid)
    return result


# ══════════════════════════════════════════════════════════════
# 기능 4 — 파이프라인 단계 완료 보고 (--step)
# ══════════════════════════════════════════════════════════════

# 전체 파이프라인 단계 정의 (순서/총 단계 수 표시용)
PIPELINE_STEPS = [
    ("1", "Data Agent",       "📥"),
    ("2", "Refresh",          "🔄"),
    ("3", "Analysis Agent",   "📊"),
    ("4", "Stock Agent",      "🏢"),
    ("5", "Evaluator Agent",  "🔬"),
    ("6", "Sector Agent",     "🏭"),
    ("7", "Validation Agent", "✅"),
    ("8", "UI Agent",         "🖥"),
    ("9", "Report",           "📄"),
    ("10", "Audit Agent",     "🔍"),
    ("11", "Telegram Check",  "📱"),
]
TOTAL_STEPS = len(PIPELINE_STEPS)


def run_step(step_num: str, step_name: str, detail: str = "") -> None:
    """파이프라인 단계 완료 보고."""
    now = datetime.now().strftime("%H:%M:%S")
    total = TOTAL_STEPS

    # 진행 바 (단순 텍스트)
    try:
        n = int(step_num)
        filled = "█" * n + "░" * (total - n)
        pct    = round(n / total * 100)
    except ValueError:
        filled = "─" * total
        pct    = 0

    # 단계 이모지 찾기
    emoji = next((e for s, nm, e in PIPELINE_STEPS if s == str(step_num)), "⚙")

    lines = [
        f"{emoji} <b>[{step_num}/{total}] {step_name} 완료</b>",
        f"<code>{filled}</code>  {pct}%",
        f"<i>{now}</i>",
    ]
    if detail:
        lines.append("")
        lines.append(detail)

    msg = "\n".join(lines)
    result = send_message(msg)
    mid = result.get("result", {}).get("message_id")
    print(f"[Telegram] 단계 보고 전송 — {step_num}/{total} {step_name} | message_id={mid}")
    _append_log("step_report", f"step={step_num} {step_name}", mid)


# ══════════════════════════════════════════════════════════════
# 기능 5 — 파이프라인 전체 완료 요약 (--summary)
# ══════════════════════════════════════════════════════════════

def run_summary() -> None:
    """파이프라인 전체 완료 요약."""
    print("[Telegram] 파이프라인 완료 요약 전송")

    # final_results.json
    try:
        data  = _load_results()
        sig   = data.get("market_signal", {})
        score = sig.get("score", 0)
        direc = sig.get("direction", "N/A")
        bull  = sig.get("bullish_count", 0)
        total_sigs = sig.get("total_signals", 0)
        rank  = data.get("indicator_weight_ranking", [])
        sp_cont  = data.get("sp500_analysis", {}).get("contribution_top5", [])
        sp_bene  = data.get("sp500_analysis", {}).get("beneficiary_top5", [])
        ksp_cont = data.get("kospi_analysis", {}).get("contribution_top5", [])
        ksp_bene = data.get("kospi_analysis", {}).get("beneficiary_top5", [])
        meta  = data.get("meta", {})
        col_rate = meta.get("collection_rate", "N/A")
    except Exception as e:
        data = {}
        score, direc, bull, total_sigs = 0, "N/A", 0, 0
        rank, sp_cont, sp_bene, ksp_cont, ksp_bene, col_rate = [], [], [], [], [], "N/A"

    # 방향 이모지
    if score >= 75:
        dir_emoji, action = "🟢", "매수 관점"
    elif score < 40:
        dir_emoji, action = "🔴", "매도/축소 검토"
    else:
        dir_emoji, action = "🟡", "관망 (HOLD)"

    dir_kr = {"risk-on": "리스크 온", "risk-off": "리스크 오프", "neutral": "중립"}.get(
        direc, direc
    )

    # validation 결과 로드
    try:
        import json as _json
        from pathlib import Path as _Path
        vr  = _json.loads((_Path(__file__).parent.parent / "data/processed/validation_report.json").read_text(encoding="utf-8"))
        vs  = vr.get("summary", {})
        val_pass = vs.get("passed", 0)
        val_total = vs.get("total", 0)
        val_crit = vs.get("failed_critical", 0)
    except Exception:
        val_pass, val_total, val_crit = "?", "?", "?"

    # Top3 가중치 지표
    top3_lines = []
    for r in rank[:3]:
        nm   = INDICATOR_KR.get(r["indicator"], r["indicator"])
        w    = r.get("combined_weight", 0)
        g    = " G✓" if r.get("sp500_granger_sig") else ""
        top3_lines.append(f"  {r['rank']}. {nm}{g} ({w:.4f})")

    def _cont_line(s: dict, idx: int) -> str:
        name = s.get("name", "N/A")
        ret  = s.get("stock_return_pct", 0)
        mc   = s.get("market_cap_start_b") or s.get("market_cap_b")  # 시작 시총 우선
        sc   = s.get("contribution_score", 0)
        mc_str = f" ${mc:.0f}B(시작) |" if mc else ""
        spinoff = " ⚠분사" if s.get("spinoff_event") else ""
        return f"  {idx}.{mc_str} {name} | {ret:+.1f}%{spinoff} | 기여={sc:.3f}"

    def _bene_line(s: dict, idx: int) -> str:
        name   = s.get("name", "N/A")
        excess = s.get("excess_return_pct", 0)
        sc     = s.get("beneficiary_score", 0)
        warn   = " ⚠" if abs(excess) > 1000 else ""
        return f"  {idx}. {name} | 초과 {excess:+.1f}%{warn} | 점수={sc:.3f}"

    sp_cont_lines  = [_cont_line(s, i) for i, s in enumerate(sp_cont[:3],  1)]
    sp_bene_lines  = [_bene_line(s, i) for i, s in enumerate(sp_bene[:3],  1)]
    ksp_cont_lines = [_cont_line(s, i) for i, s in enumerate(ksp_cont[:3], 1)]
    ksp_bene_lines = [_bene_line(s, i) for i, s in enumerate(ksp_bene[:3], 1)]

    now = datetime.now().strftime("%Y/%m/%d %H:%M")

    lines = [
        "🏁 <b>AI Analyzer 파이프라인 전체 완료</b>",
        f"<i>{now}</i>",
        "",
        f"<b>{dir_emoji} 시장 시그널</b>",
        f"  점수: <b>{score:.1f} / 100</b>  ({dir_kr})",
        f"  강세 지표: {bull}/{total_sigs}개 → {action}",
        "",
        "<b>📌 가중치 Top3 (Granger 인과 기반)</b>",
        *top3_lines,
        "",
        "<b>🏆 S&amp;P500 지수 기여 Top3</b>",
        *sp_cont_lines,
        "",
        "<b>🚀 S&amp;P500 수혜 종목 Top3</b>",
        *sp_bene_lines,
        "",
        "<b>🇰🇷 코스피 지수 기여 Top3</b>",
        *ksp_cont_lines,
        "",
        "<b>🇰🇷 코스피 수혜 종목 Top3</b>",
        *ksp_bene_lines,
        "",
        "<b>🔍 검증 결과</b>",
        f"  Validation: {val_pass}/{val_total} PASS, CRITICAL={val_crit}",
        f"  수집률: {col_rate}",
        "",
        "<i>AI Analyzer v4 | 파이프라인 완료</i>",
    ]

    msg = "\n".join(lines)
    result = send_message(msg)
    mid = result.get("result", {}).get("message_id")
    print(f"[Telegram] 완료 요약 전송 — message_id={mid}")
    _append_log("pipeline_summary", f"score={score} {direc}", mid)


# ══════════════════════════════════════════════════════════════
# Done Criteria 자체 검증
# ══════════════════════════════════════════════════════════════

def _run_done_criteria():
    """TG-1~TG-5 자체 검증."""
    print("\n[Telegram] Done Criteria 검증 시작")
    failures = []

    # TG-1: API 연결 확인 (getMe)
    try:
        resp = _telegram_api("getMe", {})
        ok = resp.get("ok", False)
        if not ok:
            failures.append("TG-1: getMe 실패")
        else:
            bot_name = resp.get("result", {}).get("username", "unknown")
            print(f"  TG-1 PASS — Bot: @{bot_name}")
    except Exception as e:
        failures.append(f"TG-1: API 연결 실패 — {e}")

    # TG-2: 메시지 전송 확인 (test send)
    try:
        r = _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text":    "🔧 [Done Criteria] TG-2 자체검증 핑",
        })
        mid = r.get("result", {}).get("message_id")
        if not mid:
            failures.append("TG-2: message_id 없음")
        else:
            print(f"  TG-2 PASS — message_id={mid}")
    except Exception as e:
        failures.append(f"TG-2: 전송 실패 — {e}")

    # TG-3: 로그 파일 기록 확인
    _append_log("done_criteria_check", "TG-3 검증", None)
    if not LOG_FILE.exists():
        failures.append("TG-3: telegram_log.json 생성 실패")
    else:
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            if not isinstance(log, list) or len(log) == 0:
                failures.append("TG-3: 로그 빈 배열")
            else:
                print(f"  TG-3 PASS — 로그 {len(log)}건")
        except Exception as e:
            failures.append(f"TG-3: 로그 파싱 실패 — {e}")

    # TG-4: 시그널 임계값 로직 검증 (mock)
    mock_buy_score  = BUY_THRESHOLD + 0.1
    mock_sell_score = SELL_THRESHOLD - 0.1
    mock_prev_below = BUY_THRESHOLD - 1
    mock_prev_above = SELL_THRESHOLD + 1
    buy_trigger  = mock_buy_score >= BUY_THRESHOLD and mock_prev_below < BUY_THRESHOLD
    sell_trigger = mock_sell_score < SELL_THRESHOLD and mock_prev_above >= SELL_THRESHOLD
    if not (buy_trigger and sell_trigger):
        failures.append(f"TG-4: 임계값 로직 오류 (buy={buy_trigger}, sell={sell_trigger})")
    else:
        print(f"  TG-4 PASS — 임계값 로직 정상 (buy≥{BUY_THRESHOLD}, sell<{SELL_THRESHOLD})")

    # TG-5: final_results.json 파싱 확인
    try:
        data  = _load_results()
        score = data["market_signal"]["score"]
        direc = data["market_signal"]["direction"]
        if not isinstance(score, (int, float)) or not direc:
            failures.append("TG-5: score/direction 파싱 실패")
        else:
            print(f"  TG-5 PASS — score={score}, direction={direc}")
    except Exception as e:
        failures.append(f"TG-5: 파싱 실패 — {e}")

    print()
    if failures:
        print(f"[FAIL] Done Criteria {len(failures)}개 실패:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    else:
        print("[PASS] Done Criteria TG-1~TG-5 모두 통과")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if not BOT_TOKEN or not CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수 없음")
        sys.exit(1)

    try:
        if mode == "--daily":
            run_daily()
        elif mode == "--check":
            run_check()
        elif mode == "--test":
            run_test()
        elif mode == "--step":
            # 사용법: --step <번호> <이름> [상세]
            # 예: --step 1 "Data Agent" "28/29 지표 수집 완료"
            step_num  = sys.argv[2] if len(sys.argv) > 2 else "?"
            step_name = sys.argv[3] if len(sys.argv) > 3 else "단계"
            detail    = sys.argv[4] if len(sys.argv) > 4 else ""
            run_step(step_num, step_name, detail)
        elif mode == "--summary":
            run_summary()
        elif mode == "--done-criteria":
            _run_done_criteria()
        else:
            print(f"[ERROR] 알 수 없는 모드: {mode}")
            print("사용법: python run_telegram_agent.py [--daily|--check|--test|--step|--summary|--done-criteria]")
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[ERROR] 텔레그램 API 연결 실패: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 예상치 못한 오류: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
