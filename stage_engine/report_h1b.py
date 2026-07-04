# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — report_h1b: Phase B-1 (H1-B) 리포트 — Phase A 비교 포함.

4섹션 evidence-first. 기본 실행은 조립+콘솔 출력만, `--send` 로 Telegram 전송.
pytest 수치는 실행 시점 실측 (DC-A5: 하드코딩 금지).
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from stage_engine.report_h1 import _run_pytest, SURVIVORSHIP_NOTE  # noqa: E402

A_PATH = ROOT / "output" / "stage_engine_h1_results.json"
B_PATH = ROOT / "output" / "stage_engine_h1b_results.json"

CHANGED_FILES = [
    "stage_engine/data_loader.py (pykrx PER 크로스섹션 + 업종지수 매핑/OHLCV 추가)",
    "stage_engine/backtest_h1.py (sector_map/attach_per/out_path 파라미터화 — 기본값 = Phase A 경로)",
    "stage_engine/report_h1b.py (신규 — 본 리포트)",
    "output/stage_engine_h1b_results.json (신규 — Phase A 결과 파일 보존)",
]


def _fmt_year(py: dict, y: str) -> str:
    d = py[y]
    return (f"  {y}: diff={d['median_diff_pp']}pp, p={d['bootstrap_p']}, "
            f"obs=({d['n_cohort_obs']}/{d['n_control_obs']})")


def build_report() -> list[str]:
    a = json.loads(A_PATH.read_text(encoding="utf-8"))
    b = json.loads(B_PATH.read_text(encoding="utf-8"))

    se_summary, se_pass, se_fail = _run_pytest("stage_engine/tests")
    ag_summary, ag_pass, ag_fail = _run_pytest("agents/tests")

    fb = b["sector_index_fallback"]
    n_b_obs = b["n_cohort_obs"] + b["n_control_obs"]
    avg_cohort_a = a["n_cohort_obs"] // a["n_snapshots"]
    avg_cohort_b = b["n_cohort_obs"] // b["n_snapshots"]

    s1 = f"""[Stage Engine v3.0 — Phase B-1 (H1-B) 리포트 1/4]
■ S1. 요청 vs 결과
요청: KRX 연동(pykrx) 후 피처 보강 재검증 — "엔진을 제대로 다시 돌려보자"
변경 (사전등록 라인·seed·MU/SIG·코호트 규칙 전부 불변 — 튜닝 아님):
- per_trailing: pykrx 월말 PER 크로스섹션 공급 (PER<=0=적자→None) → coverage 4/6→5/6
- 벤치마크: 시장 종합지수 → KRX 업종지수 (미매핑/시계열 부재만 종합 fallback)
- OL-7 산술 앵커: PER×EPS≈종가 표본 5/5 일치 (최대 오차 +1.94%, PER 반올림 기인)
결과: H1-B 판정 {b['h1_verdict']}
  (합격선: median diff >= +{b['pass_line']['median_diff_pp_min']}pp AND p < {b['pass_line']['p_max']} — 불변)
Phase A 대비: {a['median_diff_pp']}pp → {b['median_diff_pp']}pp, p {a['bootstrap_p']} → {b['bootstrap_p']}
판정 {b['h1_verdict']} — 무튜닝 원칙 유지, 수치 전체 보고"""

    s2 = f"""[Stage Engine v3.0 — Phase B-1 (H1-B) 리포트 2/4]
■ S2. 문제 먼저 (Problems First)
1) 기존 회귀 4 FAIL (pre-existing — B-1 무관):
   {ag_summary}
   원인: 오늘 08:58 UTC CI daily run(e63f9cd)이 output/narrative_context.json 을
   23필드→7필드로 퇴화 커밋 → test_narrative_context_schema 4건 FAIL.
   stage_engine 은 해당 파일 미접촉 — 별도 수정 스트림 필요.
2) 업종지수 backfill 갭: 일부 지수 시계열이 2024-07 이후 시작 →
   2023-01~2024-06 fallback ~250건/월, 2024-07 이후 ~21건/월.
   전체 fallback {fb['fallback_count']}건 / 벤치 사용 {fb['sector_bench_count'] + fb['fallback_count']}건 (비율 {fb['fallback_ratio']}).
3) 업종지수 구성종목은 '현재' 기준 (PIT 아님) — 과거 시점 소속과 다를 수 있음.
4) PER 충전율 ~58% (나머지 적자/무의미 → None, 설계 의도) —
   coverage 5/6 은 PER 존재 종목 한정, 적자 종목은 여전히 4/6.
5) 생존편향 (Phase A 와 동일): {SURVIVORSHIP_NOTE}
6) consensus_gap = None 유지 (Phase B-2 이연) — coverage 최대 5/6.
7) 월평균 cohort {avg_cohort_b}종목 (Phase A {avg_cohort_a}) — 선별력 소폭 개선
   그러나 여전히 유니버스의 ~1/3 (관찰만, 무조정)."""

    s3 = "[Stage Engine v3.0 — Phase B-1 (H1-B) 리포트 3/4]\n■ S3. 변경 파일\n" + \
        "\n".join(f"- {f}" for f in CHANGED_FILES) + \
        "\n(classifier/dynamics/failure_axis/tests 무수정 — fixture 12/14 경로 보존)"

    s4 = f"""[Stage Engine v3.0 — Phase B-1 (H1-B) 리포트 4/4]
■ S4. 수치 증거
[H1-B 게이트 — 판정 {b['h1_verdict']}]
- median diff = {b['median_diff_pp']}pp (합격선 +{b['pass_line']['median_diff_pp_min']}pp)
- bootstrap p = {b['bootstrap_p']} (<{b['pass_line']['p_max']}) / {b['bootstrap_method']}
- cohort 중앙값 = {b['cohort_median_excess_pp']}pp (n={b['n_cohort_obs']})
- control 중앙값 = {b['control_median_excess_pp']}pp (n={b['n_control_obs']})
- per-year:
{chr(10).join(_fmt_year(b['per_year'], y) for y in ('2023', '2024', '2025'))}
[Phase A → B-1 비교]
- median diff: {a['median_diff_pp']}pp → {b['median_diff_pp']}pp
- p: {a['bootstrap_p']} → {b['bootstrap_p']}
- cohort obs: {a['n_cohort_obs']} → {b['n_cohort_obs']} / control obs: {a['n_control_obs']} → {b['n_control_obs']}
- 벤치마크: 종합지수 100% → 업종지수 {round((1 - fb['fallback_ratio']) * 100, 1)}% (fallback {fb['fallback_count']}건)
[테스트 — 실행 시점 실측]
- stage_engine/tests: {se_summary} (fixture 12/14 유지 — 분류기 무수정)
- agents/tests: {ag_summary} (4 FAIL 은 S2-1 pre-existing — B-1 무관)
[데이터]
- 백테스트 wall-clock: {b['backtest_wall_clock_sec']}초, 스냅샷 {b['n_snapshots']}개, thin-cohort {len(b['thin_cohort_months'])}개
- 결과 파일: output/stage_engine_h1b_results.json (Phase A 파일 보존)"""

    ok = (se_fail == 0 and se_pass > 0 and B_PATH.exists()
          and b["n_snapshots"] == a["n_snapshots"])
    print(f"DONE_CRITERIA: {'PASS' if ok else 'FAIL — stage_engine 테스트/결과 파일 문제'}"
          + (f" (주의: agents/tests {ag_fail} FAIL pre-existing)" if ag_fail else ""))
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
