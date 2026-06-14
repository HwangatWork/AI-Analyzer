# -*- coding: utf-8 -*-
"""
Notion Agent — 파이프라인 완료 시 Notion 페이지 자동 업데이트
Done Criteria (N-1~N-4):
  N-1: NOTION_TOKEN 환경변수 설정 확인
  N-2: Notion API 연결 성공 (200 OK)
  N-3: 페이지 업데이트 성공 (기존 블록 삭제 + 신규 삽입)
  N-4: 필수 섹션 포함 확인 (시그널 점수, 가중치 Top5, 기여/수혜, Validation)

실행:
  python agents/run_notion_agent.py
  python agents/run_notion_agent.py --done-criteria
"""
import utf8_setup  # noqa: F401

import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import httpx
except ImportError:
    print("[ERROR] httpx 미설치 — pip install httpx")
    sys.exit(1)

BASE_DIR     = Path(__file__).parent.parent
OUT_DIR      = BASE_DIR / "output"
PROC_DIR     = BASE_DIR / "data" / "processed"
RESULTS_FILE = OUT_DIR / "final_results.json"

NOTION_TOKEN   = os.getenv("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
PAGE_ID        = "3781a4c7-30d8-81f9-bf7d-db6541a23fcf"
BASE_URL       = "https://api.notion.com/v1"

INDICATOR_KR = {
    "NASDAQ100": "나스닥100", "DOW": "다우존스", "SP500": "S&P500",
    "KOSPI": "코스피", "KOSDAQ": "코스닥", "NIKKEI225": "닛케이225",
    "US10Y": "미국 10년물 금리", "DXY": "달러인덱스", "WTI": "WTI 원유",
    "HY_SPREAD": "하이일드 스프레드", "T10Y2Y": "장단기 금리차",
    "VIX": "VIX 공포지수", "CNN_FG": "공포탐욕지수", "SKEW": "SKEW지수",
    "PUT_CALL": "Put/Call 비율", "MARKET_MOMENTUM": "시장 모멘텀",
    "MARKET_STRENGTH": "시장 강도", "RSI14": "RSI(14일)", "RSI_SIGNAL": "RSI 신호",
    "MA50": "MA50", "MA200": "MA200", "MA_SIGNAL": "골든/데드크로스",
    "BETA": "베타", "BBAND": "볼린저밴드", "STOCH_RSI": "Stochastic RSI",
    "FOREIGN_NET": "외국인 순매수", "INSTITUTION_NET": "기관 순매수",
    "INDIVIDUAL_NET": "개인 순매수", "FED_ASSETS": "연준 총자산",
}


# ── Notion API 헬퍼 ──────────────────────────────────────────────

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _get(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}{path}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def _patch(path: str, body: dict) -> dict:
    r = httpx.patch(f"{BASE_URL}{path}", headers=_headers(),
                    content=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=15)
    r.raise_for_status()
    return r.json()


def _delete(path: str) -> dict:
    r = httpx.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


# ── 블록 생성 헬퍼 ───────────────────────────────────────────────

def _h1(text: str) -> dict:
    return {"object": "block", "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _h3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, emoji: str = "📊") -> dict:
    return {"object": "block", "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
                "icon": {"type": "emoji", "emoji": emoji},
            }}


# ── 데이터 로드 ──────────────────────────────────────────────────

def _load_results() -> dict:
    if not RESULTS_FILE.exists():
        raise FileNotFoundError(f"{RESULTS_FILE} 없음 — 파이프라인 먼저 실행")
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def _load_validation() -> dict:
    vf = PROC_DIR / "validation_report.json"
    if vf.exists():
        return json.loads(vf.read_text(encoding="utf-8"))
    return {}


# ── 블록 목록 구성 ───────────────────────────────────────────────

def _build_blocks(data: dict, vr: dict) -> list[dict]:
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    direc = sig.get("direction", "N/A")
    bull  = sig.get("bullish_count", 0)
    total_sigs = sig.get("total_signals", 0)
    rank  = data.get("indicator_weight_ranking", [])

    sp_cont  = data.get("sp500_analysis", {}).get("contribution_top5", [])
    sp_bene  = data.get("sp500_analysis", {}).get("beneficiary_top5", [])
    ksp_cont = data.get("kospi_analysis",  {}).get("contribution_top5", [])
    ksp_bene = data.get("kospi_analysis",  {}).get("beneficiary_top5", [])

    vs       = vr.get("summary", {})
    val_pass = vs.get("passed",  "?")
    val_tot  = vs.get("total",   "?")
    val_crit = vs.get("failed_critical", "?")

    now = datetime.now().strftime("%Y/%m/%d %H:%M")

    # 액션 판단
    if score >= 75:
        action_str = f"🟢 매수 관점 ({score:.1f}점)"
    elif score < 40:
        action_str = f"🔴 매도/축소 검토 ({score:.1f}점)"
    else:
        action_str = f"🟡 관망 HOLD ({score:.1f}점)"

    dir_kr = {"risk-on": "리스크 온", "risk-off": "리스크 오프", "neutral": "중립"}.get(
        direc, direc
    )

    def cont_str(s: dict, i: int) -> str:
        name = s.get("name", "N/A")
        ret  = s.get("stock_return_pct", 0)
        mc   = s.get("market_cap_start_b") or s.get("market_cap_b", 0)
        sc   = s.get("contribution_score", 0)
        return f"{i}. {name} | 수익률 {ret:+.1f}% | 시가총액 ${mc:.0f}B(시작) | 기여점수 {sc:.3f}"

    def bene_str(s: dict, i: int) -> str:
        name   = s.get("name", "N/A")
        excess = s.get("excess_return_pct", 0)
        sc     = s.get("beneficiary_score", 0)
        warn   = " ⚠이벤트" if abs(excess) > 1000 else ""
        return f"{i}. {name} | 초과수익 {excess:+.1f}%{warn} | 점수 {sc:.3f}"

    blocks = [
        _h1(f"📊 AI Analyzer 분석 결과 — {now}"),
        _divider(),

        # 시장 시그널
        _h2("📈 시장 시그널"),
        _callout(action_str, "🎯"),
        _bullet(f"점수: {score:.1f} / 100  ({dir_kr})"),
        _bullet(f"강세 지표: {bull} / {total_sigs}개"),
        _divider(),

        # 가중치 Top5
        _h2("📌 지표 가중치 Top5"),
    ]
    for r in rank[:5]:
        nm = INDICATOR_KR.get(r["indicator"], r["indicator"])
        w  = r.get("combined_weight", 0)
        g  = " [Granger ✓]" if r.get("sp500_granger_sig") else ""
        blocks.append(_bullet(f"{r['rank']}. {nm}{g} — {w:.4f}"))

    blocks += [
        _divider(),

        # S&P500 기여
        _h2("🏆 S&P500 분석"),
        _h3("지수 기여 Top5"),
    ]
    for i, s in enumerate(sp_cont[:5], 1):
        blocks.append(_bullet(cont_str(s, i)))

    blocks.append(_h3("수혜 종목 Top5"))
    for i, s in enumerate(sp_bene[:5], 1):
        blocks.append(_bullet(bene_str(s, i)))

    blocks += [
        _divider(),

        # 코스피 기여
        _h2("🇰🇷 코스피 분석"),
        _h3("지수 기여 Top5"),
    ]
    for i, s in enumerate(ksp_cont[:5], 1):
        blocks.append(_bullet(cont_str(s, i)))

    blocks.append(_h3("수혜 종목 Top5"))
    for i, s in enumerate(ksp_bene[:5], 1):
        blocks.append(_bullet(bene_str(s, i)))

    blocks += [
        _divider(),

        # Validation
        _h2("🔍 Validation 결과"),
        _bullet(f"통과: {val_pass} / {val_tot}  (CRITICAL={val_crit})"),
    ]

    # 실패 항목 (CRITICAL만)
    checks = vr.get("checks", [])
    crit_fails = [c for c in checks if not c.get("passed") and c.get("severity") == "CRITICAL"]
    if crit_fails:
        blocks.append(_para("❌ CRITICAL 실패 항목:"))
        for c in crit_fails:
            blocks.append(_bullet(f"  [{c.get('check_id','')}] {c.get('description','')} — {c.get('detail','')}"))
    else:
        blocks.append(_bullet("모든 CRITICAL 항목 통과 ✅"))

    blocks.append(_divider())
    blocks.append(_para(f"AI Analyzer v4  |  생성: {now}"))
    return blocks


# ── 메인 업데이트 로직 ───────────────────────────────────────────

def update_notion_page() -> dict:
    """Notion 페이지 전체 갱신 (기존 블록 삭제 → 신규 삽입)."""

    # 1. 기존 자식 블록 조회
    print(f"[Notion] 기존 블록 조회 — page_id={PAGE_ID}")
    resp = _get(f"/blocks/{PAGE_ID}/children?page_size=100")
    existing = resp.get("results", [])
    print(f"[Notion] 기존 블록 수: {len(existing)}")

    # 2. 기존 블록 삭제
    for blk in existing:
        bid = blk.get("id")
        if bid:
            _delete(f"/blocks/{bid}")
    print(f"[Notion] 기존 블록 {len(existing)}개 삭제 완료")

    # 3. 데이터 로드
    data = _load_results()
    vr   = _load_validation()

    # 4. 신규 블록 삽입 (Notion API: 한 번에 최대 100 블록)
    blocks = _build_blocks(data, vr)
    chunk_size = 90
    inserted = 0
    for i in range(0, len(blocks), chunk_size):
        chunk = blocks[i:i + chunk_size]
        _patch(f"/blocks/{PAGE_ID}/children", {"children": chunk})
        inserted += len(chunk)
    print(f"[Notion] {inserted}개 블록 삽입 완료")

    sig   = data.get("market_signal", {})
    return {
        "ok":      True,
        "blocks":  inserted,
        "score":   sig.get("score"),
        "direc":   sig.get("direction"),
    }


# ── Done Criteria 자체검증 ────────────────────────────────────────

def _run_done_criteria():
    print("\n[Notion] Done Criteria 검증 시작")
    failures = []

    # N-1: NOTION_TOKEN 설정 확인
    if not NOTION_TOKEN:
        failures.append("N-1: NOTION_TOKEN 환경변수 없음 — .env에 토큰 추가 필요")
        print("  N-1 FAIL — NOTION_TOKEN 없음")
    else:
        print(f"  N-1 PASS — 토큰 존재 (길이={len(NOTION_TOKEN)})")

    # N-2: API 연결 확인
    if NOTION_TOKEN:
        try:
            resp = _get(f"/pages/{PAGE_ID}")
            if resp.get("object") == "page":
                print(f"  N-2 PASS — 페이지 접근 성공")
            else:
                failures.append(f"N-2: 페이지 응답 이상 — object={resp.get('object')}")
        except Exception as e:
            failures.append(f"N-2: API 연결 실패 — {e}")
            print(f"  N-2 FAIL — {e}")
    else:
        failures.append("N-2: 토큰 없어 건너뜀")

    # N-3: 업데이트 실행
    if NOTION_TOKEN:
        try:
            result = update_notion_page()
            if result.get("ok") and result.get("blocks", 0) > 0:
                print(f"  N-3 PASS — {result['blocks']}개 블록 삽입")
            else:
                failures.append(f"N-3: 업데이트 실패 — {result}")
        except Exception as e:
            failures.append(f"N-3: 업데이트 오류 — {e}")
            print(f"  N-3 FAIL — {e}")
    else:
        failures.append("N-3: 토큰 없어 건너뜀")

    # N-4: 필수 섹션 검증 (로컬 블록 구성 기준)
    try:
        data   = _load_results()
        vr     = _load_validation()
        blocks = _build_blocks(data, vr)
        texts  = []
        for b in blocks:
            for bt in ("heading_1", "heading_2", "heading_3", "paragraph", "bulleted_list_item", "callout"):
                if bt in b:
                    for rt in b[bt].get("rich_text", []):
                        texts.append(rt.get("text", {}).get("content", ""))

        required = ["시장 시그널", "가중치 Top5", "S&P500", "코스피", "Validation"]
        missing  = [r for r in required if not any(r in t for t in texts)]
        if missing:
            failures.append(f"N-4: 필수 섹션 누락 — {missing}")
        else:
            print(f"  N-4 PASS — 필수 섹션 {required} 모두 포함")
    except Exception as e:
        failures.append(f"N-4: 블록 검증 오류 — {e}")

    print()
    if failures:
        print(f"[FAIL] Done Criteria {len(failures)}개 실패:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    else:
        print("[PASS] Done Criteria N-1~N-4 모두 통과")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--update"

    if mode == "--done-criteria":
        _run_done_criteria()
        sys.exit(0)

    # 기본: 업데이트
    if not NOTION_TOKEN:
        print("[ERROR] NOTION_TOKEN 없음 — .env 파일에 NOTION_TOKEN=<토큰값> 추가 후 재실행")
        sys.exit(1)

    try:
        result = update_notion_page()
        print(f"[Notion] 완료 — 점수={result['score']}, 방향={result['direc']}, 블록={result['blocks']}개")
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] Notion API HTTP 오류: {e.response.status_code} — {e.response.text}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 예상치 못한 오류: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
