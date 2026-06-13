# -*- coding: utf-8 -*-
"""
PM Agent — 파이프라인 조율 + 구조 감사 (pm_orchestrator.py)
PIPELINE_STAGES, validate_results, auto_fix, final_report, pm_system_audit.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from pm_utils import (
    BASE_DIR, AGENTS_DIR, OUT_DIR, PROC_DIR,
    _load_results, _load_validation, _load_audit,
    _tg_send, _tg_step, _run, register_pending, _load_pending,
)
from pm_quality import (
    CONTEMPORANEOUS_INDICES, SELF_REFERENTIAL, EXTREME_RETURN_THRESHOLD,
    SMALL_CAP_USD_B_THRESHOLD, SP500_CONTRIBUTOR_TOP1_MIN_MC_B,
    MAX_RETRIES, _qc_summary, _derive_fix_scripts, _write_fix_request,
    pm_quality_checks,
)

# SA 결과 캐시 — mutable list 사용해 from pm_orchestrator import _last_audit_findings
# 으로 가져간 참조에서도 최신 값 반영 (재할당 대신 clear+extend로 갱신)
_last_audit_findings: list[dict] = []


# ══════════════════════════════════════════════════════════════
# 자체검증 기준
# ══════════════════════════════════════════════════════════════

class Criterion:
    def __init__(self, code: str, desc: str, fix_stages: list[str]):
        self.code       = code
        self.desc       = desc
        self.fix_stages = fix_stages
        self.fatal      = True


CRITERIA = [
    Criterion("C1", "동행 지수 상위 3위 이내",
              ["run_analysis_agent_v2.py", "run_evaluator_agent_v2.py",
               "run_validation_agent.py", "generate_report_v2.py"]),
    Criterion("C2", "Granger 미통과 지표 상위 5위 이내",
              ["run_evaluator_agent_v2.py", "run_validation_agent.py",
               "generate_report_v2.py"]),
    Criterion("C3", "자기참조 지표 상위권",
              ["run_evaluator_agent_v2.py", "run_validation_agent.py",
               "generate_report_v2.py"]),
    Criterion("C4", "소형주 기여 Top1", []),
    Criterion("C5", "Validation CRITICAL > 0",
              ["run_validation_agent.py", "generate_report_v2.py"]),
    Criterion("C6", "Audit CRITICAL > 0",
              ["run_audit_agent.py"]),
]
CRITERIA[3].fatal = False  # C4는 경고만, retry 없음


# ══════════════════════════════════════════════════════════════
# 파이프라인 정의
# ══════════════════════════════════════════════════════════════

PIPELINE_STAGES = [
    ("run_data_agent_v2.py",    "Data Agent",       1,  800),
    ("refresh_data.py",         "Refresh",          2,  120),
    ("run_analysis_agent_v2.py","Analysis Agent",   3,  300),
    ("run_stock_agent_v2.py",   "Stock Agent",      4,  600),
    ("run_evaluator_agent_v2.py","Evaluator Agent", 5,  120),
    ("run_news_agent.py",       "News Agent",       6,  120),
    ("run_sector_agent.py",     "Sector Agent",     7,  120),
    ("run_validation_agent.py", "Validation Agent", 8,  120),
    ("run_decision_agent.py",   "Decision Agent",   9,  120),
    ("run_ui_agent.py",         "UI Agent",         10, 120),
    ("run_narrative_agent.py",  "Narrative Agent",  11, 120),
    ("generate_report_v2.py",   "Report",           12, 120),
    ("run_audit_agent.py",      "Audit Agent",      13, 300),
]
TOTAL_STEPS = 14  # 13 스테이지 + 1 최종 보고

STAGE_DEPS: dict[str, list[str]] = {
    "run_data_agent_v2.py":      [],
    "refresh_data.py":           ["run_data_agent_v2.py"],
    "run_analysis_agent_v2.py":  ["refresh_data.py"],
    "run_stock_agent_v2.py":     ["refresh_data.py"],
    "run_evaluator_agent_v2.py": ["run_analysis_agent_v2.py"],
    "run_news_agent.py":         [],
    "run_sector_agent.py":       ["refresh_data.py"],
    "run_validation_agent.py":   ["run_evaluator_agent_v2.py",
                                   "run_stock_agent_v2.py"],
    "run_decision_agent.py":     ["run_validation_agent.py"],
    "run_ui_agent.py":           ["run_decision_agent.py",
                                   "run_evaluator_agent_v2.py",
                                   "run_stock_agent_v2.py"],
    "run_narrative_agent.py":    ["run_ui_agent.py"],
    "generate_report_v2.py":     ["run_narrative_agent.py"],
    "run_audit_agent.py":        ["generate_report_v2.py"],
}


def _get_dependents(failed_scripts: set[str]) -> list[str]:
    """
    실패한 스크립트 집합에서 재실행이 필요한 스크립트 목록 반환.
    STAGE_DEPS의 역방향 그래프를 BFS로 탐색해 전이적 의존 단계를 수집한다.
    """
    reverse_deps: dict[str, list[str]] = {s: [] for s in STAGE_DEPS}
    for stage, deps in STAGE_DEPS.items():
        for dep in deps:
            if dep in reverse_deps:
                reverse_deps[dep].append(stage)

    to_run: set[str] = set(failed_scripts)
    queue: list[str] = list(failed_scripts)
    while queue:
        current = queue.pop(0)
        for dependent in reverse_deps.get(current, []):
            if dependent not in to_run:
                to_run.add(dependent)
                queue.append(dependent)

    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    return [s for s in pipeline_order if s in to_run]


def _auto_fix_from_diagnosis(issues: list[str]) -> None:
    """진단 코드별로 해당 Agent 자동 재실행."""
    scripts_needed, _ = _derive_fix_scripts(issues)

    if not scripts_needed:
        return

    known = {s for s in scripts_needed if s in {st for st, *_ in PIPELINE_STAGES}}
    if not known:
        return
    ordered = _get_dependents(known)

    _tg_send(
        f"🔧 <b>PM 자가진단 자동 수정</b>\n"
        f"이슈 {len(issues)}개 발견\n"
        f"재실행: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자가진단 자동 수정: {ordered}")
    run_partial_pipeline(ordered)


# ══════════════════════════════════════════════════════════════
# 결과 검증
# ══════════════════════════════════════════════════════════════

def validate_results() -> list[tuple[Criterion, str]]:
    """결과 검증 → 실패한 (Criterion, 상세) 목록 반환."""
    failures: list[tuple[Criterion, str]] = []
    data = _load_results()
    vr   = _load_validation()
    ar   = _load_audit()

    if not data:
        return [(CRITERIA[0], "final_results.json 없음")]

    rank = data.get("indicator_weight_ranking", [])

    top3_inds = {r["indicator"] for r in rank[:3]}
    overlap   = top3_inds & CONTEMPORANEOUS_INDICES
    if overlap:
        failures.append((CRITERIA[0], f"상위 3위에 동행 지수 포함: {overlap}"))

    top5 = rank[:5]
    granger_fails = [
        r["indicator"] for r in top5
        if not r.get("sp500_granger_sig") and not r.get("kospi_granger_sig")
    ]
    if granger_fails:
        failures.append((CRITERIA[1], f"Granger 미통과 상위 5위: {granger_fails}"))

    self_ref_in_top = [r["indicator"] for r in top5 if r["indicator"] in SELF_REFERENTIAL]
    if self_ref_in_top:
        failures.append((CRITERIA[2], f"자기참조 지표 상위 5위: {self_ref_in_top}"))

    sp_top1 = (data.get("sp500_analysis", {}).get("contribution_top5") or [{}])[0]
    mc_start = sp_top1.get("market_cap_start_b") or sp_top1.get("market_cap_b") or 0
    if 0 < mc_start < SMALL_CAP_USD_B_THRESHOLD:
        failures.append((CRITERIA[3],
            f"S&P500 기여 1위 시총 ${mc_start:.1f}B — 소형주({sp_top1.get('name','?')}) ⚠ 수동 확인 필요"))

    val_crit = vr.get("summary", {}).get("failed_critical", 0)
    if val_crit and val_crit != "?" and int(val_crit) > 0:
        crit_items = [
            f"[{c['check_id']}] {c.get('description','')}"
            for c in vr.get("checks", [])
            if not c.get("passed") and c.get("severity") == "CRITICAL"
        ]
        failures.append((CRITERIA[4], f"CRITICAL {val_crit}건: {crit_items[:3]}"))

    aud_crit = ar.get("summary", {}).get("failed_critical", 0)
    if aud_crit and int(aud_crit) > 0:
        audit_items = [
            f"[{f['code']}] {f.get('target','')}"
            for f in ar.get("findings", [])
            if not f.get("passed") and f.get("severity") == "CRITICAL"
        ]
        failures.append((CRITERIA[5], f"Audit CRITICAL {aud_crit}건: {audit_items[:3]}"))

    return failures


# ══════════════════════════════════════════════════════════════
# 파이프라인 실행
# ══════════════════════════════════════════════════════════════

def run_full_pipeline(skip_data: bool = False) -> list[tuple[str, bool]]:
    """전체 파이프라인 실행. 각 단계 완료 시 Telegram 보고."""
    results = []
    for script, label, step_n, timeout in PIPELINE_STAGES:
        if skip_data and script in ("run_data_agent_v2.py", "refresh_data.py"):
            print(f"[PM] 건너뜀 (--skip-data): {script}")
            _tg_step(step_n, TOTAL_STEPS, label, "건너뜀 (기존 데이터 사용)")
            results.append((label, True))
            continue
        ok, out = _run(script, label, timeout)
        short = out.strip().splitlines()[-1][:150] if out.strip() else ""
        _tg_step(step_n, TOTAL_STEPS, label, short if ok else f"⚠ 오류: {short}")
        results.append((label, ok))
        if not ok:
            print(f"[PM] {label} 실패 — 파이프라인 중단")
            break
    return results


def run_partial_pipeline(scripts: list[str]) -> list[tuple[str, bool]]:
    """지정 스테이지만 재실행 (자동 수정용)."""
    script_map = {s: (lbl, sn, to) for s, lbl, sn, to in PIPELINE_STAGES}
    results = []
    for script in scripts:
        if script not in script_map:
            print(f"[PM] 알 수 없는 스크립트: {script} — 건너뜀")
            continue
        lbl, sn, to = script_map[script]
        ok, out = _run(script, lbl, to)
        results.append((lbl, ok))
    return results


def auto_fix(failures: list[tuple[Criterion, str]], attempt: int) -> None:
    """실패 기준별 자동 수정 실행."""
    fatal   = [(c, d) for c, d in failures if c.fatal]
    warning = [(c, d) for c, d in failures if not c.fatal]

    for c, d in warning:
        _tg_send(
            f"⚠ <b>PM Agent 경고 [{c.code}]</b>\n"
            f"기준: {c.desc}\n상세: {d}\n<i>재시도 없음 — 수동 확인 권장</i>"
        )

    if not fatal:
        return

    pipeline_order = [s for s, *_ in PIPELINE_STAGES]
    fix_stage_set: set[str] = {
        s for c, _ in fatal for s in c.fix_stages if s in pipeline_order
    }
    if not fix_stage_set:
        return
    ordered = _get_dependents(fix_stage_set)

    fail_descs = "\n".join(f"  [{c.code}] {d}" for c, d in fatal)
    _tg_send(
        f"🔄 <b>PM Agent 자동 수정 시도 {attempt}/{MAX_RETRIES}</b>\n"
        f"실패 기준:\n{fail_descs}\n\n"
        f"재실행 단계: {[s.replace('run_','').replace('.py','') for s in ordered]}"
    )

    print(f"[PM] 자동 수정 실행: {ordered}")
    run_partial_pipeline(ordered)


# ══════════════════════════════════════════════════════════════
# 최종 보고
# ══════════════════════════════════════════════════════════════

def _confidence_tier(confidence_pct: float) -> tuple[str, str]:
    """신뢰도 임계값 분류. (tier, label) 반환."""
    if confidence_pct >= 70:
        return "normal", f"✅ 정상 신호 ({confidence_pct:.1f}%)"
    elif confidence_pct >= 50:
        return "warn", f"⚠ 주의 신호 ({confidence_pct:.1f}%) — 부분 신뢰"
    else:
        return "hold", f"🔴 신호 보류 ({confidence_pct:.1f}%) — 데이터 부족"


def _format_decision_for_tg(decision: dict) -> str:
    """decision.json 내용을 Telegram 메시지용 텍스트로 변환 (신뢰도 임계값 적용)."""
    lines = []
    for market_key, market_label in [("sp500", "S&P500"), ("kospi", "코스피")]:
        dec = decision.get(market_key, {})
        action = dec.get("action", "HOLD")
        conf   = dec.get("confidence_pct", 0.0)
        pos    = dec.get("position_size_pct", 0.0)
        tier, tier_label = _confidence_tier(conf)

        if tier == "hold":
            lines.append(f"  {market_label}: {action} | {tier_label}\n  → 신뢰도 50% 미만 — 의사결정 보류")
        elif tier == "warn":
            lines.append(f"  {market_label}: {action} | {tier_label}\n  → 포지션 {pos:.0f}% (낮은 신뢰도 감안 주의)")
        else:
            lines.append(f"  {market_label}: {action} | {tier_label} | 포지션 {pos:.0f}%")
    return "\n".join(lines)


def final_report(all_passed: bool, failures: list[tuple[Criterion, str]], elapsed: float) -> None:
    """Telegram 최종 보고 + Notion 업데이트."""
    data  = _load_results()
    sig   = data.get("market_signal", {})
    score = sig.get("score", 0)
    direc = sig.get("direction", "N/A")
    rank  = data.get("indicator_weight_ranking", [])

    top3 = "\n".join(
        f"  {r['rank']}. {r['indicator']} ({r['combined_weight']:.4f})"
        for r in rank[:3]
    )

    vr = _load_validation()
    vs = vr.get("summary", {})
    val_pass = vs.get("passed", "?")
    val_tot  = vs.get("total",  "?")

    elapsed_str = f"{elapsed/60:.1f}분"

    decision   = data.get("decision", {})
    dec_section = ""
    if decision:
        sp_conf  = decision.get("sp500", {}).get("confidence_pct", 0.0)
        ksp_conf = decision.get("kospi", {}).get("confidence_pct", 0.0)
        sp_tier,  _ = _confidence_tier(sp_conf)
        ksp_tier, _ = _confidence_tier(ksp_conf)
        dec_text = _format_decision_for_tg(decision)
        dec_section = f"\n<b>의사결정 (신뢰도 임계값 적용):</b>\n{dec_text}\n"
        if sp_tier == "hold":
            print(f"  [PM] ⚠ S&P500 신뢰도 {sp_conf:.1f}% < 50% — 의사결정 보류 표시")
        if ksp_tier == "hold":
            print(f"  [PM] ⚠ 코스피 신뢰도 {ksp_conf:.1f}% < 50% — 의사결정 보류 표시")

    if all_passed:
        status_emoji = "✅"
        status_text  = "모든 자체검증 기준 통과"
    else:
        status_emoji = "⚠"
        fail_list = "\n".join(f"  [{c.code}] {d}" for c, d in failures if c.fatal)
        status_text = f"일부 기준 미달 (최대 {MAX_RETRIES}회 재시도 완료)\n{fail_list}"

    msg = (
        f"🏁 <b>PM Agent 완료</b>  ({elapsed_str})\n\n"
        f"{status_emoji} <b>상태:</b> {status_text}\n\n"
        f"<b>시장 시그널:</b> {score:.1f} / 100  ({direc})\n"
        f"<b>Validation:</b> {val_pass}/{val_tot} PASS\n"
        f"{dec_section}\n"
        f"<b>가중치 Top3:</b>\n{top3}\n\n"
        f"<i>AI Analyzer PM Agent v2 | {datetime.now().strftime('%Y/%m/%d %H:%M')}</i>"
    )
    _tg_send(msg)
    print(f"[PM] 최종 Telegram 보고 완료")

    notion_script = AGENTS_DIR / "run_notion_agent.py"
    if notion_script.exists():
        import os
        if os.getenv("NOTION_TOKEN"):
            ok, _ = _run("run_notion_agent.py", "Notion 업데이트", 60)
            if ok:
                print("[PM] Notion 업데이트 완료")
            else:
                print("[PM] Notion 업데이트 실패 (비치명적)")
        else:
            print("[PM] NOTION_TOKEN 없음 — Notion 업데이트 건너뜀")

    _run("run_telegram_agent.py", "Telegram 상세 요약", 30)
    _tg_step(TOTAL_STEPS, TOTAL_STEPS, "최종 보고", "Telegram + Notion 완료")


# ══════════════════════════════════════════════════════════════
# SA 구조 감사 (pm_system_audit)
# ══════════════════════════════════════════════════════════════

def _register_audit_findings(findings: list[dict]) -> None:
    """SA findings를 pending_requests.json에 등록 (중복 제외).

    CRITICAL → 즉시 등록 + Telegram 알림
    HIGH → 등록만
    MEDIUM → backlog으로 등록
    INFO → 등록 안 함
    """
    data = _load_pending()
    all_items = data.get("completed", []) + data.get("pending", [])

    registered: list[str] = []
    for f in findings:
        sev = f["severity"]
        if sev == "INFO":
            continue

        sa_code = f["sa_code"]

        existing = None
        for item in all_items:
            _itxt = json.dumps(item, ensure_ascii=False)
            if sa_code in _itxt:
                existing = item
                break

        if sa_code == "SA-1" and existing is None:
            for item in all_items:
                _itxt2 = json.dumps(item, ensure_ascii=False)
                if "CONTEMPORANEOUS" in _itxt2 or "역입력" in _itxt2:
                    existing = item
                    break

        if existing:
            print(f"  [SA] {sa_code} 기존 항목 발견 ({existing.get('id', '?')}) — 신규 등록 생략")
            continue

        req_id = f"REQ-{sa_code.replace('-', '')}"
        status = "pending" if sev in ("CRITICAL", "HIGH") else "backlog"
        register_pending(
            req_id=req_id,
            request=f"[{sa_code} {sev}] {f['title']}",
            status=status,
            details=f['detail'],
        )
        registered.append(req_id)

        if sev == "CRITICAL":
            _tg_send(
                f"🚨 <b>[{sa_code} CRITICAL] {f['title']}</b>\n"
                f"{f['detail'][:200]}\n"
                f"<i>pending_requests에 {req_id} 자동 등록됨</i>"
            )
            print(f"  [SA] CRITICAL → Telegram 알림 + {req_id} 등록")

    if registered:
        print(f"  [SA] pending_requests 신규 등록: {registered}")
    else:
        print("  [SA] pending_requests 신규 등록 없음 (모두 기존 항목)")


def _sa8_regression_health(agents_dir: Path) -> dict:
    """SA-8: 회귀 테스트 스위트 자체 건강도 감사 (구조 감사, 데이터 품질과 무관).

    T-count:     test 함수 ≥ 23개
    T-vacuous:   assert True / assert [] == [] 패턴 0건
    T-import:    핵심 모듈 3개 이상 참조 (stop_hook/decision_agent/compute_kospi/pm_quality)
    T-freshness: 테스트 파일이 소스보다 14일 이상 뒤처지지 않음
    """
    import re as _re8

    test_path = agents_dir / "tests" / "test_regression.py"
    if not test_path.exists():
        return {"sa_code": "SA-8", "severity": "HIGH",
                "title": "SA-8 회귀 테스트 파일 없음",
                "detail": f"{test_path} 파일 없음"}
    try:
        src = test_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as _e8:
        return {"sa_code": "SA-8", "severity": "HIGH",
                "title": "SA-8 회귀 테스트 읽기 실패",
                "detail": str(_e8)[:120]}

    issues: list[str] = []
    parts:  list[str] = []

    fn_count = len(_re8.findall(r"^def (test_\w+)", src, _re8.MULTILINE))
    if fn_count < 23:
        issues.append(f"T-count {fn_count}<23")
    parts.append(f"T-count={fn_count}")

    vacuous = [l for l in src.splitlines()
               if _re8.search(r"\bassert True\b", l) or "assert [] ==" in l]
    if vacuous:
        issues.append(f"T-vacuous {len(vacuous)}건")
    parts.append(f"T-vacuous={len(vacuous)}")

    _core = ["stop_hook", "decision_agent", "compute_kospi", "pm_quality"]
    refs = sum(1 for m in _core if m in src)
    if refs < 3:
        issues.append(f"T-import {refs}<3")
    parts.append(f"T-import={refs}/{len(_core)}")

    test_mtime = test_path.stat().st_mtime
    _src_files = ["pm_orchestrator.py", "pm_quality.py", "run_pm_agent.py",
                  "run_decision_agent.py", "run_validation_agent.py"]
    _mtimes = [p.stat().st_mtime for p in (agents_dir / f for f in _src_files) if p.exists()]
    lag_days = max(0.0, (max(_mtimes) - test_mtime) / 86400) if _mtimes else 0.0
    if lag_days > 14:
        issues.append(f"T-freshness lag={lag_days:.0f}일>14")
    parts.append(f"T-freshness={lag_days:.0f}일")

    detail = " | ".join(parts)
    if issues:
        return {"sa_code": "SA-8", "severity": "MEDIUM",
                "title": f"SA-8 회귀 테스트 건강도 이슈 {len(issues)}건",
                "detail": f"{' | '.join(issues)} ({detail})"}
    return {"sa_code": "SA-8", "severity": "INFO",
            "title": "SA-8 회귀 테스트 스위트 건강도 정상",
            "detail": detail}


def pm_system_audit() -> list[dict]:
    """SA-1~SA-8 정적 구조 감사 — 런타임 데이터 품질(SD)과 분리된 아키텍처 검사.

    Returns list of findings: [{"sa_code", "severity", "title", "detail"}]
    severity: CRITICAL / HIGH / MEDIUM / INFO
    """
    import ast as _ast_sa
    import inspect as _insp_sa
    from collections import Counter as _Cnt_sa

    findings: list[dict] = []

    # ── SA-1: run_decision_agent.py에서 CONTEMPORANEOUS 지수 직접 참조 탐지 ──
    _da_path = AGENTS_DIR / "run_decision_agent.py"
    sa1_hits: list[str] = []
    if _da_path.exists():
        try:
            _da_lines = _da_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for _lno, _line in enumerate(_da_lines, 1):
                if "_CONTEMPORANEOUS" in _line:
                    continue
                for _idx in CONTEMPORANEOUS_INDICES:
                    if f'"{_idx}"' in _line or f"'{_idx}'" in _line:
                        sa1_hits.append(f"L{_lno}:'{_idx}'")
        except Exception as _e1:
            sa1_hits.append(f"파싱 오류: {_e1}")

    if sa1_hits:
        findings.append({
            "sa_code":  "SA-1",
            "severity": "CRITICAL",
            "title":    "CONTEMPORANEOUS 역입력 탐지",
            "detail":   (
                f"run_decision_agent.py에서 동행 지수 {len(sa1_hits)}개 직접 참조: "
                f"{sa1_hits[:6]}"
            ),
        })
    else:
        findings.append({
            "sa_code":  "SA-1",
            "severity": "INFO",
            "title":    "CONTEMPORANEOUS 역입력 없음",
            "detail":   "run_decision_agent.py에 동행 지수 직접 참조 없음 (IQ-1 체계 정상)",
        })

    # ── SA-2: 파이프라인 Agent 200줄 이상 함수 탐지 + run_pm_agent.py 총 라인 ──
    large_fns: list[str] = []
    for _sc2, *_ in PIPELINE_STAGES:
        _p2 = AGENTS_DIR / _sc2
        if not _p2.exists():
            continue
        try:
            import ast as _ast2
            _src2 = _p2.read_text(encoding="utf-8", errors="ignore")
            _tree2 = _ast2.parse(_src2)
            for _nd2 in _ast2.walk(_tree2):
                if isinstance(_nd2, _ast2.FunctionDef):
                    _ln2 = (_nd2.end_lineno or 0) - _nd2.lineno
                    if _ln2 >= 200:
                        large_fns.append(f"{_sc2}:{_nd2.name}() {_ln2}L")
        except Exception:
            pass

    _pm_lines2 = 0
    _pm_path2  = AGENTS_DIR / "run_pm_agent.py"
    if _pm_path2.exists():
        try:
            _pm_lines2 = len(_pm_path2.read_text(encoding="utf-8").splitlines())
        except Exception:
            pass

    if large_fns or _pm_lines2 > 800:
        _sa2_detail = ""
        if large_fns:
            _sa2_detail += f"≥200줄 함수 {len(large_fns)}개: {large_fns[:3]}"
        if _pm_lines2 > 800:
            if _sa2_detail:
                _sa2_detail += " | "
            _sa2_detail += f"run_pm_agent.py 총 {_pm_lines2}줄"
        findings.append({
            "sa_code":  "SA-2",
            "severity": "MEDIUM",
            "title":    "대형 함수 탐지",
            "detail":   _sa2_detail,
        })
    else:
        findings.append({
            "sa_code":  "SA-2",
            "severity": "INFO",
            "title":    "대형 함수 없음",
            "detail":   f"모든 파이프라인 Agent 함수 200줄 미만 | run_pm_agent.py {_pm_lines2}줄",
        })

    # ── SA-3: PIPELINE_STAGES 순서 vs STAGE_DEPS 일관성 검증 ──────
    pipeline_scripts = [s for s, *_ in PIPELINE_STAGES]
    dep_scripts      = list(STAGE_DEPS.keys())
    missing_in_deps  = [s for s in pipeline_scripts if s not in dep_scripts]
    extra_in_deps    = [s for s in dep_scripts      if s not in pipeline_scripts]

    if missing_in_deps or extra_in_deps:
        findings.append({
            "sa_code":  "SA-3",
            "severity": "HIGH",
            "title":    "PIPELINE_STAGES vs STAGE_DEPS 불일치",
            "detail":   (
                f"PIPELINE 미등록 DEPS: {missing_in_deps} | "
                f"DEPS 불필요 항목: {extra_in_deps}"
            ),
        })
    else:
        findings.append({
            "sa_code":  "SA-3",
            "severity": "INFO",
            "title":    "PIPELINE_STAGES ↔ STAGE_DEPS 일치",
            "detail":   f"{len(pipeline_scripts)}개 스테이지 전체 일치",
        })

    # ── SA-4: run_pm_agent.py 외 파이프라인 Agent Done Criteria 보유 여부 ──
    missing_dc: list[str] = []
    for _sc4, *_ in PIPELINE_STAGES:
        _p4 = AGENTS_DIR / _sc4
        if not _p4.exists():
            continue
        try:
            _src4 = _p4.read_text(encoding="utf-8", errors="ignore")
            if "done_criteria" not in _src4.lower() and "done criteria" not in _src4.lower():
                missing_dc.append(_sc4)
        except Exception:
            pass

    if missing_dc:
        findings.append({
            "sa_code":  "SA-4",
            "severity": "HIGH",
            "title":    "Done Criteria 미정의 Agent",
            "detail":   f"Done Criteria 없음: {missing_dc[:5]}",
        })
    else:
        findings.append({
            "sa_code":  "SA-4",
            "severity": "INFO",
            "title":    "전체 Agent Done Criteria 정의됨",
            "detail":   f"{len(pipeline_scripts)}개 전원 Done Criteria 보유",
        })

    # ── SA-5~SA-8: TQ 품질 체크 — stop_hook.py 구조 감사 ──────────
    _sh_path = BASE_DIR / ".claude" / "hooks" / "stop_hook.py"
    if _sh_path.exists():
        try:
            _sh_src = _sh_path.read_text(encoding="utf-8", errors="ignore")

            _tq_issues: list[str] = []
            if "_extract_text_only" not in _sh_src:
                _tq_issues.append("TQ-1: _extract_text_only 없음 (tool_use 미필터)")
            if "_find_completion_section" not in _sh_src and "섹션" not in _sh_src:
                _tq_issues.append("TQ-2: 섹션 1~4 추출 로직 없음")
            if "_md_to_tg_html" not in _sh_src:
                _tq_issues.append("TQ-3: _md_to_tg_html 없음 (Markdown→HTML 변환 미지원)")
            _tg_send_count = _sh_src.count("_tg_send(")
            if _tg_send_count < 1:
                _tq_issues.append(f"TQ-4: _tg_send 호출 {_tg_send_count}회 (최소 1회 필요)")
            if "_sync_verify" not in _sh_src and "SYNC" not in _sh_src:
                _tq_issues.append("TQ-5: 터미널↔TG 동일성 검증 없음")

            if _tq_issues:
                findings.append({
                    "sa_code":  "SA-5",
                    "severity": "HIGH",
                    "title":    "stop_hook.py TQ 품질 이슈",
                    "detail":   " | ".join(_tq_issues),
                })
            else:
                findings.append({
                    "sa_code":  "SA-5",
                    "severity": "INFO",
                    "title":    "stop_hook.py TQ-1~TQ-5 통과",
                    "detail":   "text필터/섹션추출/MD→HTML/단일TG전송/터미널동일성 전원 확인",
                })
        except Exception as _e5:
            findings.append({
                "sa_code":  "SA-5",
                "severity": "HIGH",
                "title":    "stop_hook.py 읽기 실패",
                "detail":   str(_e5)[:120],
            })
    else:
        findings.append({
            "sa_code":  "SA-5",
            "severity": "HIGH",
            "title":    "stop_hook.py 없음",
            "detail":   f"{_sh_path} 파일 없음 — Stop Hook 비활성화 상태",
        })

    # ── SA-8: 회귀 테스트 스위트 자체 건강도 감사 ──────────────────────────
    findings.append(_sa8_regression_health(AGENTS_DIR))

    # SA 감사 결과 캐시 갱신 (mutable list — 참조 무효화 방지)
    _last_audit_findings.clear()
    _last_audit_findings.extend(findings)

    sev_counts = {}
    for f in findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1
    print(f"[PM] SA 감사 완료 — {sev_counts}")
    for f in findings:
        icon = {"CRITICAL": "🚨", "HIGH": "⚠", "MEDIUM": "📋", "INFO": "ℹ"}.get(f["severity"], "")
        print(f"  {icon} {f['sa_code']} [{f['severity']}] {f['title']}: "
              f"{f['detail'][:90]}")

    return findings
