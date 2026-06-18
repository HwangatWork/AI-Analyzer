# -*- coding: utf-8 -*-
"""
semiconductor_monitor/analyzer.py — L3 분석 엔진

PM Agent 결정 사항:
  [D2] L3 분석 깊이: 투자 시사점 포함
       이유: 투자 의사결정 도구에 가장 가치 있는 분석 수준
  [D4] agents/semiconductor_monitor/ 디렉토리
       이유: 기존 agents/ 패턴 유지

환경변수:
  ANTHROPIC_API_KEY — 없으면 규칙 기반 fallback 사용

출력: 한국어 텍스트 200자 이내, 투자 시사점 포함
"""

import io
import os
import sys
from pathlib import Path

# Windows cp949 환경에서 한글 UnicodeEncodeError 방지
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# dotenv 로드
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

# anthropic 패키지 선택적 임포트
try:
    import anthropic as _anthropic_lib
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_lib = None
    _ANTHROPIC_AVAILABLE = False


def _rule_based_analysis(export_data: dict) -> str:
    """
    규칙 기반 분석 (Claude API 없을 때 fallback).
    [D2] 투자 시사점 포함.
    """
    summary = export_data.get("summary", {})
    mom = summary.get("mom_change_pct", 0.0)
    yoy = summary.get("yoy_change_pct", 0.0)
    latest_val = summary.get("latest_value", 0.0)
    latest_month = summary.get("latest_month", "")
    share_pct = summary.get("export_share_pct", 18.4)

    # 월 레이블 변환
    if len(latest_month) == 6:
        month_label = f"{latest_month[:4]}년 {latest_month[4:]}월"
    else:
        month_label = latest_month

    # MoM 방향성 판단
    if mom > 10:
        mom_desc = f"MoM +{mom:.1f}% 급증"
        inv_hint = "반도체 장비·소재주 비중 확대 고려"
    elif mom > 3:
        mom_desc = f"MoM +{mom:.1f}% 회복세"
        inv_hint = "반도체 대형주 점진적 매수 유효"
    elif mom >= -3:
        mom_desc = f"MoM {mom:+.1f}% 보합"
        inv_hint = "관망 후 추세 확인 필요"
    elif mom >= -10:
        mom_desc = f"MoM {mom:+.1f}% 둔화"
        inv_hint = "반도체 비중 축소 검토"
    else:
        mom_desc = f"MoM {mom:+.1f}% 급감"
        inv_hint = "반도체 섹터 리스크 관리 필요"

    # YoY 방향성
    if yoy > 0:
        yoy_desc = f"YoY +{yoy:.1f}% 성장"
    else:
        yoy_desc = f"YoY {yoy:+.1f}% 역성장"

    text = (
        f"{month_label} 반도체 수출 {latest_val:,.0f}백만달러 ({share_pct:.1f}% 비중). "
        f"{mom_desc}, {yoy_desc}. "
        f"[투자시사점] {inv_hint}."
    )

    # 200자 이내 보장
    if len(text) > 200:
        text = text[:197] + "..."

    return text


def _claude_analysis(export_data: dict) -> str:
    """
    Claude API를 사용한 L3 분석.
    [D2] 투자 시사점 포함.
    API 키 없거나 호출 실패 시 규칙 기반으로 자동 fallback.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key or not _ANTHROPIC_AVAILABLE:
        print("[analyzer] ANTHROPIC_API_KEY 없거나 패키지 없음 — 규칙 기반 분석 사용")
        return _rule_based_analysis(export_data)

    summary = export_data.get("summary", {})
    data_rows = export_data.get("data", [])
    mom = summary.get("mom_change_pct", 0.0)
    yoy = summary.get("yoy_change_pct", 0.0)
    latest_val = summary.get("latest_value", 0.0)
    latest_month = summary.get("latest_month", "")

    # 최근 6개월 트렌드 요약 (프롬프트용)
    recent = data_rows[-6:] if len(data_rows) >= 6 else data_rows
    trend_lines = ", ".join(
        f"{r['label']}:{r['value']:,.0f}" for r in recent
    )

    prompt = (
        f"한국 반도체 수출 데이터 분석 — 200자 이내 한국어로 답변:\n"
        f"최신월: {latest_month}, 수출액: {latest_val:,.0f}백만달러\n"
        f"MoM 변화: {mom:+.1f}%, YoY 변화: {yoy:+.1f}%\n"
        f"최근 6개월 추이: {trend_lines}\n\n"
        f"분석 요청: 현재 반도체 수출 상황을 평가하고 투자 시사점(매수/관망/축소)을 "
        f"반드시 포함하여 200자 이내로 요약하라."
    )

    try:
        client = _anthropic_lib.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # 200자 이내 보장
        if len(text) > 200:
            text = text[:197] + "..."
        print(f"[analyzer] Claude API 분석 완료 ({len(text)}자)")
        return text
    except Exception as exc:
        print(f"[analyzer] Claude API 호출 실패: {exc} — 규칙 기반 분석으로 fallback")
        return _rule_based_analysis(export_data)


def analyze_export_data(export_data: dict) -> str:
    """
    [D2] L3 분석: 투자 시사점 포함
    Claude API 없을 시 규칙 기반 fallback 사용.

    Args:
        export_data: fetch_semiconductor_export() 반환값

    Returns:
        한국어 분석 텍스트 (200자 이내, 투자 시사점 포함)
    """
    if not export_data or not export_data.get("summary"):
        return "반도체 수출 데이터 없음 — 분석 불가."

    return _claude_analysis(export_data)


if __name__ == "__main__":
    import json
    # 테스트용 mock 데이터
    mock = {
        "summary": {
            "latest_month": "202405",
            "latest_value": 11234.5,
            "mom_change_pct": 8.2,
            "yoy_change_pct": 15.3,
            "export_share_pct": 18.4,
        },
        "data": [
            {"period": f"20240{i}", "value": 10000 + i * 200, "label": f"2024-0{i}"}
            for i in range(1, 7)
        ],
    }
    result = analyze_export_data(mock)
    print(f"\n[분석 결과] ({len(result)}자):")
    print(result)
