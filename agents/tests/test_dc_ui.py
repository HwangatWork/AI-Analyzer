# -*- coding: utf-8 -*-
"""
SD-12 동적 테스트: run_ui_agent.py Done Criteria
빈 HTML + signal=neutral → UX-1/2/5/6/7 FAIL → exit(1) 검증
UX-3/UX-4 vacuously PASS 여부도 확인 (SD-13 추가 검증)
Done Criteria 코드 출처: agents/run_ui_agent.py L501-519 (verbatim)
"""
import sys

_html_text  = ""          # 완전히 빈 HTML
_all_stocks = []          # 빈 종목 리스트
_zero_mcap  = []          # 빈 zero-mcap 리스트
signal      = {"direction": "neutral"}

_done_criteria = {
    "UX-1 모바일 nav 스크롤":  "overflow-x" in _html_text,
    "UX-2 HOLD 카드 설명":     signal.get("direction") != "neutral"
                               or ("신규 매수" in _html_text and "기존 보유" in _html_text),
    "UX-3 $0B 경고 배지":      (not _zero_mcap) or "미집계" in _html_text,
    "UX-4 극단 수익률 경고":    not any(abs(s.get("stock_return_pct") or 0) > 1000
                                        for s in _all_stocks) or "이벤트 영향" in _html_text,
    "UX-5 신뢰도 설명":        "개 강세" in _html_text,
    "UX-6 7개 탭 모두 존재":    all(f"page-{t}" in _html_text
                                    for t in ["decision","narrative","signal","stocks",
                                              "sector","indicators","looker"]),
    "UX-7 footer 면책 문구":    "투자 판단은 개인 책임" in _html_text or "개인 책임" in _html_text,
}

print("[UI AGENT Done Criteria — mock empty HTML]")
crit_fail = [k for k, v in _done_criteria.items() if not v]
for k, v in _done_criteria.items():
    vacuous = "(vacuous PASS!)" if v and k.startswith(("UX-3","UX-4")) and not _all_stocks else ""
    print(f"  [{'PASS' if v else 'FAIL'}] {k} {vacuous}")

if crit_fail:
    print(f"\n[FAIL] UX Done Criteria 미충족: {crit_fail}")
    sys.exit(1)
print("\n[PASS] 전항목 통과")
