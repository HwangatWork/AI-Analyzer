# -*- coding: utf-8 -*-
"""
semiconductor_monitor — 반도체 수출 모니터링 패키지

PM Agent 결정 사항:
  [D1] Option B: ECOS 단독 수집 (RSS 없음)
       이유: ECOS는 구조화된 월별 공식 데이터, RSS는 비정형 텍스트로 노이즈 많음
  [D2] L3 분석 깊이: 투자 시사점 포함
       이유: 투자 의사결정 도구에 가장 가치 있는 분석 수준
  [D3] ±10% MoM 초과 시만 알림
       이유: 월별 데이터 특성상 매번 알림은 과도함
  [D4] agents/semiconductor_monitor/ 디렉토리
       이유: 기존 agents/ 패턴 유지

공개 인터페이스
"""

from .data_fetcher import fetch_semiconductor_export
from .analyzer import analyze_export_data
from .notifier import send_alert

__all__ = [
    "fetch_semiconductor_export",
    "analyze_export_data",
    "send_alert",
]
