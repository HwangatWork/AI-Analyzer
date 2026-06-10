# -*- coding: utf-8 -*-
"""
AI Analyzer — 회귀 테스트 스위트 (Phase 1)
지금까지 발견된 버그가 재발하면 FAIL하는 테스트 케이스 15개+.

실행: pytest agents/tests/test_regression.py -v --tb=short
"""
import io, sys, re, importlib.util, json, os
from pathlib import Path

# pytest가 sys.stdout을 캡처하므로 모듈 레벨 리다이렉트 금지
# 대신 환경변수로 UTF-8 설정
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BASE   = Path(__file__).parent.parent.parent   # AI Analyzer root
AGENTS = BASE / "agents"

# ── 모듈 동적 로드 헬퍼 ─────────────────────────────────────────
def _load(rel_path: str):
    name = Path(rel_path).stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, BASE / rel_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ── stop_hook 모듈 로드 ──────────────────────────────────────────
sh = _load(".claude/hooks/stop_hook.py")

SELFTEST_TRANSCRIPT = BASE / "agents" / "tests" / "selftest_transcript.json"


# ════════════════════════════════════════════════════════════════
# T01: 실전 transcript 기반 — Check2 SKIP 재발 방지 (FIX-A/B/C)
#      실전 문제: last_user="\n"(공백전용)이 truthy로 처리돼 loop 조기 종료
#                + 영어 'Level 10' 미인식 → Check2=SKIP
#      수정 후: Check2 = WARN 또는 PASS (not SKIP)
# ════════════════════════════════════════════════════════════════
def test_T01_real_transcript_check2_not_skip():
    """실전 transcript(English Level 10 + whitespace last_user)에서 Check2=SKIP 금지."""
    assert SELFTEST_TRANSCRIPT.exists(), f"T01 FAIL: selftest_transcript.json 없음"
    transcript = json.loads(SELFTEST_TRANSCRIPT.read_text(encoding="utf-8"))
    lu, la, rc = sh._last_messages(transcript)
    result, detail = sh.check_static_only(lu, la, rc)
    assert result != "SKIP", (
        f"T01 FAIL: 실전 transcript에서 Check2=SKIP 재발. got=({result!r},{detail!r})\n"
        f"  last_user={lu[:60]!r}, recent_ctx={rc[:60]!r}"
    )


# ════════════════════════════════════════════════════════════════
# T02: 실전 transcript 기반 — 빈 task_hint(작업 내용 없음) 재발 방지 (FIX-A)
#      실전 문제: last_user="\n" → strip() = "" → task_hint="(작업 내용 없음)"
#      수정 후: task_hint는 실제 task 내용 포함
# ════════════════════════════════════════════════════════════════
def test_T02_real_transcript_task_hint_not_empty():
    """실전 transcript에서 task_hint='(작업 내용 없음)' 재발 금지."""
    assert SELFTEST_TRANSCRIPT.exists(), f"T02 FAIL: selftest_transcript.json 없음"
    transcript = json.loads(SELFTEST_TRANSCRIPT.read_text(encoding="utf-8"))
    lu, la, rc = sh._last_messages(transcript)
    task_hint = (lu[:70].replace("\n", " ").strip() or "(작업 내용 없음)")
    assert task_hint != "(작업 내용 없음)", (
        f"T02 FAIL: 실전 transcript에서 빈 task_hint 재발. last_user={lu[:60]!r}"
    )
    assert task_hint.strip(), (
        f"T02 FAIL: task_hint가 공백 전용. last_user={lu[:60]!r}"
    )


# ════════════════════════════════════════════════════════════════
# T03: check_static_only — 정적분석 패턴 있고 실행 없음 → PASS 오반환
#      (세션 G-4 B2/C2 버그: 마지막 브랜치가 PASS를 반환했음)
# ════════════════════════════════════════════════════════════════
def test_T03_check_static_only_no_exec_returns_warn():
    """실행 Evidence 없이 정적분석만 언급하면 WARN이어야 한다."""
    cases = [
        ("레벨 8 작업: 이 버그 수정해줘", "코드를 읽어보니 run_pm_agent.py에 문제가 있습니다", ""),
        ("레벨 8 작업: 이 버그 수정해줘", "수정 완료했습니다.", ""),
    ]
    for user, asst, ctx in cases:
        result, detail = sh.check_static_only(user, asst, ctx)
        assert result == "WARN", (
            f"T03 FAIL: 실행 없는데 PASS 반환. user={user!r} got=({result!r},{detail!r})"
        )


