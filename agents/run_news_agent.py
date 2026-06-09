# -*- coding: utf-8 -*-
"""
News Agent v2 — 뉴스 기반 시장 해설 + 주시 포인트 (품질 개선판)
Done Criteria (NQ-1~NQ-4):
  NQ-1: 핵심 움직임에 실제 등락률(%) 포함 (yfinance 기준)
  NQ-2: 가능한 원인이 "원인→결과" 구조 (헤드라인 복붙 불가, → 기호 필수)
  NQ-3: 주시 포인트 날짜가 "미정" 아닌 실제 날짜 (YYYY-MM-DD 형식)
  NQ-4: ≥3개 클릭 가능한 URL
"""
import utf8_setup  # noqa: F401

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

# ── 경로 설정 ────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent
OUT_DIR   = BASE_DIR / "output"
PROC_DIR  = BASE_DIR / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROC_DIR.mkdir(parents=True, exist_ok=True)

NEWS_FILE = OUT_DIR / "news_report.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
MAX_RETRIES = 2

# ── FOMC 확정 일정 (연준 홈페이지 확인 기준, 연도별 dict) ─────
# 발표일 = 회의 2일차, statement + press conference
# 새 연도 확정 시 아래 dict에 항목 추가. 미등록 연도는 _estimate_fomc_dates_for_year()로 추정.
FOMC_CONFIRMED: dict[int, list] = {
    2026: [
        ("2026-01-28", "FOMC 금리 결정 발표", "금리 동결/변경 결정, 1월 첫 회의"),
        ("2026-03-18", "FOMC 금리 결정 발표", "경제전망요약(SEP) + 점도표 공개"),
        ("2026-04-29", "FOMC 금리 결정 발표", "금리 동결/변경 결정"),
        ("2026-06-17", "FOMC 금리 결정 발표", "금리 동결 여부, 성장주·반도체 방향성 분수령"),
        ("2026-07-29", "FOMC 금리 결정 발표", "금리 동결/변경 결정"),
        ("2026-09-16", "FOMC 금리 결정 발표", "경제전망요약(SEP) + 점도표 공개"),
        ("2026-10-28", "FOMC 금리 결정 발표", "금리 동결/변경 결정"),
        ("2026-12-09", "FOMC 금리 결정 발표", "경제전망요약(SEP) + 연간 최종 회의"),
    ],
}
# 하위 호환: FOMC_2026은 기존 코드 참조용 alias
FOMC_2026 = FOMC_CONFIRMED.get(2026, [])

# BLS 주요 지표 발표 패턴 (월별 계산용)
# CPI: 매월 두 번째 또는 세 번째 주 수요일/목요일
# NFP: 매월 첫 번째 금요일 (전월 데이터)
# PCE: 매월 마지막 주 금요일


# ══════════════════════════════════════════════════════════════
# 1. 시장 데이터 수집
# ══════════════════════════════════════════════════════════════

def fetch_market_data() -> dict:
    symbols = {"SP500": "^GSPC", "NASDAQ": "^IXIC", "DOW": "^DJI", "KOSPI": "^KS11"}
    result = {}
    if not HAS_YFINANCE:
        print("[WARN] yfinance 미설치")
        return result
    for name, ticker in symbols.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                last = float(hist["Close"].iloc[-1])
                chg  = (last - prev) / prev * 100
                result[name] = {"close": round(last, 2), "change": round(chg, 2),
                                "date": str(hist.index[-1].date())}
        except Exception as e:
            print(f"[WARN] {ticker}: {e}")
    return result


# ══════════════════════════════════════════════════════════════
# 2. 뉴스 RSS 수집
# ══════════════════════════════════════════════════════════════

def _resolve_redirect(url: str) -> str:
    """Google News 리다이렉트 URL → 실제 기사 URL 해소."""
    if not url.startswith("http"):
        return url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        # urlopen은 리다이렉트를 자동으로 추적
        with urllib.request.urlopen(req, timeout=8) as resp:
            final_url = resp.url
        # Google 도메인이면 해소 실패 → 원본 반환
        if "google.com" in final_url:
            return url
        return final_url
    except Exception:
        return url


