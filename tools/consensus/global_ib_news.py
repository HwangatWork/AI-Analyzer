# -*- coding: utf-8 -*-
"""Phase 14-4 — Per-firm Global IB target extraction via Korean news search.

Goal: Surface NAMED global IB targets (JPM/Goldman Sachs/Morgan Stanley etc.)
for Korean stocks by scraping Korean financial press article bodies.

Phase 14-3 found that financial data pages (yfinance/Finnhub/Yahoo HTML) do
not expose per-firm names for Korean tickers. Korean financial press DOES
publish explicit phrasing like "JP모건은 24만원, CLSA는 26만원을 제시하고
있다" (verified on hankyung.com/article/2026020437756 for 삼성전자 005930).

Honest scope:
  - Validated on 반도체 sector tickers (000660 / 005930). Not generalized.
  - News-derived signals are LOWER confidence than direct broker data.
  - Headline re-quotes inflate sample counts unless deduped.
  - Manual input via configs/manual_global_ib_targets.json is the
    higher-confidence path for high-stakes decisions.

Source precedence (Decision Agent rule): manual > yfinance > news.

Confidence labels:
  - "user_verified" : manual input
  - "high"          : >= 2 unique news sources after dedupe
  - "medium"        : 1 news source
  - "low"           : single match but proximity_chars > 200 or
                      analyst_context < underwriter_context
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional


try:
    from tools.consensus.robots_check import check_robots, DEFAULT_UA
except ImportError:
    import os.path as _osp
    sys.path.insert(0, _osp.dirname(_osp.dirname(_osp.dirname(
        _osp.abspath(__file__)
    ))))
    from tools.consensus.robots_check import check_robots, DEFAULT_UA  # noqa: E402


# ---------- canonical name mapping ----------

# WiseReport / Korean press uses Korean transliterations of global IB names.
# All variants map to a canonical English name.
IB_NAME_ALIASES: dict[str, str] = {
    # JPMorgan
    "JP모건": "JPMorgan", "JPMorgan": "JPMorgan", "제이피모간": "JPMorgan",
    "JP 모건": "JPMorgan", "J.P. Morgan": "JPMorgan",
    # Goldman Sachs
    "골드만삭스": "Goldman Sachs", "Goldman Sachs": "Goldman Sachs",
    "골드만": "Goldman Sachs",
    # Morgan Stanley
    "모건스탠리": "Morgan Stanley", "Morgan Stanley": "Morgan Stanley",
    # BofA / Merrill
    "BofA": "BofA", "메릴린치": "BofA", "뱅크오브아메리카": "BofA",
    "Bank of America": "BofA",
    # Citi
    "씨티": "Citi", "Citi": "Citi", "Citigroup": "Citi",
    # UBS
    "UBS": "UBS",
    # Barclays
    "Barclays": "Barclays", "바클레이즈": "Barclays",
    # HSBC
    "HSBC": "HSBC", "에이치에스비씨": "HSBC",
    # Macquarie
    "Macquarie": "Macquarie", "맥쿼리": "Macquarie",
    # CLSA
    "CLSA": "CLSA",
    # Nomura
    "Nomura": "Nomura", "노무라": "Nomura",
    # Daiwa
    "Daiwa": "Daiwa", "다이와": "Daiwa",
    # Mizuho
    "Mizuho": "Mizuho", "미즈호": "Mizuho",
    # Deutsche Bank
    "Deutsche Bank": "Deutsche Bank", "도이체방크": "Deutsche Bank",
    "도이치방크": "Deutsche Bank",
}

CANONICAL_IBS = tuple(sorted(set(IB_NAME_ALIASES.values())))


def canonicalize_ib(name: Optional[str]) -> Optional[str]:
    """Return canonical English IB name for any known alias. None if unknown."""
    if not name:
        return None
    return IB_NAME_ALIASES.get(name.strip())


# ---------- ticker → Korean name ----------

TICKER_TO_KO_NAME: dict[str, str] = {
    "000660": "SK하이닉스",
    "005930": "삼성전자",
    "035420": "NAVER",
    "035720": "카카오",
    "207940": "삼성바이오로직스",
}


# ---------- source configuration ----------

# robots-pre-audited candidates (2026-07-01 audit, reports/phase_14_4/robots_audit_log.txt).
# Only `allowed=True` sources are listed here. Inline robots re-check still
# runs before each fetch (Audit Agent's defensive concern).
KOREAN_NEWS_SOURCES: list[dict[str, Any]] = [
    {
        "name": "hankyung_search",
        "search_url_template": (
            "https://search.hankyung.com/search/news?query={query}"
        ),
        "article_url_pattern": (
            r"https?://www\.hankyung\.com/article/\d+[a-z]?"
        ),
        "encoding": "utf-8",
    },
]


# ---------- regex (compiled once) ----------

# Korean target-price pattern. Captures numeric value with optional
# "만" (10,000) shorthand. Limit context distance to 30 chars to avoid
# capturing distant numbers.
KO_TARGET_RE = re.compile(
    r"(?:목표(?:주)?가)[^\d<>]{0,30}"
    r"(\d{1,3}(?:[,.]?\d{3})*|\d+(?:\.\d+)?\s?만\s?\d{0,4}\s?)"
    r"\s*원"
)

# English variant (for cases where article is in English)
EN_TARGET_RE = re.compile(
    r"(?:price target|target price|PT)[^\d]{0,8}"
    r"(?:KRW|₩|won)?\s*([\d,]+)",
    re.IGNORECASE,
)

# Context words that confirm "analyst recommendation" vs "underwriter role"
ANALYST_CONTEXT_WORDS = (
    "투자의견", "리서치", "보고서", "리포트", "애널리스트", "커버리지",
    "상향", "하향", "제시", "평가", "전망", "컨센서스", "분석",
)

UNDERWRITER_CONTEXT_WORDS = (
    "주관사", "인수", "대표주관", "대표주관사", "유상증자", "회사채",
    "발행", "공모", "신규상장",
)


def _normalize_korean_money(raw: str) -> Optional[int]:
    """Convert '24만', '24만원', '215,375', '21만5375' to integer KRW.

    Returns None on parse failure.
    """
    if raw is None:
        return None
    s = raw.strip().replace(" ", "")
    # Strip trailing 원 if any
    s = s.rstrip("원")
    # Pure comma-separated number: "215,375"
    if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        return int(s.replace(",", ""))
    # Pure number with optional .: "215375"
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    # "21만5375" or "21만5,375"
    m = re.fullmatch(r"(\d+)만\s?(\d[\d,]*)?", s)
    if m:
        man = int(m.group(1))
        rest = m.group(2)
        sub = int(rest.replace(",", "")) if rest else 0
        return man * 10000 + sub
    # "24.5만"
    m = re.fullmatch(r"(\d+\.\d+)\s?만", s)
    if m:
        return int(float(m.group(1)) * 10000)
    return None


# ---------- search + fetch ----------

def _http_get(url: str, timeout: float = 15.0,
              user_agent: str = DEFAULT_UA) -> tuple[Optional[int], bytes, str]:
    """One GET. Returns (status, body_bytes, error_or_empty)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept-Language": "ko-KR,ko;q=0.9"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, b"", f"HTTPError {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, b"", f"{type(e).__name__}: {e!r}"


def search_news(
    ib_name_ko: str,
    ticker_ko: str,
    max_items: int = 8,
    source: Optional[dict[str, Any]] = None,
    delay_sec: float = 1.0,
) -> list[dict[str, Any]]:
    """Search a single source for articles mentioning {ib_name_ko} {ticker_ko}.

    Returns list of {"url": str, "source_name": str} (article URL hits, deduped).
    """
    src = source or KOREAN_NEWS_SOURCES[0]
    # Defensive robots re-check (Audit Agent G1 extension)
    query = f"{ib_name_ko}+{ticker_ko}+목표주가"
    encoded_query = urllib.parse.quote(query, safe="+")  # type: ignore[attr-defined]
    search_url = src["search_url_template"].format(query=encoded_query)
    if not check_robots(search_url)["allowed"]:
        return []
    status, body, err = _http_get(search_url)
    if status != 200 or not body:
        return []
    text = body.decode(src.get("encoding", "utf-8"), errors="replace")
    pat = re.compile(src["article_url_pattern"])
    urls: list[str] = []
    seen: set[str] = set()
    for m in pat.finditer(text):
        u = m.group(0)
        if u in seen:
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= max_items:
            break
    time.sleep(delay_sec)
    return [{"url": u, "source_name": src["name"]} for u in urls]


def fetch_and_extract_targets(
    url: str,
    ticker_ko: str,
    delay_sec: float = 1.0,
) -> list[dict[str, Any]]:
    """Fetch one article. Extract all (firm, target_price, evidence_phrase)
    triples where:
      - target match occurs near (within 300 chars) at least one IB alias
      - ticker_ko also occurs in the article
      - analyst_context >= underwriter_context (paragraph-level proxy)

    Returns list of entries (may be empty).
    """
    if not check_robots(url)["allowed"]:
        return []
    status, body, err = _http_get(url)
    if status != 200 or not body:
        return []
    text = body.decode("utf-8", errors="replace")
    # Strip script/style (lower noise + reduce false positives in JS strings)
    text_clean = re.sub(r"<script[^>]*>.*?</script>", " ", text,
                         flags=re.DOTALL | re.IGNORECASE)
    text_clean = re.sub(r"<style[^>]*>.*?</style>", " ", text_clean,
                         flags=re.DOTALL | re.IGNORECASE)
    if ticker_ko not in text_clean:
        return []

    results: list[dict[str, Any]] = []
    for m in KO_TARGET_RE.finditer(text_clean):
        target_raw = m.group(1)
        target_price = _normalize_korean_money(target_raw)
        if target_price is None:
            continue
        # plausibility: 1만~100만원 per share is reasonable for KOSPI large-caps,
        # or 1억 max (1억 = 100,000,000원 → way too high in won)
        if not (10_000 <= target_price <= 100_000_000):
            continue
        # Context window
        start = max(0, m.start() - 300)
        end = min(len(text_clean), m.end() + 300)
        ctx_html = text_clean[start:end]
        ctx = re.sub(r"<[^>]+>", " ", ctx_html)
        ctx = re.sub(r"&[a-z]+;", " ", ctx)
        ctx = re.sub(r"\s+", " ", ctx).strip()

        # Find IB names in this context
        ibs_found: list[tuple[str, int]] = []  # (canonical, position)
        for alias, canonical in IB_NAME_ALIASES.items():
            pos = ctx.find(alias)
            if pos >= 0:
                ibs_found.append((canonical, pos))
        if not ibs_found:
            continue
        # Pick the IB CLOSEST to the target value
        target_pos_in_ctx = ctx.find(target_raw)
        if target_pos_in_ctx < 0:
            target_pos_in_ctx = len(ctx) // 2  # fallback
        ibs_found.sort(key=lambda t: abs(t[1] - target_pos_in_ctx))
        closest_ib, ib_pos = ibs_found[0]
        proximity_chars = abs(ib_pos - target_pos_in_ctx)

        # Analyst vs underwriter context (Stock Agent + Validation Agent rule)
        analyst_ctx = sum(1 for w in ANALYST_CONTEXT_WORDS if w in ctx)
        underwriter_ctx = sum(1 for w in UNDERWRITER_CONTEXT_WORDS if w in ctx)
        is_analyst = analyst_ctx > underwriter_ctx
        if not is_analyst:
            continue  # skip underwriter-only mentions

        # Evidence phrase: ±80 chars around the target match in cleaned text
        ev_start = max(0, target_pos_in_ctx - 80)
        ev_end = min(len(ctx), target_pos_in_ctx + 80 + len(target_raw))
        evidence_phrase = ctx[ev_start:ev_end].strip()

        results.append({
            "firm": closest_ib,
            "target_price": target_price,
            "currency": "KRW",
            "evidence_phrase": evidence_phrase,
            "proximity_chars": proximity_chars,
            "analyst_ctx_score": analyst_ctx,
            "underwriter_ctx_score": underwriter_ctx,
            "source_url": url,
            "extraction_method": "news_regex",
        })
    time.sleep(delay_sec)
    return results


def _try_extract_report_date(url: str) -> Optional[str]:
    """Hankyung URL embeds YYYYMMDD as the first 8 digits after /article/."""
    m = re.search(r"/article/(\d{8})", url)
    if not m:
        return None
    s = m.group(1)
    try:
        y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:8])
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except (ValueError, TypeError):
        return None


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Meta-Audit Agent rule: dedupe by (firm, target_price, report_date)
    so re-quoted wire stories count as 1 unique signal."""
    seen: dict[tuple, dict[str, Any]] = {}
    for e in entries:
        key = (e.get("firm"), e.get("target_price"), e.get("report_date"))
        if key not in seen:
            e["source_count"] = 1
            e["source_urls"] = [e["source_url"]]
            seen[key] = e
        else:
            seen[key]["source_count"] += 1
            seen[key]["source_urls"].append(e["source_url"])
    return list(seen.values())


def _assign_confidence(entry: dict[str, Any]) -> str:
    if entry.get("extraction_method") == "manual":
        return "user_verified"
    proximity = entry.get("proximity_chars", 999)
    sc = entry.get("source_count", 1)
    if proximity > 200:
        return "low"
    if sc >= 2:
        return "high"
    return "medium"


def parse_per_firm_global(
    ticker: str,
    ib_names_to_search: Optional[list[str]] = None,
    max_articles_per_ib: int = 5,
) -> dict[str, Any]:
    """Orchestrator: search → fetch → extract → dedupe → assign confidence.

    Args:
      ticker: KRX numeric (e.g. "000660")
      ib_names_to_search: Korean transliterations of IBs to search.
                          Default: top 5 (JP모건, 골드만삭스, 모건스탠리, CLSA, 노무라).
      max_articles_per_ib: cap per IB per source.

    Returns:
      {
        "found": bool,
        "n_entries": int,
        "entries": list[FirmEntry],
        "attempted_searches": list[str],
        "probed_at": str,
      }
    """
    ticker_ko = TICKER_TO_KO_NAME.get(ticker)
    if ticker_ko is None:
        return {
            "found": False, "n_entries": 0, "entries": [],
            "attempted_searches": [], "probed_at": _now_iso(),
            "error": f"unknown_ticker_ko_name: {ticker}",
        }
    ibs = ib_names_to_search or ["JP모건", "골드만삭스", "모건스탠리", "CLSA", "노무라"]
    raw_entries: list[dict[str, Any]] = []
    attempted: list[str] = []
    for ib_ko in ibs:
        for source in KOREAN_NEWS_SOURCES:
            attempted.append(f"{source['name']}:{ib_ko}")
            hits = search_news(ib_ko, ticker_ko, max_items=max_articles_per_ib,
                                source=source)
            for h in hits:
                entries = fetch_and_extract_targets(h["url"], ticker_ko)
                for e in entries:
                    e["report_date"] = _try_extract_report_date(h["url"])
                    e["source_name"] = source["name"]
                raw_entries.extend(entries)
    deduped = _dedupe_entries(raw_entries)
    for e in deduped:
        e["confidence"] = _assign_confidence(e)
    return {
        "found": bool(deduped),
        "n_entries": len(deduped),
        "entries": deduped,
        "attempted_searches": attempted,
        "probed_at": _now_iso(),
    }


# ---------- manual input loader ----------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


MANUAL_TARGETS_PATH = "configs/manual_global_ib_targets.json"
MANUAL_SCHEMA_PATH = "configs/manual_global_ib_targets.schema.json"


def load_manual_targets(ticker: str,
                         path: str = MANUAL_TARGETS_PATH) -> list[dict[str, Any]]:
    """Read manual targets JSON. Validates via jsonschema if available."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get(ticker) or []
    out: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        firm = canonicalize_ib(e.get("firm"))
        if not firm:
            continue
        target_price = e.get("target_price")
        if not isinstance(target_price, (int, float)) or target_price <= 0:
            continue
        out.append({
            "firm": firm,
            "target_price": float(target_price),
            "currency": e.get("currency", "KRW"),
            "report_date": e.get("report_date"),
            "rating": e.get("rating"),
            "source_url": None,
            "evidence_phrase": e.get("user_note", "user-verified PDF"),
            "extraction_method": "manual",
            "confidence": "user_verified",
            "source_count": 1,
            "source_urls": [],
        })
    return out


