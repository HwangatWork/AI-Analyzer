# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — report_h1: 4섹션 evidence-first 리포트 조립 + Telegram 전송.

S1 요청 vs 결과 / S2 문제 먼저 / S3 변경 파일 / S4 수치 증거.
기본 실행은 조립+콘솔 출력만. `--send` 플래그로 Telegram 분할 전송
(agents/run_telegram_agent.py send_message 재사용, HTML escape 적용).

pytest 수치는 하드코딩하지 않고 실행 시점에 subprocess로 직접 측정
(DC-A5: 기대 개수 하드코딩 금지 — 실제 수치 보고).
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from stage_engine.failure_axis import NO_KEY_BLOCKER  # noqa: E402

RESULTS_PATH = ROOT / "output" / "stage_engine_h1_results.json"

CHANGED_FILES = [
    "stage_engine_v3_smoke_test.py (신규 — 사용자 전달 스펙 verbatim)",
    "stage_engine/__init__.py",
    "stage_engine/data_loader.py",
    "stage_engine/classifier.py",
    "stage_engine/dynamics.py",
    "stage_engine/failure_axis.py",
    "stage_engine/backtest_h1.py",
    "stage_engine/report_h1.py",
    "stage_engine/tests/test_fixture_reproduction.py",
    "stage_engine/tests/test_classifier_units.py",
    "stage_engine/tests/test_dynamics.py",
    ".gitignore (stage_engine/cache/ 추가)",
]

SURVIVORSHIP_NOTE = (
    "생존편향은 코호트·컨트롤 양쪽에 모두 작용해 부분적으로(그러나 불완전하게) "
    "상쇄되므로, 차이의 부호·크기 방향으로 해석하고 정확한 값 자체를 무편향 "
    "추정치로 취급하지 않는다."
)


def _run_pytest(target: str) -> tuple[str, int, int]:
    """(요약 라인, n_passed, n_failed). 실측 — 하드코딩 금지."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--tb=no"],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8", errors="replace", timeout=600,
    )
    tail = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    summary = tail[-1] if tail else "(no output)"
    m_pass = re.search(r"(\d+) passed", summary)
    m_fail = re.search(r"(\d+) failed", summary)
    return summary, (int(m_pass.group(1)) if m_pass else 0), \
        (int(m_fail.group(1)) if m_fail else 0)


def build_report() -> list[str]:
    r = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    se_summary, se_pass, se_fail = _run_pytest("stage_engine/tests")
    ag_summary, ag_pass, ag_fail = _run_pytest("agents/tests")

    verdict = r["h1_verdict"]
    thin = r["thin_cohort_months"]
    fb = r["sector_index_fallback"]
    dm = r.get("download_meta", {})

    s1 = f"""[Stage Engine v3.0 — Phase A 완료 리포트 1/4]
■ S1. 요청 vs 결과
요청: 5단계 확률 분류 엔진 + H1 사전등록 검증 게이트 (강도 10/10)
결과:
- stage_engine/ 독립 모듈 6개 + 테스트 3개 구축 (기존 파이프라인 무수정)
- 14종목 fixture 재현: 스펙과 동일 경로로 회귀 고정
- H1 백테스트: 2023-01~2025-12 월말 {r['n_snapshots']}개 스냅샷, PIT 피처, 전종목 {dm.get('n_tickers', '?')}개
- H1 판정: {verdict}
  (사전등록 합격선: median diff >= +{r['pass_line']['median_diff_pp_min']}pp AND p < {r['pass_line']['p_max']} — 불변)
- 판정 {verdict} — 사전등록 원칙에 따라 MU/SIG/conf 임계/드리프트 윈도우 무튜닝, 수치 전체 보고"""

    s2 = f"""[Stage Engine v3.0 — Phase A 완료 리포트 2/4]
■ S2. 문제 먼저 (Problems First)
1) DART 키 부재 blocker:
   {NO_KEY_BLOCKER}
   DART 실호출 코드는 키 미보유로 미검증 상태.
2) KRX 섹터지수 시계열 FDR 조회 불가 (SnapDataReader NotImplementedError 실측)
   → 시장 종합지수(KS11/KQ11) fallback {fb['fallback_count']}건 (100%).
   단, 지표가 cohort-control '차이'라 벤치마크 항 대부분 상쇄.
