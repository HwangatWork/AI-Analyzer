# -*- coding: utf-8 -*-
"""
SD-14 회귀 감지 실제 작동 테스트
- pm_baseline.json에 qc_pass_count를 실제보다 5 높게 임시 설정
- pm_self_diagnosis()의 SD-14 로직을 격리 실행
- 회귀 경고 발생 + Telegram 발송 확인
- baseline 원본 복원
"""
import io, sys
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json, os, re, time, hashlib, urllib.request
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

BASE_DIR      = Path(__file__).parent.parent.parent
PROC_DIR      = BASE_DIR / "data" / "processed"
BASELINE_FILE = PROC_DIR / "pm_baseline.json"

# ── 원본 백업 ──────────────────────────────────────────────────
original_baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
print(f"[백업] 원본 baseline: {json.dumps(original_baseline, ensure_ascii=False)[:120]}")

# ── 임시 baseline: qc_pass_count를 현재값+5로 부풀리기 ─────────
REAL_PASS_COUNT = 23   # pm_quality_checks()로 확인한 실제 값
FAKE_BASELINE_COUNT = REAL_PASS_COUNT + 5  # 28 → 실제 23보다 5 높음

inflated = dict(original_baseline)
inflated["qc_pass_count"]    = FAKE_BASELINE_COUNT
inflated["qc_total"]         = 24
inflated["qc_failed_checks"] = []  # 이전엔 실패 없었다고 가정
BASELINE_FILE.write_text(json.dumps(inflated, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[테스트] baseline qc_pass_count 임시 설정: {FAKE_BASELINE_COUNT}/24 (실제: {REAL_PASS_COUNT}/24)")

# ── SD-14 로직 격리 실행 ───────────────────────────────────────
# (run_pm_agent.py pm_self_diagnosis의 SD-14 블록과 동일)
sys.path.insert(0, str(BASE_DIR / "agents"))
from run_pm_agent import pm_quality_checks, _tg_send

baseline_for_test = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

try:
    _qc14      = pm_quality_checks()
    _qc14_pass = sum(1 for c in _qc14 if c["pass"])
    _qc14_base = baseline_for_test.get("qc_pass_count")

    print(f"\n[SD-14] 현재 PASS: {_qc14_pass}/{len(_qc14)}")
    print(f"[SD-14] 기준선 PASS: {_qc14_base}/{baseline_for_test.get('qc_total',24)}")

    if _qc14_base is not None and _qc14_pass < _qc14_base:
        _regressed14  = _qc14_base - _qc14_pass
        _prev_fails14 = set(baseline_for_test.get("qc_failed_checks", []))
        _new_fails14  = [c["check"] for c in _qc14
                         if not c["pass"] and c["check"] not in _prev_fails14]
        msg = (
            f"SD-14 QC 회귀 감지 [TEST]: "
            f"{_qc14_pass}/{len(_qc14)} PASS (기준선 {_qc14_base} -> {_qc14_pass}, "
            f"-{_regressed14}개 감소). 신규 실패: {_new_fails14}"
        )
        print(f"\n[DETECTED] {msg}")

        tg_msg = (
            f"[TEST] SD-14 QC 회귀 감지\n"
            f"기준선 {_qc14_base}/{len(_qc14)} -> "
            f"현재 {_qc14_pass}/{len(_qc14)} PASS\n"
            f"신규 실패: {', '.join(_new_fails14[:5]) or '없음'}"
        )
        _tg_send(tg_msg)
        print("[TELEGRAM] 회귀 경고 발송 완료")
        test_passed = True
    else:
        print("[ERROR] SD-14 회귀 감지 미발생 — 로직 오류")
        test_passed = False

except Exception as e:
    print(f"[ERROR] {e}")
    test_passed = False

finally:
    # ── 원본 복원 ─────────────────────────────────────────────
    BASELINE_FILE.write_text(
        json.dumps(original_baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[복원] baseline 원본 복원 완료")

print(f"\n[RESULT] SD-14 테스트 {'PASS' if test_passed else 'FAIL'}")
sys.exit(0 if test_passed else 1)