def merge_named_global_ib(
    news_entries: list[dict[str, Any]],
    manual_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Decision Agent rule: manual > yfinance > news.

    Manual entries override news entries for the same firm. Sort by report_date
    desc and tag stale (>60 days from today).
    """
    by_firm: dict[str, dict[str, Any]] = {}
    for e in news_entries:
        by_firm[e["firm"]] = e
    for e in manual_entries:
        by_firm[e["firm"]] = e  # manual overrides

    today = _dt.date.today()
    for e in by_firm.values():
        rd = e.get("report_date")
        if rd:
            try:
                d = _dt.date.fromisoformat(rd)
                e["is_stale"] = (today - d).days > 60
            except ValueError:
                e["is_stale"] = False
        else:
            e["is_stale"] = False
    out = list(by_firm.values())
    out.sort(key=lambda e: e.get("report_date") or "", reverse=True)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="Phase 14-4 — per-firm global IB target extractor"
    )
    p.add_argument("--ticker", required=True)
    p.add_argument("--smoke", action="store_true",
                   help="REQUIRED — confirms intent to make network calls")
    p.add_argument("--out-dir", default="output/consensus_snapshot")
    p.add_argument("--max-articles", type=int, default=5)
    args = p.parse_args(argv)

    if not args.smoke:
        sys.stderr.write(
            "ERROR: --smoke flag required (default-deny). Phase 14-4 makes "
            "outgoing network calls.\n"
        )
        return 4

    news = parse_per_firm_global(args.ticker,
                                   max_articles_per_ib=args.max_articles)
    manual = load_manual_targets(args.ticker)
    merged = merge_named_global_ib(news["entries"], manual)
    payload = {
        "ticker": args.ticker,
        "ticker_ko": TICKER_TO_KO_NAME.get(args.ticker),
        "probed_at": _now_iso(),
        "news_search": news,
        "manual_entries": manual,
        "merged_entries": merged,
        "n_merged": len(merged),
    }
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir,
                              f"{args.ticker}_global_ib_named.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(
        f"global_ib_news: ticker={args.ticker} merged={len(merged)} "
        f"news={len(news['entries'])} manual={len(manual)} out={out_path}\n"
    )
    return 0 if merged else 3


# Needed by search_news urllib.parse import
import urllib.parse  # noqa: E402  (kept at module bottom for clarity)


if __name__ == "__main__":
    raise SystemExit(main())