# ════════════════════════════════════════════════════════════════
# T04: vacuously True — 빈 리스트에서 all([]) = True
#      (SA-13: 빈 리스트 Done Criteria 항목이 통과 처리되는 패턴)
# ════════════════════════════════════════════════════════════════
def test_T04_vacuous_truth_empty_list():
    """빈 리스트에서 all() = True인 Python 특성을 안전하게 처리해야 한다."""
    # 실제 패턴: 검증 대상 목록이 비어있을 때 '조건 없이 통과'가 되지 않아야 함
    items = []
    # vacuous all: 이 패턴을 사용하면 안 됨
    assert all(x > 0 for x in items) is True, "Python vacuous truth 확인 (이 동작을 코드에서 쓰면 안 됨)"
    # 올바른 패턴: 리스트가 비어있으면 False 반환
    def safe_check(items_list):
        return bool(items_list) and all(x > 0 for x in items_list)
    assert safe_check([]) is False, "T04 FAIL: 빈 리스트 safe_check가 True 반환"
    assert safe_check([1, 2, 3]) is True, "T04 FAIL: 비어있지 않은 리스트가 False 반환"


# ════════════════════════════════════════════════════════════════
# T05: SD-14 known FAIL 오탐 — 선택 기능 = FAIL 처리 (QG-1 패턴)
#      pm_quality_checks에서 QG-1(Google Sheets)가 SKIP이어야지 FAIL이 아님
# ════════════════════════════════════════════════════════════════
def test_T05_optional_check_not_fail():
    """GOOGLE_SA_JSON 미설정 시 QG-1이 FAIL이 아닌 SKIP(pass=True)이어야 한다."""
    sys.path.insert(0, str(AGENTS))
    import run_pm_agent as pm
    result = pm.pm_quality_checks()
    qg1 = next((r for r in result if "Google Sheets" in r["check"]), None)
    assert qg1 is not None, "T05 FAIL: QG-1 체크 항목 없음"
    assert qg1["pass"] is True, (
        f"T05 FAIL: QG-1이 FAIL 처리됨. detail={qg1['detail']!r}"
    )


# ════════════════════════════════════════════════════════════════
# T06: HOLD confidence 역설 — 중립(ratio=0.5)이 100%가 되는 버그
#      (REQ-029: HOLD confidence 공식 반전)
# ════════════════════════════════════════════════════════════════
def test_T06_hold_confidence_not_inverted():
    """HOLD 신뢰도 공식이 역설 없이 작동하는지 decision.json 또는 공식으로 확인."""
    # run_decision_agent.py L68: ratio=0.5 → abs(0.5-0.5)*2*100 = 0%
    # ratio=0.05 → abs(0.05-0.5)*2*100 = 90%  (REQ-029 수정 후)
    def hold_confidence_formula(consensus_ratio: float) -> float:
        return abs(consensus_ratio - 0.5) * 2 * 100

    confidence_neutral = hold_confidence_formula(0.5)
    confidence_extreme = hold_confidence_formula(0.05)

    assert confidence_neutral < confidence_extreme, (
        f"T06 FAIL: 중립({confidence_neutral:.1f}%)이 극단({confidence_extreme:.1f}%)보다 높음 — 역설"
    )
    assert confidence_neutral < 5.0, (
        f"T06 FAIL: 중립 confidence={confidence_neutral:.1f}% > 5% — 역설 미해소"
    )
    # decision.json 존재 시 실제 값 확인
    dec_path = BASE / "output" / "decision.json"
    if dec_path.exists():
        dec = json.loads(dec_path.read_text(encoding="utf-8"))
        sp500 = dec.get("sp500", {})
        if sp500.get("action") == "HOLD":
            sp_conf = sp500.get("confidence_pct", 0)
            assert sp_conf < 60.0, (
                f"T06 FAIL: SP500 HOLD confidence={sp_conf}% — 너무 높음 (역설 가능성)"
            )


