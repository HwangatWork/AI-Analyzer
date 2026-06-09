# -*- coding: utf-8 -*-
"""
SD-12 동적 테스트: run_data_agent_v2.py Done Criteria
ok=set() (수집 성공 지표 없음) → 모든 DC 체크 실패 → exit(1) 검증
Done Criteria 코드 출처: agents/run_data_agent_v2.py L427-475 (verbatim)
"""
import sys

ok = set()   # 수집 성공 없음 — 빈 데이터 모사

F01_OK = all(k in ok for k in ["SP500","NASDAQ100","DOW","KOSPI","KOSDAQ","NIKKEI225"])
F02_OK = all(k in ok for k in ["US10Y","DXY","WTI","FED_ASSETS","T10Y2Y","HY_SPREAD"])
F03_CORE = all(k in ok for k in ["VIX","MARKET_MOMENTUM","MARKET_STRENGTH"])
F03_OK   = F03_CORE and ("SKEW" in ok or "CNN_FG" in ok)
F04_CORE = all(k in ok for k in ["RSI14","MA50","MA200","MA_SIGNAL"])
F04_OK   = F04_CORE and sum(1 for k in ["RSI14","RSI_SIGNAL","MA50","MA200","MA_SIGNAL","BBAND","BETA","STOCH_RSI"] if k in ok) >= 6
F05_OK   = all(k in ok for k in ["FOREIGN_NET","INSTITUTION_NET","INDIVIDUAL_NET"])
TOTAL_MIN = 22

done_checks = {
    "DC-1 F01 시장지수 6/6":       F01_OK,
    "DC-2 F02 매크로 6/6":         F02_OK,
    "DC-3 F03 심리 VIX+핵심4개+":  F03_OK,
    "DC-4 F04 기술 핵심4개+6개+":  F04_OK,
    "DC-5 F05 수급 3/3":           F05_OK,
    f"DC-6 전체 >=22개":           len(ok) >= TOTAL_MIN,
}

print("[DATA AGENT Done Criteria — mock empty ok]")
hard_fails = []
for check, passed in done_checks.items():
    print(f"  [{'PASS' if passed else 'FAIL'}] {check}")
    if not passed:
        hard_fails.append(check)

if hard_fails:
    print(f"\n[FAIL] Done Criteria 미충족 — 파이프라인 중단: {hard_fails}")
    sys.exit(1)
print("\n[PASS] Done Criteria 전항목 통과")