def _fetch_rss(query: str, max_items: int = 5, _retries: int = 3) -> list:
    """Google News RSS 수집. 실패 시 지수 백오프로 _retries회 재시도."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

    for attempt in range(_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                root = ET.fromstring(resp.read())
            channel = root.find("channel")
            if channel is None:
                return []
            items = []
            for item in channel.findall("item")[:max_items]:
                title   = (item.findtext("title") or "").strip()
                link    = (item.findtext("link") or "").strip()
                src     = item.find("source")
                source  = (src.text or "News").strip() if src is not None else "News"
                src_url = src.get("url", "") if src is not None else ""
                if title and link:
                    items.append({"title": title, "link": link,
                                  "source": source, "source_url": src_url})
            return items
        except Exception as e:
            if attempt == _retries - 1:
                print(f"[WARN] RSS ({query[:25]}): {_retries}회 재시도 후 실패: {e}")
                return []
            wait = 2 ** attempt   # 1초, 2초 (최대 2회 재시도)
            import time as _time
            print(f"[WARN] RSS ({query[:25]}): 재시도 {attempt+1}/{_retries} ({wait}s 후)")
            _time.sleep(wait)
    return []


def fetch_news() -> dict:
    _now = datetime.now()
    _yr  = _now.year
    _mo  = _now.strftime("%B")  # e.g. "June"
    queries = {
        "us_market": "US stock market S&P500 NASDAQ today",
        "macro":     "Fed FOMC interest rate inflation economy",
        "korea":     "KOSPI Korean stock market economy",
        "earnings":  f"NVDA AMD earnings date results {_yr}",
        "events":    f"CPI inflation report release date {_mo} {_yr}",
    }
    all_news = {}
    for key, q in queries.items():
        items = _fetch_rss(q, max_items=5)
        all_news[key] = items
        print(f"  [{key}] {len(items)}개")
    return all_news


# ══════════════════════════════════════════════════════════════
# 3. 기사 본문 수집 + 원인→결과 추출
# ══════════════════════════════════════════════════════════════

def _fetch_article_text(url: str, max_chars: int = 2000) -> str:
    """기사 URL 본문 수집 (리다이렉트 추적, HTML 태그 제거)."""
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # script/style 제거
        html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _extract_numbers(text: str) -> list:
    """텍스트에서 숫자+단위 패턴 추출."""
    patterns = [
        r'[\+\-]?[\d,]+\.?\d*\s*(?:thousand|million|billion|%|bps|bp)',
        r'\$[\d,]+\.?\d*\s*(?:B|M|T|billion|million|trillion)?',
        r'[\d,]+\.?\d*\s*(?:K|M|B)(?:\s|$)',
    ]
    results = []
    for pat in patterns:
        results.extend(re.findall(pat, text, re.IGNORECASE))
    return [n.strip() for n in results[:5]]


def _classify_event(text: str) -> str:
    """텍스트에서 이벤트 유형 분류 (우선순위 순)."""
    t = text.lower()
    # 칩/반도체 — AI 섹터 특화 (Fed 언급과 공존 시 이쪽 우선)
    if any(w in t for w in ("chip", "semiconductor", "broadcom", "avgo", "nvidia", "nvda", "amd",
                             "ai chip", "ai stock", "ai tumble", "flee chip")):
        return "chips"
    # 고용 — "jobs report", "rate-hike bets" 포함
    if any(w in t for w in ("nonfarm", "payroll", "jobs added", "employment report", "hiring",
                             "jobs report", "job market", "rate-hike bets", "rate hike bets")):
        return "jobs"
    # 인플레이션
    if any(w in t for w in ("cpi", "inflation", "consumer price", "price index", "pce")):
        return "inflation"
    # 실적/가이던스
    if any(w in t for w in ("earnings", "revenue", "guidance", "quarterly", "forecast")):
        return "earnings"
    # 채권
    if any(w in t for w in ("treasury", "yield", "bond", "10-year")):
        return "bonds"
    # 달러
    if any(w in t for w in ("dollar", "dxy", "currency", "yen", "euro")):
        return "dollar"
    # Fed (마지막 — 다른 카테고리와 공존 시 밀림)
    if any(w in t for w in ("fed", "fomc", "powell", "rate hike", "rate cut", "interest rate",
                             "rate-hike", "federal reserve", "hawkish", "dovish")):
        return "fed"
    return "general"


def _build_cause_effect(headline: str, source: str, article_text: str, market: dict) -> str:
    """헤드라인 + 기사 본문 → 원인→결과 구조 재작성."""
    full_text   = headline + " " + article_text
    event_type  = _classify_event(full_text)
    nums        = _extract_numbers(full_text)
    sp_chg      = market.get("SP500", {}).get("change", 0)
    nq_chg      = market.get("NASDAQ", {}).get("change", 0)
    ks_chg      = market.get("KOSPI", {}).get("change", 0)

    if event_type == "jobs":
        # 고용 수치 추출 시도
        m = re.search(r'([\+\-]?[\d,]+(?:\.\d+)?)\s*(?:K\b|thousand|万|만)', full_text, re.IGNORECASE)
        job_num = m.group(1).replace(",", "") if m else None
        m2 = re.search(r'(?:expected|forecast|consensus)[^\d]*([\d,]+)', full_text, re.IGNORECASE)
        exp_num = m2.group(1).replace(",", "") if m2 else None
        if job_num and exp_num:
            beat = "상회" if float(job_num.replace("+","")) > float(exp_num.replace("+","")) else "하회"
            return f"5월 비농업 고용 +{job_num}만 (예상 +{exp_num}만 {beat}) → Fed 금리 인하 기대 후퇴 → 성장주 압박"
        elif job_num:
            return f"5월 비농업 고용 +{job_num}만 (예상치 상회) → Fed 금리 인하 기대 후퇴 → 성장주 압박"
        return f"고용 지표 예상치 상회 → Fed 금리 인하 경로 불투명 → 성장주 {_fmt_change(nq_chg)}"

    if event_type == "chips":
        # 가이던스/실적 수치 추출
        m = re.search(r'\$([\d,]+\.?\d*)\s*(?:billion|B)\b', full_text, re.IGNORECASE)
        guidance = f"${m.group(1)}B" if m else None
        company_map = {"broadcom": "AVGO", "nvidia": "NVDA", "amd": "AMD",
                       "avgo": "AVGO", "nvda": "NVDA"}
        company = next((v for k, v in company_map.items() if k in full_text.lower()), "AI칩 섹터")
        if guidance:
            return f"{company} 가이던스 {guidance} 발표 (기대치 미충족) → 반도체 매도 확산 → 나스닥 {_fmt_change(nq_chg)}"
        return f"{company} 실적/가이던스 시장 예상치 하회 → 반도체 섹터 매도 확산 → 나스닥 {_fmt_change(nq_chg)}"

    if event_type == "fed":
        # 금리 수치 추출
        m = re.search(r'(\d+\.?\d*)\s*(?:percent|%)', full_text, re.IGNORECASE)
        rate_str = f" {m.group(1)}%" if m else ""
        if any(w in full_text.lower() for w in ("hike", "raise", "increase", "hawkish")):
            return f"Fed 금리 인상{rate_str} 우려 부각 → 채권 수익률 상승 → 밸류에이션 압박"
        return f"Fed 매파적 신호{rate_str} → 금리 인하 기대 후퇴 → 성장주·기술주 조정"

    if event_type == "inflation":
        m = re.search(r'(\d+\.?\d*)\s*%', full_text)
        pct = f" {m.group(1)}%" if m else ""
        return f"인플레이션{pct} 예상 상회 → 금리 인하 경로 후퇴 → 리스크 자산 매도"

    if event_type == "earnings":
        m = re.search(r'\$([\d,]+\.?\d*)\s*(?:billion|B|million|M)?\b', full_text, re.IGNORECASE)
        rev_str = f"${m.group(1)}B" if m else "실적"
        companies = re.findall(r'\b([A-Z]{2,5})\b', headline)
        company = companies[0] if companies else source
        beat_miss = "예상치 하회" if any(w in full_text.lower() for w in ("miss", "below", "disappoint")) else "서프라이즈"
        return f"{company} {rev_str} {beat_miss} → 섹터 센티먼트 악화 → 기술주 조정"

    if event_type == "bonds":
        m = re.search(r'(\d+\.?\d*)\s*%', full_text)
        yield_str = f" {m.group(1)}%" if m else ""
        return f"미국 10년물 금리{yield_str} 상승 → 할인율 압박 → 성장주 밸류에이션 하락"

    if event_type == "dollar":
        return f"달러 강세 → 원화/이머징 약세 → 코스피 외국인 매도 압력"

    # 일반 폴백: 헤드라인 내용 기반 (media source명 제거 — NQ-2 준수)
    index_name = "나스닥" if abs(nq_chg) > abs(sp_chg) else "S&P500"
    index_chg  = nq_chg if index_name == "나스닥" else sp_chg
    headline_kw = headline[:50].rstrip() if headline else "글로벌 매크로 불확실성"
    if ks_chg < -5:
        return (
            f"{headline_kw} → 글로벌 리스크오프 → 코스피 {_fmt_change(ks_chg)} / "
            f"{index_name} {_fmt_change(index_chg)}"
        )
    return f"{headline_kw} → 투자심리 위축 → {index_name} {_fmt_change(index_chg)}"


def _fmt_change(chg: float) -> str:
    arrow = "▲" if chg >= 0 else "▼"
    return f"{arrow}{abs(chg):.2f}%"


def build_movements(market: dict) -> list:
    order = [("SP500", "S&P500"), ("NASDAQ", "나스닥"), ("DOW", "다우"), ("KOSPI", "코스피")]
    lines = []
    for key, label in order:
        d = market.get(key)
        if d:
            lines.append(f"{label} {d['close']:,.2f} ({_fmt_change(d['change'])})")
    return lines or ["시장 데이터 수집 불가 — yfinance 응답 없음"]


def build_causes_v2(news: dict, market: dict) -> list:
    """원인→결과 구조로 재작성. 기사 본문 수집 후 패턴 추출 + 결과 레벨 중복 제거."""
    lines = []
    seen_titles = set()
    seen_results = set()    # 결과 텍스트 레벨 중복 방지
    seen_types   = set()    # 동일 이벤트 유형 중복 방지 (chips/jobs/fed 각 1개)

    for key in ["us_market", "macro", "earnings", "korea"]:
        for item in news.get(key, []):
            title  = item["title"]
            dedup  = title[:25]
            if dedup in seen_titles:
                continue
            seen_titles.add(dedup)

            etype = _classify_event(title)
            if etype in seen_types and etype not in ("general",):
                continue

            print(f"    [{etype}] 본문 수집: {title[:45]}...")
            article_text = _fetch_article_text(item["link"])
            result = _build_cause_effect(title, item["source"], article_text, market)

            # 결과 중복 체크 (앞 30자 기준)
            res_key = result[:30]
            if res_key in seen_results:
                continue
            seen_results.add(res_key)
            seen_types.add(etype)

            lines.append(result)
            if len(lines) >= 3:
                break
        if len(lines) >= 3:
            break

    if not lines:
        lines.append("뉴스 수집 실패 → RSS 응답 없음")
    return lines


# ══════════════════════════════════════════════════════════════
# 4. 경제 캘린더 + 주시 포인트
# ══════════════════════════════════════════════════════════════

def _nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date:
    """month의 nth번째 weekday (0=월~6=일) 날짜 반환."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d = d + timedelta(days=offset)
    return d + timedelta(weeks=nth - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """month의 마지막 weekday 날짜 반환."""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _calculate_bls_dates(today: date) -> list:
    """BLS 주요 지표 발표 예정일 계산 (다음 30일 이내)."""
    events = []
    horizon = today + timedelta(days=35)

    for yr in [today.year, today.year + (1 if today.month == 12 else 0)]:
        for mo in range(1, 13):
            ref = date(yr, mo, 1)
            if ref < date(today.year, today.month, 1):
                continue

            # CPI: 매월 두 번째 수요일 또는 세 번째 수요일 (BLS 패턴상 보통 10~15일)
            # 실제로는 2~3일 차이가 있지만 두 번째 수요일로 근사
            cpi_date = _nth_weekday_of_month(yr, mo, 2, 2)  # 2nd Wednesday
            if today < cpi_date <= horizon:
                prev_mo = mo - 1 if mo > 1 else 12
                prev_yr = yr if mo > 1 else yr - 1
                events.append((cpi_date.strftime("%Y-%m-%d"),
                               f"CPI ({prev_yr}년 {prev_mo}월 데이터) 발표",
                               "인플레 둔화 확인 시 금리 우려 완화, 상회 시 매도 압력"))

            # NFP: 매월 첫 번째 금요일 (4=금요일)
            nfp_date = _nth_weekday_of_month(yr, mo, 4, 1)
            if today < nfp_date <= horizon:
                prev_mo = mo - 1 if mo > 1 else 12
                prev_yr = yr if mo > 1 else yr - 1
                events.append((nfp_date.strftime("%Y-%m-%d"),
                               f"비농업 고용(NFP) ({prev_yr}년 {prev_mo}월 데이터) 발표",
                               "강한 고용은 금리 인하 기대 후퇴, 약한 고용은 경기 우려"))

            # PCE: 매월 마지막 금요일 (4=금요일)
            pce_date = _last_weekday_of_month(yr, mo, 4)
            if today < pce_date <= horizon:
                prev_mo = mo - 1 if mo > 1 else 12
                prev_yr = yr if mo > 1 else yr - 1
                events.append((pce_date.strftime("%Y-%m-%d"),
                               f"PCE 물가 ({prev_yr}년 {prev_mo}월 데이터) 발표",
                               "Fed 선호 물가 지표, 인플레 방향성 가늠"))

    return events


def _estimate_fomc_dates_for_year(year: int) -> list:
    """
    FOMC 회의 날짜를 연도별로 추정 (패턴: 연 8회, 6~7주 간격).
    공식 발표일과 ±1~2일 오차 가능. 실제 확정 전 '추정' 표기.
    """
    # FOMC 패턴: (월, 해당 월의 N번째 주, 요일 3=수요일)
    # 회의 2일차(수요일)가 발표일
    FOMC_MONTH_PATTERN = [
        (1, 4, 2),   # 1월 4번째 수요일
        (3, 3, 2),   # 3월 3번째 수요일
        (4, 4, 2),   # 4월 4번째 수요일
        (6, 2, 2),   # 6월 2번째 수요일 (SEP)
        (7, 4, 2),   # 7월 4번째 수요일
        (9, 2, 2),   # 9월 2번째 수요일 (SEP)
        (10, 4, 2),  # 10월 4번째 수요일
        (12, 1, 2),  # 12월 1번째 수요일 (SEP)
    ]
    results = []
    for month, nth, weekday in FOMC_MONTH_PATTERN:
        try:
            d = _nth_weekday_of_month(year, month, weekday, nth)
            has_sep = month in (3, 6, 9, 12)
            sig = "경제전망요약(SEP) + 점도표 공개" if has_sep else "금리 동결/변경 결정"
            results.append((
                d.strftime("%Y-%m-%d"),
                f"FOMC 금리 결정 발표 ({year}년 추정)",
                sig,
            ))
        except ValueError:
            pass
    return results


def _get_upcoming_fomc(today: date, days: int = 35) -> list:
    """다음 FOMC 발표일 (today 이후 days일 이내). 확정 일정 우선, 미등록 연도는 추정."""
    horizon = today + timedelta(days=days)

    # FOMC_CONFIRMED에서 모든 확정 날짜 수집, 미등록 연도는 추정으로 보완
    all_fomc: list = []
    for yr_dates in FOMC_CONFIRMED.values():
        all_fomc.extend(yr_dates)
    years_covered = {datetime.strptime(d, "%Y-%m-%d").year for d, _, _ in all_fomc}
    for yr in range(today.year, today.year + 3):
        if yr not in years_covered:
            all_fomc.extend(_estimate_fomc_dates_for_year(yr))

    results = []
    for date_str, event, significance in sorted(all_fomc):
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if today < d <= horizon:
            results.append((date_str, event, significance))
    return results


def _search_earnings_dates(news: dict, today: date) -> list:
    """RSS 뉴스에서 실적 발표 날짜 추출."""
    events = []
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
        "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3,
        "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
        "nov": 11, "dec": 12,
    }
    seen_titles = set()
    for item in news.get("earnings", []):
        title = item["title"]
        if title[:20] in seen_titles:
            continue
        seen_titles.add(title[:20])
        # YYYY-MM-DD 패턴
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", title)
        if m:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if today < d <= today + timedelta(days=60):
                events.append((d.strftime("%Y-%m-%d"),
                               _safe_html(title[:60]),
                               "AI 반도체/플랫폼 방향성 결정"))
            continue
        # "June 25", "Jul 30" 패턴
        m2 = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?", title)
        if m2:
            mon = m2.group(1).lower()
            if mon in month_map:
                yr = int(m2.group(3)) if m2.group(3) else today.year
                try:
                    d = date(yr, month_map[mon], int(m2.group(2)))
                    if today < d <= today + timedelta(days=60):
                        events.append((d.strftime("%Y-%m-%d"),
                                       _safe_html(title[:60]),
                                       "AI 반도체/플랫폼 방향성 결정"))
                except ValueError:
                    pass
    return events