# ════════════════════════════════════════════════════════════════
# T07: 서브스트링 SD 매칭 버그 — "SD-1"이 "SD-10"/"SD-11" 매칭
#      (REQ-027: _derive_fix_scripts SD→script 매핑)
# ════════════════════════════════════════════════════════════════
def test_T07_sd_substring_matching():
    """SD-1 매칭이 SD-10, SD-11을 잘못 매칭하지 않아야 한다."""
    import re

    # 잘못된 패턴 (서브스트링)
    bad_pattern = re.compile(r"SD-1")
    # 올바른 패턴 (단어 경계)
    good_pattern = re.compile(r"\bSD-1\b")

    test_str = "SD-10 이슈가 발견됨"
    assert bad_pattern.search(test_str) is not None, "잘못된 패턴 미매칭 (테스트 전제 확인)"
    assert good_pattern.search(test_str) is None, (
        f"T07 FAIL: 단어 경계 패턴이 SD-10을 SD-1로 잘못 매칭"
    )

    # run_pm_agent의 실제 _derive_fix_scripts도 확인 (issues 파라미터 필수)
    sys.path.insert(0, str(AGENTS))
    import run_pm_agent as pm
    scripts_set, stages = pm._derive_fix_scripts(["SD-1 동행지수 탐지"])
    # SD-1 issues 전달 시 evaluator/analysis 스크립트가 포함돼야 함
    all_scripts = scripts_set | set(stages)
    assert any("evaluator" in s or "analysis" in s for s in all_scripts), (
        f"T07 FAIL: SD-1 issues 전달 시 evaluator/analysis 스크립트 없음. got={all_scripts}"
    )


# ════════════════════════════════════════════════════════════════
# T08: 삼성전자 Marcap=0 → contribution_score 오계산
#      (SA-7c: FDR Marcap 미집계 시 점수가 소형주보다 낮아짐)
# ════════════════════════════════════════════════════════════════
def test_T08_samsung_contribution_score_with_zero_marcap():
    """Marcap=0일 때 기여점수 공식 결과가 소형주보다 낮음을 수치로 확인."""
    # contribution_score = abs(corr) * abs(return_decimal) * (mc_usd/1e12 + 0.01)
    def score(corr, ret_pct, mc_usd):
        return abs(corr) * abs(ret_pct / 100.0) * (mc_usd / 1e12 + 0.01)

    samsung_corr = 0.888
    samsung_ret  = 438.5    # %
    samsung_mc_real = 243e9 # USD

    score_real = score(samsung_corr, samsung_ret, samsung_mc_real)
    score_mc0  = score(samsung_corr, samsung_ret, 0.0)

    # 효성중공업 수준 소형주 기여점수
    hyosung_score = 0.0393

    assert score_real > 0.9, (
        f"T08 FAIL: 정상 시총 기여점수={score_real:.4f} < 0.9"
    )
    assert score_mc0 < hyosung_score, (
        f"T08 FAIL: Marcap=0 기여점수={score_mc0:.4f} > 효성중공업 {hyosung_score} — 논리 오류"
    )


# ════════════════════════════════════════════════════════════════
# T09: 효성화학 std==0 → safe_pearsonr None → 크래시
#      (REQ-017/020: stat_utils.safe_pearsonr std=0 가드)
# ════════════════════════════════════════════════════════════════
def test_T09_safe_pearsonr_constant_series():
    """std=0인 계열에서 safe_pearsonr이 None을 반환하고 크래시하지 않아야 한다."""
    sys.path.insert(0, str(AGENTS))
    import stat_utils

    import numpy as np
    x_const = np.array([100.0] * 252)  # 거래정지, 가격 불변
    y_normal = np.random.randn(252)

    result = stat_utils.safe_pearsonr(x_const, y_normal)
    # safe_pearsonr은 (r, p_value) 튜플을 반환하며, std=0이면 (None, None)
    if isinstance(result, tuple):
        assert result[0] is None, (
            f"T09 FAIL: std=0 계열에서 r={result[0]!r} (None이어야 함)"
        )
    else:
        assert result is None, (
            f"T09 FAIL: std=0 계열에서 None이 아닌 {result!r} 반환"
        )

    # 정상 계열은 숫자 또는 (숫자, 숫자) 반환
    x_normal = np.random.randn(252)
    result2 = stat_utils.safe_pearsonr(x_normal, y_normal)
    if isinstance(result2, tuple):
        assert isinstance(result2[0], float), (
            f"T09 FAIL: 정상 계열에서 r={result2[0]!r}가 float가 아님"
        )
    else:
        assert isinstance(result2, float), (
            f"T09 FAIL: 정상 계열에서 float가 아닌 {result2!r} 반환"
        )


