# -*- coding: utf-8 -*-
"""
semiconductor_monitor/data_fetcher.py — ECOS API 클라이언트

PM Agent 결정 사항:
  [D1] Option B: ECOS 단독 수집 (RSS 없음)
       이유: ECOS는 구조화된 월별 공식 데이터, RSS는 비정형 텍스트로 노이즈 많음
  [D4] agents/semiconductor_monitor/ 디렉토리
       이유: 기존 agents/ 패턴 유지

ECOS API 응답 형식:
  {"StatisticSearch": {"list_total_count": N,
                       "ROW": [{"TIME": "202401", "DATA_VALUE": "10234.5"}, ...]}}

환경변수:
  ECOS_API_KEY — 없으면 mock 데이터 반환 (is_mock=True)

출력 파일:
  output/semiconductor_export.json
"""

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
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

BASE_DIR = Path(__file__).parent.parent.parent
OUT_DIR = BASE_DIR / "output"

# config.yaml 로드 (yaml 없으면 기본값 사용)
def _load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    except FileNotFoundError:
        pass
    # 기본값 fallback
    return {
        "ecos": {
            "base_url": "https://ecos.bok.or.kr/api",
            "stat_code": "403Y003",
            "item_code": "261",
            "cycle": "M",
            "lookback_months": 12,
        },
        "scheduler": {
            "retry_max": 3,
            "retry_backoff_base": 2,
        },
        "output": {
            "json_path": "output/semiconductor_export.json",
        },
    }


def _make_mock_data(lookback_months: int = 12) -> dict:
    """
    ECOS API 키 없을 시 현실적인 mock 데이터 반환.
    한국 반도체 수출 실제 트렌드 (2023-2024) 기반으로 생성.
    """
    base_values = [
        9800.0, 10200.0, 10500.0, 10100.0, 9900.0, 10300.0,
        10800.0, 11200.0, 11000.0, 11500.0, 11800.0, 12000.0,
    ]
    now = datetime.now()
    data_rows = []
    # 최근 lookback_months개월치 생성 (오래된 순서)
    for i in range(lookback_months - 1, -1, -1):
        dt = now - timedelta(days=30 * i)
        period = dt.strftime("%Y%m")
        label = dt.strftime("%Y-%m")
        # 순환 인덱스로 현실적 값 매핑
        idx = (lookback_months - 1 - i) % len(base_values)
        value = base_values[idx]
        data_rows.append({"period": period, "value": value, "label": label})

    # summary 계산
    latest = data_rows[-1]
    prev = data_rows[-2] if len(data_rows) >= 2 else data_rows[-1]
    yoy = data_rows[-13] if len(data_rows) >= 13 else data_rows[0]

    mom_pct = round((latest["value"] - prev["value"]) / prev["value"] * 100, 2)
    yoy_pct = round((latest["value"] - yoy["value"]) / yoy["value"] * 100, 2)

    return {
        "last_updated": latest["period"],
        "unit": "지수(2020=100)",
        "is_mock": True,
        "data": data_rows,
        "summary": {
            "latest_month": latest["period"],
            "latest_value": latest["value"],
            "mom_change_pct": mom_pct,
            "yoy_change_pct": yoy_pct,
            "export_share_pct": 18.4,  # 반도체 수출 비중 근사값
        },
    }


def _fetch_ecos_with_retry(
    url: str,
    retry_max: int = 3,
    backoff_base: int = 2,
) -> dict:
    """
    ECOS API 호출 — 최대 retry_max회, 지수 백오프 (backoff_base^attempt 초).
    성공 시 JSON 딕셔너리 반환. 모든 시도 실패 시 예외 발생.
    """
    last_exc = None
    for attempt in range(retry_max):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            wait_sec = backoff_base ** attempt  # 1, 2, 4초 (attempt=0,1,2)
            print(
                f"[data_fetcher] ECOS 요청 실패 (시도 {attempt + 1}/{retry_max}): {exc}"
                f" — {wait_sec}초 후 재시도"
            )
            if attempt < retry_max - 1:
                time.sleep(wait_sec)
    raise RuntimeError(f"ECOS API {retry_max}회 모두 실패: {last_exc}")


def _parse_ecos_response(raw: dict, lookback_months: int = 12) -> list:
    """
    ECOS StatisticSearch 응답을 data 배열로 파싱.
    반환: [{"period": "202401", "value": 10234.5, "label": "2024-01"}, ...]
    """
    ss = raw.get("StatisticSearch", {})
    rows = ss.get("row", ss.get("ROW", []))
    parsed = []
    for row in rows:
        period = row.get("TIME", "")
        raw_val = row.get("DATA_VALUE", "")
        try:
            value = float(raw_val)
        except (ValueError, TypeError):
            continue
        if len(period) == 6:
            label = f"{period[:4]}-{period[4:]}"
        else:
            label = period
        parsed.append({"period": period, "value": value, "label": label})
    # 날짜 오름차순 정렬
    parsed.sort(key=lambda x: x["period"])
    # 최근 lookback_months개월만 반환
    return parsed[-lookback_months:]