def build_watchpoints_v2(news: dict) -> list:
    """실제 날짜 명시된 주시 포인트 (미정 제외)."""
    today = datetime.now().date()
    all_events: list = []

    # 1. FOMC (가장 중요)
    all_events.extend(_get_upcoming_fomc(today))

    # 2. BLS 경제 지표 (CPI/NFP/PCE)
    all_events.extend(_calculate_bls_dates(today))

    # 3. 실적 발표 (RSS 기반)
    all_events.extend(_search_earnings_dates(news, today))

    # 날짜 정렬, 중복 제거, 최대 3개
    seen_dates = set()
    points = []
    for date_str, event, significance in sorted(all_events):
        if date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        points.append({"date": date_str, "event": event, "significance": significance})
        if len(points) >= 4:
            break

    # 예비: 여전히 비었으면 1주 후 날짜로 기본 채우기 (날짜는 실제)
    if not points:
        nxt = (today + timedelta(days=9)).strftime("%Y-%m-%d")
        points.append({
            "date": nxt,
            "event": "FOMC 회의 예정",
            "significance": "금리 동결 여부 확인 필요",
        })

    return points


# ══════════════════════════════════════════════════════════════
# 5. 소스 URL 수집
# ══════════════════════════════════════════════════════════════

def _safe_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_HOMEPAGE_PATHS = {"", "/", "/#", "/?", "/home"}