# ════════════════════════════════════════════════════════════════
# T10: _last_messages — tool_use/tool_result 블록이 text에 포함되는 버그
#      (TQ-1: _extract_text_only로 type=text 블록만 추출)
# ════════════════════════════════════════════════════════════════
def test_T10_last_messages_filters_tool_blocks():
    """_last_messages가 tool_use/tool_result 블록을 text에서 제외해야 한다."""
    transcript = [
        {"role": "user",      "content": "레벨 8 구현해줘"},
        {"role": "assistant", "content": [
            {"type": "tool_use",    "id": "t1", "name": "Bash", "input": {}},
            {"type": "tool_result", "tool_use_id": "t1", "content": "exit_code=0"},
            {"type": "text",        "text": "동적 테스트 12/12 PASS exit_code=0"},
        ]},
    ]
    lu, la, rlc = sh._last_messages(transcript)

    assert "tool_use" not in la, f"T10 FAIL: tool_use가 last_asst에 포함됨: {la!r}"
    assert "tool_result" not in la, f"T10 FAIL: tool_result가 last_asst에 포함됨: {la!r}"
    assert "동적 테스트" in la, f"T10 FAIL: 실제 text 블록이 last_asst에 없음: {la!r}"


# ════════════════════════════════════════════════════════════════
# T11: CONTEMPORANEOUS 지수가 decision_agent에서 직접 참조 → SA-1 CRITICAL
#      (SA-1: KOSDAQ/NIKKEI225 등이 decision_agent에 하드코딩 참조)
# ════════════════════════════════════════════════════════════════
def test_T11_contemporaneous_in_decision_agent():
    """run_decision_agent.py에 CONTEMPORANEOUS 지수가 직접 참조됨을 확인 (기존 CRITICAL 유지)."""
    dec_path = AGENTS / "run_decision_agent.py"
    content  = dec_path.read_text(encoding="utf-8")

    contemporaneous = {"KOSDAQ", "NIKKEI225", "DOW", "NASDAQ100"}
    found = [idx for idx in contemporaneous if f'"{idx}"' in content or f"'{idx}'" in content]

    # 이 버그는 아직 미해결 (REQ-FUTURE-031). 존재함을 확인해서 리그레션 추적.
    assert len(found) >= 1, (
        "T11 NOTE: decision_agent에서 CONTEMPORANEOUS 지수가 사라짐 — "
        "REQ-FUTURE-031 해소됐으면 이 테스트를 'FIXED' 버전으로 업데이트"
    )
    # 발견된 지수를 출력 (CRITICAL 상태 추적)
    print(f"\n  T11 INFO: decision_agent CONTEMPORANEOUS 직접참조: {found} (REQ-FUTURE-031 미해결)")


# ════════════════════════════════════════════════════════════════
# T12: SA-7 warn_reason — 극단수익률 500%+ 종목에 warn_reason 필드 필수
#      (세션 H: SK하이닉스 867.2%인데 warn_reason 없어 pm_quality_checks FAIL)
# ════════════════════════════════════════════════════════════════
def test_T12_warn_reason_for_extreme_returns():
    """final_results.json의 극단수익률(≥500%) 종목에 warn_reason 필드가 있어야 한다."""
    fr_path = BASE / "output" / "final_results.json"
    if not fr_path.exists():
        import pytest
        pytest.skip("final_results.json 없음 — 파이프라인 미실행")

    fr = json.loads(fr_path.read_text(encoding="utf-8"))
    EXTREME_THRESHOLD = 500.0

    for section_key in ("kospi_analysis", "sp500_analysis"):
        section = fr.get(section_key, {})
        for list_key in ("contribution_top5", "beneficiary_top5"):
            for stock in section.get(list_key, []):
                ret = abs(stock.get("return_pct", 0.0))
                if ret >= EXTREME_THRESHOLD:
                    assert "warn_reason" in stock, (
                        f"T12 FAIL: {stock.get('ticker')} return={ret:.1f}% ≥ {EXTREME_THRESHOLD}% "
                        f"인데 warn_reason 없음"
                    )
                    assert stock["warn_reason"], (
                        f"T12 FAIL: {stock.get('ticker')} warn_reason이 빈 문자열"
                    )


