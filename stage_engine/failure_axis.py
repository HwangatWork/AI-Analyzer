# -*- coding: utf-8 -*-
"""Stage Engine v3.0 — failure_axis: 실패 축 F ∈ [0,1].

컴포넌트 (가중치 합 = 1.0):
- F1 catalyst-void        0.30  — DART 단일판매·공급계약 공시 부재 (구현)
- F2 trickle-down-lag     0.30  — 스텁 (Phase B)
- F3 price-transfer-fail  0.25  — 스텁 (Phase B)
- F4 dilution-risk        0.15  — 스텁 (Phase B)

None 처리: 컴포넌트 None → 가중 평균에서 제외, f_coverage(가용 가중치 합)를
반환해 상위 Confidence에 결측 인지 전파. 전 컴포넌트 None → F = None.

DART 키: 프로젝트 루트 .env의 DART_API_KEY (FRED_API_KEY 패턴).
키 부재 → F1 = None + blocker 문자열 (리포트 Section 2 게재용).
보안: 키 값은 어떤 경로로도 출력/로깅하지 않는다 (CLAUDE.md 보안 규칙).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

F_WEIGHTS = {
    "F1_catalyst_void": 0.30,
    "F2_trickle_down_lag": 0.30,
    "F3_price_transfer_failure": 0.25,
    "F4_dilution_risk": 0.15,
}
F1_LOOKBACK_DAYS = 180  # 단일판매·공급계약 공시 탐색 폭
_DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

NO_KEY_BLOCKER = ("DART_API_KEY 미등록 (.env 부재 확인 2026-07-04) — "
                  "F1 catalyst-void 는 None 반환. 키 등록 후 재실행 필요 "
                  "(OL-1 프로토콜: .env + gh secret + workflow env 3중 등록).")


def _load_dart_key() -> str | None:
    env_path = Path(__file__).parents[1] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DART_API_KEY=") and len(line.split("=", 1)[1]) > 0:
            return line.split("=", 1)[1].strip()
    return None


class DartClient:
    """DART OpenAPI 최소 클라이언트 (list.json). 키 없으면 available=False."""

    def __init__(self):
        self._key = _load_dart_key()

    @property
    def available(self) -> bool:
        return self._key is not None

    def single_sales_contracts(self, corp_code: str, start: date,
                               end: date) -> list[dict] | None:
        """단일판매·공급계약체결 공시 목록. 키 부재/오류 → None.

        주의: 키 미보유 환경에서는 실호출 미검증 (리포트 S2 기재).
        corp_code는 DART 8자리 고유번호 (종목코드 아님 — 매핑은 Phase B).
        """
        if not self.available:
            return None
        params = {
            "crtfc_key": self._key,
            "corp_code": corp_code,
            "bgn_de": start.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "pblntf_ty": "I",  # 거래소공시
            "page_count": "100",
        }
        url = _DART_LIST_URL + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if data.get("status") != "000":
            return [] if data.get("status") == "013" else None  # 013 = 조회 결과 없음
        return [r for r in data.get("list", [])
                if "단일판매" in r.get("report_nm", "")
                or "공급계약" in r.get("report_nm", "")]


def f1_catalyst_void(corp_code: str | None, asof: date,
                     client: DartClient | None = None) -> float | None:
    """trailing 180일 내 단일판매·공급계약 공시 0건 → 1.0, 있으면 0.0.

    키 부재 / corp_code 미매핑 / API 오류 → None.
    """
    client = client or DartClient()
    if not client.available or corp_code is None:
        return None
    filings = client.single_sales_contracts(
        corp_code, asof - timedelta(days=F1_LOOKBACK_DAYS), asof)
    if filings is None:
        return None
    return 1.0 if len(filings) == 0 else 0.0


def f2_trickle_down_lag(ticker: str, asof: date) -> float | None:
    return None  # Phase B 스텁


def f3_price_transfer_failure(ticker: str, asof: date) -> float | None:
    return None  # Phase B 스텁


def f4_dilution_risk(ticker: str, asof: date) -> float | None:
    return None  # Phase B 스텁


def failure_score(ticker: str, asof: date, corp_code: str | None = None,
                  client: DartClient | None = None) -> tuple[float | None, dict]:
    """(F, detail). F = 가용 컴포넌트의 가중 평균 (가중치 재정규화).

    detail = {components, f_coverage, blockers}
    f_coverage = 가용 가중치 합 ∈ [0,1] — 상위 Confidence 결측 인지용.
    """
    client = client or DartClient()
    components = {
        "F1_catalyst_void": f1_catalyst_void(corp_code, asof, client),
        "F2_trickle_down_lag": f2_trickle_down_lag(ticker, asof),
        "F3_price_transfer_failure": f3_price_transfer_failure(ticker, asof),
        "F4_dilution_risk": f4_dilution_risk(ticker, asof),
    }
    blockers = [] if client.available else [NO_KEY_BLOCKER]
    avail = {k: v for k, v in components.items() if v is not None}
    f_coverage = sum(F_WEIGHTS[k] for k in avail)
    if not avail:
        return None, {"components": components, "f_coverage": 0.0,
                      "blockers": blockers}
    f = sum(F_WEIGHTS[k] * v for k, v in avail.items()) / f_coverage
    return f, {"components": components, "f_coverage": f_coverage,
               "blockers": blockers}