def _build_summary(data_rows: list) -> dict:
    """data 배열에서 summary 딕셔너리 계산."""
    if not data_rows:
        return {
            "latest_month": "",
            "latest_value": 0.0,
            "mom_change_pct": 0.0,
            "yoy_change_pct": 0.0,
            "export_share_pct": 0.0,
        }
    latest = data_rows[-1]
    prev = data_rows[-2] if len(data_rows) >= 2 else None
    yoy = data_rows[-13] if len(data_rows) >= 13 else data_rows[0]

    mom_pct = 0.0
    if prev and prev["value"] != 0:
        mom_pct = round((latest["value"] - prev["value"]) / prev["value"] * 100, 2)

    yoy_pct = 0.0
    if yoy["value"] != 0:
        yoy_pct = round((latest["value"] - yoy["value"]) / yoy["value"] * 100, 2)

    # export_share_pct: 전체 수출 대비 반도체 비중은 별도 시리즈 필요,
    # 현재는 근사값 유지 (17~20% 범위)
    export_share_pct = 18.4

    return {
        "latest_month": latest["period"],
        "latest_value": round(latest["value"], 2),
        "mom_change_pct": mom_pct,
        "yoy_change_pct": yoy_pct,
        "export_share_pct": export_share_pct,
    }


def fetch_semiconductor_export() -> dict:
    """
    반도체 수출 데이터를 ECOS API에서 수집하여 반환 및 저장.

    환경변수 ECOS_API_KEY 없으면 mock 데이터 반환 (is_mock=True).

    반환 형식:
    {
        "last_updated": "202405",
        "unit": "지수(2020=100)",
        "is_mock": false,
        "data": [{"period": "202401", "value": 10234.5, "label": "2024-01"}, ...],
        "summary": {
            "latest_month": "202405",
            "latest_value": 11234.5,
            "mom_change_pct": 8.2,
            "yoy_change_pct": 15.3,
            "export_share_pct": 18.4
        }
    }
    """
    cfg = _load_config()
    ecos_cfg = cfg.get("ecos", {})
    sched_cfg = cfg.get("scheduler", {})
    out_cfg = cfg.get("output", {})

    api_key = os.environ.get("ECOS_API_KEY", "").strip()
    lookback = int(ecos_cfg.get("lookback_months", 12))
    retry_max = int(sched_cfg.get("retry_max", 3))
    backoff_base = int(sched_cfg.get("retry_backoff_base", 2))
    output_path = BASE_DIR / out_cfg.get("json_path", "output/semiconductor_export.json")

    # ECOS API 키 없음 → mock 데이터
    if not api_key:
        print("[data_fetcher] ECOS_API_KEY 없음 — mock 데이터 반환")
        result = _make_mock_data(lookback)
        _save_result(result, output_path)
        return result

    # 날짜 범위 계산
    now = datetime.now()
    end_dt = now - timedelta(days=1)
    start_dt = end_dt - timedelta(days=30 * (lookback + 1))
    start_date = start_dt.strftime("%Y%m")
    end_date = end_dt.strftime("%Y%m")

    base_url = ecos_cfg.get("base_url", "https://ecos.bok.or.kr/api")
    stat_code = ecos_cfg.get("stat_code", "403Y001")
    item_code = ecos_cfg.get("item_code", "30911AA")
    cycle = ecos_cfg.get("cycle", "M")

    # URL 구성 (ECOS 공식 포맷) — item_code 포함
    # {base_url}/StatisticSearch/{api_key}/json/kr/1/100/{stat_code}/{cycle}/{start}/{end}/{item_code}
    url = (
        f"{base_url}/StatisticSearch/{api_key}/json/kr/1/100"
        f"/{stat_code}/{cycle}/{start_date}/{end_date}/{item_code}"
    )

    print(f"[data_fetcher] ECOS API 호출: stat_code={stat_code}, item={item_code}, {start_date}~{end_date}")

    try:
        raw = _fetch_ecos_with_retry(url, retry_max=retry_max, backoff_base=backoff_base)
        data_rows = _parse_ecos_response(raw, lookback_months=lookback)

        if not data_rows:
            print("[data_fetcher] ECOS 응답에 유효한 데이터 없음 — mock 데이터로 fallback")
            result = _make_mock_data(lookback)
        else:
            summary = _build_summary(data_rows)
            result = {
                "last_updated": data_rows[-1]["period"],
                "unit": "지수(2020=100)",
                "is_mock": False,
                "data": data_rows,
                "summary": summary,
            }
            print(
                f"[data_fetcher] 수집 완료: {len(data_rows)}개월, "
                f"최신={summary['latest_month']}, "
                f"MoM={summary['mom_change_pct']:+.1f}%"
            )

    except Exception as exc:
        print(f"[data_fetcher] ECOS API 실패: {exc} — mock 데이터로 fallback")
        result = _make_mock_data(lookback)

    _save_result(result, output_path)
    return result


def _save_result(result: dict, output_path: Path) -> None:
    """결과를 output/semiconductor_export.json에 저장."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[data_fetcher] 저장 완료: {output_path}")


if __name__ == "__main__":
    data = fetch_semiconductor_export()
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