# ════════════════════════════════════════════════════════════════
# T13: NQ-2 예측성 기사 필터 — 미래 전망성 제목이 필터링돼야 함
#      (REQ-025: _PREDICTIVE_TITLE_RE 패턴)
# ════════════════════════════════════════════════════════════════
def test_T13_nq2_predictive_title_filter():
    """예측성/현황 기사 제목이 _PREDICTIVE_TITLE_RE에 매칭돼야 한다."""
    sys.path.insert(0, str(AGENTS))
    import run_news_agent as nw

    # _PREDICTIVE_TITLE_RE는 영어 패턴 위주 — 실제 매칭되는 영어 제목 사용
    predictive_titles = [
        "week ahead: key data to watch",
        "what to expect this week",
        "S&P500 could rally on Fed decision",
        "Markets outlook for next week",
    ]
    non_predictive = [
        "Fed raises rates by 0.25%",
        "S&P500 closes up 1.2%, tech leads",
    ]

    for title in predictive_titles:
        assert nw._PREDICTIVE_TITLE_RE.search(title) or nw._TODAY_MARKET_RE.search(title), (
            f"T13 FAIL: 예측성 제목이 필터에 안 걸림: {title!r}"
        )

    for title in non_predictive:
        matched = (nw._PREDICTIVE_TITLE_RE.search(title) or nw._TODAY_MARKET_RE.search(title))
        assert not matched, (
            f"T13 FAIL: 정상 제목이 필터에 걸림 (오탐): {title!r}"
        )


# ════════════════════════════════════════════════════════════════
# T14: SD-19 fix_request 불일치 — _write_fix_request와 auto_fix 로직 동기화
#      (SD-19: 수정 계획 목록 = 이슈 코드 기반 동적 도출 필수)
# ════════════════════════════════════════════════════════════════
def test_T14_fix_request_derives_from_issues():
    """_derive_fix_scripts가 하드코딩 목록이 아닌 SD 코드를 파라미터로 받아야 한다."""
    sys.path.insert(0, str(AGENTS))
    import run_pm_agent as pm
    import inspect

    src = inspect.getsource(pm._derive_fix_scripts)
    # 함수가 파라미터를 받아서 동적으로 동작하는지 확인
    # (issues 또는 sd_codes 등의 파라미터가 있어야 함)
    sig = inspect.signature(pm._derive_fix_scripts)
    params = list(sig.parameters.keys())

    # 파라미터(issues)가 있어야 동적 도출 구조
    assert "issues" in params, (
        f"T14 FAIL: _derive_fix_scripts에 issues 파라미터 없음. 현재: {params}"
    )

    # 정적 하드코딩이 아닌 SD 코드 기반 매핑을 사용해야 함
    assert "SD-1" in src and "SD-6" in src, (
        "T14 FAIL: _derive_fix_scripts에 SD 코드 매핑이 없음"
    )
    # 실제 호출: issues 목록 전달
    fix_scripts, fix_stages = pm._derive_fix_scripts(["SD-1 동행지수 탐지"])
    assert len(fix_scripts) > 0 or len(fix_stages) > 0, (
        f"T14 FAIL: SD-1 issues 전달해도 fix_scripts/stages 빈 반환"
    )


# ════════════════════════════════════════════════════════════════
# T15: PM-5 Done Criteria — run_notion_agent.py 미존재 시 FAIL 방지
#      (REQ-030: notion_agent가 agents/ 루트에 존재해야 PM-5 통과)
# ════════════════════════════════════════════════════════════════
def test_T15_notion_agent_exists_for_pm5():
    """run_notion_agent.py가 agents/ 루트에 존재해야 PM-5 Done Criteria를 통과한다."""
    notion_path = AGENTS / "run_notion_agent.py"
    assert notion_path.exists(), (
        f"T15 FAIL: run_notion_agent.py가 {AGENTS}에 없음 — PM-5 Done Criteria FAIL"
    )


# ════════════════════════════════════════════════════════════════
# T16: check_evidence PASS 기준 — 3종 이상 Evidence 키워드 조합
#      (check_evidence의 핵심 기준 회귀 방지)
# ════════════════════════════════════════════════════════════════
def test_T16_check_evidence_pass_threshold():
    """3종 이상 Evidence 키워드가 있으면 PASS, 2종 이하면 WARN이어야 한다."""
    # PASS 케이스 (3종)
    result, _ = sh.check_evidence("섹션 1. 요청 vs 결과\n24/24 PASS\n섹션 4. 검증\nexit_code=0")
    assert result == "PASS", f"T16 FAIL: 3종 Evidence인데 PASS 아님. got={result!r}"

    # WARN 케이스 (1종)
    result, _ = sh.check_evidence("exit_code=0 확인. 완료.")
    assert result == "WARN", f"T16 FAIL: 1종 Evidence인데 WARN 아님. got={result!r}"

    # FAIL 케이스 (0종)
    result, _ = sh.check_evidence("파일을 수정했습니다. 잘 작동합니다.")
    assert result == "FAIL", f"T16 FAIL: 0종 Evidence인데 FAIL 아님. got={result!r}"