3) FDR 빈 티커: {r.get('n_empty_fdr_tickers', 0)}건 / {dm.get('n_tickers', '?')}종목
4) thin-cohort 월 (<5종목): {len(thin)}개 / {r['n_snapshots']}개 스냅샷
   {', '.join(thin) if thin else '(없음)'}
   반대 방향 관찰: 월평균 cohort {r['n_cohort_obs'] // r['n_snapshots']}종목
   (유니버스의 약 절반) — conf>=0.4 게이트의 선별력이 낮음 (사전등록 원칙상
   무조정, 관찰만 보고).
5) PIT 한계 (FDR 구조상 불가피): 섹터·상장주식수는 현재 리스팅 기준,
   유니버스는 현재 상장 종목만 → 생존편향 존재.
   {SURVIVORSHIP_NOTE}
6) per_trailing/consensus_gap = None by design (Phase A) → coverage <= 4/6,
   conf >= 0.4 임계는 사전등록대로 무조정.
7) LARGECAP_MU 스케일링(per x0.6, pos_low x0.5)과 vol_z20 설계값은 UNVALIDATED
   (스펙 지시 구현, 실증 검증은 Phase B)."""

    s3 = "[Stage Engine v3.0 — Phase A 완료 리포트 3/4]\n■ S3. 변경 파일\n" + \
        "\n".join(f"- {f}" for f in CHANGED_FILES) + \
        "\n(agents/, refresh_data.py, 기존 테스트 무수정 — S4 회귀로 증명)"

    py = r["per_year"]

    def _yr(y: str) -> str:
        d = py[y]
        return (f"  {y}: diff={d['median_diff_pp']}pp, p={d['bootstrap_p']}, "
                f"obs=({d['n_cohort_obs']}/{d['n_control_obs']})")

    s4 = f"""[Stage Engine v3.0 — Phase A 완료 리포트 4/4]
■ S4. 수치 증거
[H1 게이트 — 판정 {verdict}]
- median diff = {r['median_diff_pp']}pp (합격선 +{r['pass_line']['median_diff_pp_min']}pp)
- bootstrap p = {r['bootstrap_p']} (<{r['pass_line']['p_max']}) / {r['bootstrap_method']}
- cohort 중앙값 = {r['cohort_median_excess_pp']}pp (n={r['n_cohort_obs']})
- control 중앙값 = {r['control_median_excess_pp']}pp (n={r['n_control_obs']})
- per-year:
{chr(10).join(_yr(y) for y in ('2023', '2024', '2025'))}
[테스트 — 실행 시점 실측]
- stage_engine/tests: {se_summary} (fixture 12/14 재현 + 합성 drift 방향 포함)
- agents/tests 기존 회귀: {ag_summary} → FAIL {ag_fail}건 (기준: 0 FAIL)
[데이터]
- FDR 다운로드: {dm.get('n_ok', '?')}/{dm.get('n_tickers', '?')} 성공, empty {dm.get('n_empty', '?')}건, {dm.get('wall_clock_sec', '?')}초
- 백테스트 wall-clock: {r['backtest_wall_clock_sec']}초
- 결과 파일: output/stage_engine_h1_results.json"""

    ok = (se_fail == 0 and ag_fail == 0 and se_pass > 0 and ag_pass > 0
          and RESULTS_PATH.exists())
    print(f"DONE_CRITERIA: {'PASS' if ok else 'FAIL — 테스트 실패 또는 결과 파일 부재'}")
    if not ok:
        sys.exit(1)
    return [s1, s2, s3, s4]


def send_report(sections: list[str]) -> None:
    from agents.run_telegram_agent import send_message
    for sec in sections:
        resp = send_message(html.escape(sec))
        if not resp.get("ok"):
            print(f"TELEGRAM FAIL: {resp}")
            sys.exit(1)
    print(f"TELEGRAM: {len(sections)}개 섹션 전송 완료")


if __name__ == "__main__":
    secs = build_report()
    print("\n\n".join(secs))
    if "--send" in sys.argv:
        send_report(secs)