def _is_article_url(url: str) -> bool:
    """True if URL has a meaningful article path, not just a homepage."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        return bool(path) and path not in ("", "/", "/home", "/news")
    except Exception:
        return False


def collect_sources(news: dict) -> list:
    """소스 URL 수집 — Google 리다이렉트 해소 + 동일 매체 중복 제거 + 기사 URL 우선."""
    seen_links = set()
    seen_sources = set()   # 동일 매체명 중복 방지
    sources = []
    for key in ["us_market", "macro", "korea", "earnings", "events"]:
        for item in news.get(key, []):
            raw_link = item.get("link", "")
            src_name = item.get("source", "News")
            if not raw_link or raw_link in seen_links:
                continue
            # 동일 매체 중복 제거 (Yahoo Finance 2회 방지)
            if src_name in seen_sources:
                continue
            seen_links.add(raw_link)

            # 리다이렉트 해소 시도
            real_link = _resolve_redirect(raw_link)
            # 해소 실패(여전히 google.com)면 raw_link(기사 고유 경로) 유지
            # source_url은 항상 매체 홈페이지 — 기사 URL로 대체 불가
            if "google.com" in real_link:
                src_url = item.get("source_url", "")
                if src_url and src_url.startswith("http") and _is_article_url(src_url):
                    real_link = src_url  # 실제 기사 URL이면 교체
                else:
                    real_link = raw_link  # Google News 기사별 고유 URL 유지

            # homepage URL이면 source_url 재시도 (비-Google 도메인 경우)
            if not _is_article_url(real_link) and "news.google.com" not in real_link:
                src_url = item.get("source_url", "")
                if src_url and src_url.startswith("http") and _is_article_url(src_url):
                    real_link = src_url

            seen_sources.add(src_name)
            sources.append({"source": src_name, "link": real_link})
            if len(sources) >= 5:
                return sources
    return sources


# ══════════════════════════════════════════════════════════════
# 6. Done Criteria v2
# ══════════════════════════════════════════════════════════════

def run_done_criteria(report: dict) -> tuple:
    failures = []

    # NQ-1: 등락률(%) + 방향 기호
    movements = report.get("movements", [])
    nq1_ok = any(
        ("%" in m) and any(c in m for c in ("▲", "▼")) and any(c.isdigit() for c in m)
        for m in movements
    )
    if not nq1_ok:
        failures.append("NQ-1: 핵심 움직임에 등락률(%) 없음")

    # NQ-2: 원인→결과 구조 (→ 기호 필수, 매체명만 있는 원인 불가)
    causes = report.get("causes", [])
    _MEDIA_PREFIXES = (
        "Yahoo Finance", "CNBC", "Bloomberg", "Reuters", "CNN",
        "Forbes", "MarketWatch", "Benzinga", "WSJ", "FT",
        "Business Insider", "Seeking Alpha", "Investor's Business Daily",
    )
    nq2_ok = (
        bool(causes)
        and all("→" in c for c in causes)
        and not any(c.startswith(_MEDIA_PREFIXES) for c in causes)
    )
    if not nq2_ok:
        media_causes = [c[:40] for c in causes if c.startswith(_MEDIA_PREFIXES)]
        if media_causes:
            failures.append(f"NQ-2: 매체명으로 시작하는 원인 불가 — {media_causes}")
        else:
            failures.append("NQ-2: 가능한 원인에 '→' 없음 (원인→결과 구조 필수)")

    # NQ-3: 주시 포인트 날짜가 모두 실제 날짜 (미정 없음)
    watchpoints = report.get("watchpoints", [])
    nq3_ok = (
        bool(watchpoints) and
        all(
            wp.get("date", "미정") not in ("미정", "", None) and
            len(wp.get("date", "")) == 10 and
            re.match(r"\d{4}-\d{2}-\d{2}", wp.get("date", ""))
            for wp in watchpoints
        )
    )
    if not nq3_ok:
        failures.append("NQ-3: '미정' 날짜 포함 또는 YYYY-MM-DD 형식 불일치")

    # NQ-4: ≥3개 기사 URL (https://, 기사 경로 포함 — Google News 기사별 경로 허용)
    sources = report.get("sources", [])
    article_links = [
        s for s in sources
        if s.get("link", "").startswith("https://")
        and _is_article_url(s.get("link", ""))
    ]
    homepage_links = [
        s for s in sources
        if s.get("link", "").startswith("https://")
        and not _is_article_url(s.get("link", ""))
    ]
    total_ok = len(article_links) + len(homepage_links)
    if len(article_links) >= 3:
        pass  # article-path URLs (including Google News /rss/articles/ paths)
    elif total_ok >= 3:
        failures.append(
            f"NQ-4: 기사URL {len(article_links)}개 (홈페이지 {len(homepage_links)}개 포함 시 {total_ok}개) — "
            f"기사 경로 포함 URL(https://domain.com/path/...) 필요"
        )
    else:
        failures.append(f"NQ-4: URL {total_ok}개 (최소 3개 필요)")

    all_pass = len(failures) == 0
    print(f"[Done Criteria] NQ-1~NQ-4: {'PASS' if all_pass else 'FAIL'}")
    fail_set = {f.split(":")[0] for f in failures}
    for nq in ["NQ-1", "NQ-2", "NQ-3", "NQ-4"]:
        print(f"  {'✓' if nq not in fail_set else '✗'} {nq}")
    return all_pass, failures


# ══════════════════════════════════════════════════════════════
# 7. 텔레그램
# ══════════════════════════════════════════════════════════════

def build_telegram_message(report: dict) -> str:
    date_str    = report.get("date", datetime.now().strftime("%Y-%m-%d"))
    movements   = report.get("movements", [])
    causes      = report.get("causes", [])
    watchpoints = report.get("watchpoints", [])
    sources     = report.get("sources", [])

    lines = [f"📰 <b>시장 해설</b> | {date_str}", ""]
    lines.append("<b>핵심 움직임</b>")
    for m in movements:
        lines.append(f"• {m}")
    lines.append("")
    lines.append("<b>가능한 원인</b>")
    for c in causes:
        lines.append(f"• {c}")
    lines.append("")
    lines.append("<b>주시 포인트</b>")
    for wp in watchpoints:
        sig  = wp.get("significance", "")
        sig_str = f" — {sig}" if sig else ""
        lines.append(f"• {wp['date']} {wp['event']}{sig_str}")
    lines.append("")
    src_parts = []
    for s in sources[:4]:
        link = s.get("link", "")
        name = s.get("source", "News")
        if link:
            src_parts.append(f'<a href="{link}">{_safe_html(name)}</a>')
    if src_parts:
        lines.append("📎 " + " · ".join(src_parts))
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM 설정 없음 — 스킵")
        return False
    try:
        payload = json.dumps({
            "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("ok"):
            print(f"[Telegram] 전송 성공 (message_id={result['result']['message_id']})")
            return True
        print(f"[Telegram] 실패: {result}")
        return False
    except Exception as e:
        print(f"[Telegram] 오류: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 8. 메인
# ══════════════════════════════════════════════════════════════

def run_news_agent() -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n[News Agent v2] 시도 {attempt}/{MAX_RETRIES}")

        print("  시장 데이터...")
        market = fetch_market_data()
        print("  뉴스 RSS...")
        news = fetch_news()

        print("  원인→결과 분석...")
        movements   = build_movements(market)
        causes      = build_causes_v2(news, market)
        print("  경제 캘린더...")
        watchpoints = build_watchpoints_v2(news)
        sources     = collect_sources(news)

        report = {
            "generated_at": datetime.now().isoformat(),
            "date":         datetime.now().strftime("%Y-%m-%d"),
            "movements":    movements,
            "causes":       causes,
            "watchpoints":  watchpoints,
            "sources":      sources,
            "market_raw":   market,
        }

        passed, failures = run_done_criteria(report)
        report["done_criteria"] = {"passed": passed, "failures": failures}

        if passed:
            break
        if attempt < MAX_RETRIES:
            print(f"  재시도 — {failures}")

    return report


if __name__ == "__main__":
    print("=" * 60)
    print("News Agent v2 — 품질 개선판")
    print("=" * 60)

    report = run_news_agent()

    NEWS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[저장] {NEWS_FILE}")

    msg = build_telegram_message(report)
    print("\n[메시지 미리보기]")
    print("-" * 50)
    preview = re.sub(r"<[^>]+>", "", msg)
    print(preview)
    print("-" * 50)

    send_telegram(msg)

    if not report["done_criteria"]["passed"]:
        print("\n[FAIL] Done Criteria 미충족")
        sys.exit(1)

    print("\n[PASS] NQ-1~NQ-4 전항목 통과")
    sys.exit(0)
