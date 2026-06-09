# -*- coding: utf-8 -*-
"""
SD-12 동적 테스트: run_stock_agent_v2.py Done Criteria
빈 top5 리스트 → SA-1/2/3/4/7 FAIL → exit(1) 검증
SA-5/SA-6 vacuously PASS 여부도 함께 확인 (SD-13 검증)
Done Criteria 코드 출처: agents/run_stock_agent_v2.py L840-859 (verbatim)
"""
import sys

results = {
    "universe": {"source": "EMPTY_TEST", "kospi_count": 0, "sp500_count": 0},
    "kospi_analysis": {"analyzed_count": 0},
    "sp500_analysis": {"analyzed_count": 0},
    "f09_sp500_contribution_top5": [],
    "f10_kospi_contribution_top5": [],
    "f11_sp500_beneficiary_top5":  [],
    "f12_kospi_beneficiary_top5":  [],
}
all_top5 = []
ksp_res  = results["kospi_analysis"]
sp_res   = results["sp500_analysis"]

def has_company_dup(lst):
    tickers = [s.get("ticker", "") for s in lst]
    return len(tickers) != len(set(tickers))

done_criteria = {
    "SA-1 유니버스 동적 수집":         "FDR(KRX" in results["universe"]["source"],
    "SA-2 KOSPI >=50개 분석":         ksp_res.get("analyzed_count", 0) >= 50,
    "SA-3 S&P500 >=100개 분석":       sp_res.get("analyzed_count", 0) >= 100,
    "SA-4 KOSPI Top5 시총 존재":       any((s.get("market_cap_b") or 0) > 0
                                          for s in results["f10_kospi_contribution_top5"]),
    "SA-5 SP500 극단수익률 플래그":     not any(abs(s.get("stock_return_pct") or 0) > 5000
                                              for s in all_top5),
    "SA-6 동일기업 중복 없음 (SP500)":  not has_company_dup(results["f09_sp500_contribution_top5"]),
    "SA-7 기여/수혜 결과 비어있지 않음": (len(results["f09_sp500_contribution_top5"]) >= 3
                                          and len(results["f10_kospi_contribution_top5"]) >= 3),
}

print("[STOCK AGENT Done Criteria — mock empty results]")
crit_fail = []
for k, v in done_criteria.items():
    vacuous = "(vacuous PASS!)" if (v and k.startswith("SA-5") and not all_top5) \
                                 or (v and k.startswith("SA-6") and not results["f09_sp500_contribution_top5"]) \
              else ""
    print(f"  [{'PASS' if v else 'FAIL'}] {k} {vacuous}")
    if not v:
        crit_fail.append(k)

if crit_fail:
    print(f"\n[FAIL] Done Criteria 실패: {crit_fail}")
    sys.exit(1)
print("\n[PASS] 전항목 통과")