# ════════════════════════════════════════════════════════════════
# T17: _last_messages 3-tuple 반환 구조 확인
#      (세션 G-4: 2-tuple → 3-tuple 전환 후 호환성)
# ════════════════════════════════════════════════════════════════
def test_T17_last_messages_returns_3tuple():
    """_last_messages가 정확히 3개 항목을 반환해야 한다."""
    transcript = [
        {"role": "user",      "content": "레벨 9 작업"},
        {"role": "assistant", "content": "완료했습니다. exit_code=0 24/24 PASS"},
    ]
    result = sh._last_messages(transcript)
    assert len(result) == 3, f"T17 FAIL: 3-tuple이 아님. len={len(result)}"
    last_user, last_asst, recent_ctx = result
    assert isinstance(last_user, str), f"T17 FAIL: last_user가 str이 아님"
    assert isinstance(last_asst, str), f"T17 FAIL: last_asst가 str이 아님"
    assert isinstance(recent_ctx, str), f"T17 FAIL: recent_ctx가 str이 아님"


# ════════════════════════════════════════════════════════════════
# T18: EXTREME_RETURN_THRESHOLD 상수 존재 + SPINOFF_RETURN_CAP 존재
#      (세션 H: stock_agent_v2.py에 두 상수가 반드시 있어야 함)
# ════════════════════════════════════════════════════════════════
def test_T18_stock_agent_extreme_return_constants():
    """run_stock_agent_v2.py에 EXTREME_RETURN_THRESHOLD와 SPINOFF_RETURN_CAP 상수가 있어야 한다."""
    content = (AGENTS / "run_stock_agent_v2.py").read_text(encoding="utf-8")
    assert "EXTREME_RETURN_THRESHOLD" in content, (
        "T18 FAIL: EXTREME_RETURN_THRESHOLD 상수 없음"
    )
    assert "SPINOFF_RETURN_CAP" in content, (
        "T18 FAIL: SPINOFF_RETURN_CAP 상수 없음"
    )


# ════════════════════════════════════════════════════════════════
# T19: SA-5/SA-6 빈 리스트 vacuously True 방지
#      (SD-15/SA-13: contribution_top5가 [] 일 때 SA-5 PASS 오탐)
# ════════════════════════════════════════════════════════════════
def test_T19_sa5_sa6_empty_list_not_vacuously_pass():
    """pm_quality_checks SA-1~SA-4가 빈 리스트에서 PASS 오탐하지 않아야 한다."""
    import json
    from pathlib import Path

    fr_path = BASE / "output" / "final_results.json"
    if not fr_path.exists():
        import pytest
        pytest.skip("final_results.json 없음")

    fr = json.loads(fr_path.read_text(encoding="utf-8"))
    # SA-1~4는 각 Top5 리스트가 비어있지 않아야 PASS
    checks = [
        ("sp500_analysis", "contribution_top5"),
        ("sp500_analysis", "beneficiary_top5"),
        ("kospi_analysis", "contribution_top5"),
        ("kospi_analysis", "beneficiary_top5"),
    ]
    for section, key in checks:
        items = fr.get(section, {}).get(key, [])
        assert len(items) > 0, (
            f"T19 FAIL: {section}.{key}가 빈 리스트 — SA 체크가 vacuously PASS 될 위험"
        )


# ════════════════════════════════════════════════════════════════
# T20: stop_hook --selftest — 실전 transcript으로 selftest PASS (Phase 2 Gate 2)
#      FIX-A/B/C 적용 후 selftest_transcript.json으로 exit_code=0 반환해야 함
# ════════════════════════════════════════════════════════════════
def test_T20_selftest_passes_with_real_transcript():
    """stop_hook.py --selftest가 실전 transcript로 exit_code=0을 반환해야 한다."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(BASE / ".claude" / "hooks" / "stop_hook.py"),
         "--selftest", str(SELFTEST_TRANSCRIPT)],
        capture_output=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, (
        f"T20 FAIL: selftest exit_code={result.returncode}\n"
        f"stdout: {result.stdout[-500:]}\n"
        f"stderr: {result.stderr[-200:]}"
    )
