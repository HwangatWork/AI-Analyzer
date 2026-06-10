# -*- coding: utf-8 -*-
"""
Sheets Agent — Google Sheets 자동 업로드 (Looker Studio 데이터 소스)
PM Condition G: CSV → Google Sheets → Looker Studio 파이프라인

인증: Google Service Account JSON (GOOGLE_SA_JSON 환경변수)
      또는 OAuth (gcloud auth application-default login)
대안: gspread 라이브러리 사용
"""
import utf8_setup  # noqa: F401

import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"


def upload_to_sheets() -> dict:
    """
    CSV 파일을 Google Sheets에 업로드.
    환경 변수 GOOGLE_SA_JSON 필요 (Service Account JSON 경로 또는 내용).
    실패 시 로컬 CSV 경로와 Looker Studio 수동 연결 가이드 반환.
    """
    result = {
        "status":     "not_configured",
        "timestamp":  datetime.now().isoformat(),
        "csv_files":  [],
        "sheets_url": None,
        "looker_url": None,
        "guide":      [],
    }

    # 로컬 CSV 파일 목록
    csv_files = [
        OUTPUT_DIR / "indicator_ranking.csv",
        OUTPUT_DIR / "market_signals.csv",
        OUTPUT_DIR / "stock_analysis.csv",
    ]
    result["csv_files"] = [str(f) for f in csv_files if f.exists()]

    # gspread 시도
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_path = os.environ.get("GOOGLE_SA_JSON", "")
        if not sa_path or not Path(sa_path).exists():
            raise FileNotFoundError("GOOGLE_SA_JSON 환경변수 미설정")

        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        client = gspread.authorize(creds)

        # 스프레드시트 생성 또는 열기
        try:
            sh = client.open("AI Analyzer Dashboard")
        except gspread.SpreadsheetNotFound:
            sh = client.create("AI Analyzer Dashboard")
            sh.share(os.environ.get("GOOGLE_SHARE_EMAIL", ""), perm_type="user", role="writer")

        import csv
        for csv_path in csv_files:
            if not csv_path.exists():
                continue
            sheet_name = csv_path.stem.replace("_", " ").title()
            try:
                ws = sh.worksheet(sheet_name)
                ws.clear()
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=sheet_name, rows=200, cols=30)

            with open(csv_path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            ws.update(rows)
            print(f"  업로드 완료: {sheet_name} ({len(rows)-1}행)")

        result["status"]     = "success"
        result["sheets_url"] = sh.url
        result["looker_url"] = "https://lookerstudio.google.com/create?importFromSheets=" + sh.id
        result["guide"] = [
            f"Sheets URL: {sh.url}",
            "Looker Studio → 데이터 추가 → Google Sheets → 'AI Analyzer Dashboard' 선택",
        ]

    except ImportError:
        result["status"] = "gspread_not_installed"
        result["guide"]  = [
            "pip install gspread google-auth 설치 필요",
            "또는 아래 수동 연결 가이드 참조",
        ]
    except FileNotFoundError as e:
        result["status"] = "no_credentials"
        result["guide"]  = [
            "서비스 계정 JSON: .env에 GOOGLE_SA_JSON=/path/to/sa.json 추가",
            "또는 OAuth: gcloud auth application-default login",
        ]
    except Exception as e:
        result["status"] = f"error: {str(e)[:80]}"

    # 항상 수동 연결 가이드 포함
    result["manual_guide"] = {
        "step1": "Google Drive → 새로 만들기 → 파일 업로드 → indicator_ranking.csv",
        "step2": "Looker Studio(lookerstudio.google.com) → 보고서 만들기 → 데이터 추가",
        "step3": "Google Sheets 커넥터 선택 → 업로드한 파일 선택",
        "step4": "차트 추가: 막대 차트(가중치), 표(시그널), 스코어카드(시장 방향)",
        "csv_local_paths": result["csv_files"],
        "github_pages_csv": "https://hwangatwork.github.io/AI-Analyzer/indicator_ranking.csv",
        "looker_from_url": "Looker Studio → 데이터 추가 → CSV 업로드 또는 Web URL 사용 가능",
    }

    return result


def generate_sheets_section(sheets_result: dict) -> str:
    status    = sheets_result.get("status", "")
    guide     = sheets_result.get("manual_guide", {})
    sheets_url = sheets_result.get("sheets_url")
    csv_files = sheets_result.get("csv_files", [])
    gh_csv    = guide.get("github_pages_csv", "")

    status_badge = {
        "success":              ('<span style="color:#22c55e">● 자동 업로드 완료</span>', "#22c55e"),
        "no_credentials":       ('<span style="color:#f59e0b">● 인증 설정 필요</span>', "#f59e0b"),
        "gspread_not_installed":('<span style="color:#f59e0b">● 라이브러리 미설치</span>', "#f59e0b"),
        "not_configured":       ('<span style="color:#64748b">● 수동 연결 모드</span>', "#64748b"),
    }.get(status, (f'<span style="color:#64748b">● {status[:30]}</span>', "#64748b"))

    steps = [
        (guide.get("step1", ""), "Google Drive에 CSV 업로드"),
        (guide.get("step2", ""), "Looker Studio에서 데이터 소스 연결"),
        (guide.get("step3", ""), "Google Sheets 커넥터 선택"),
        (guide.get("step4", ""), "차트 구성 (막대/표/스코어카드)"),
    ]

    steps_html = "".join(f"""
    <div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #1e293b;align-items:flex-start">
      <div style="background:#6366f1;color:#fff;border-radius:50%;width:22px;height:22px;
                  display:flex;align-items:center;justify-content:center;font-size:0.7rem;
                  font-weight:700;flex-shrink:0;margin-top:1px">{i+1}</div>
      <div>
        <div style="font-size:0.8rem;color:#e2e8f0;font-weight:600">{label}</div>
        <div style="font-size:0.72rem;color:#64748b;margin-top:2px">{detail}</div>
      </div>
    </div>""" for i, (detail, label) in enumerate(steps))

    csv_links = "".join(
        f'<a href="{gh_csv.replace("indicator_ranking.csv", Path(f).name)}" '
        f'style="display:block;font-size:0.75rem;color:#60a5fa;padding:3px 0;text-decoration:none">'
        f'↓ {Path(f).name}</a>'
        for f in csv_files
    )

    sheets_link = f'<a href="{sheets_url}" target="_blank" style="color:#22c55e">Google Sheets 열기 →</a>' if sheets_url else ""

    return f"""
<!-- ═══ LOOKER STUDIO SECTION ═══ -->
<section id="looker">
  <h2 class="section-title">Looker Studio 연동</h2>
  <div style="font-size:0.72rem;margin-bottom:14px">{status_badge[0]}</div>

  <div class="grid-2" style="gap:16px">
    <!-- 연결 가이드 -->
    <div class="card">
      <div style="font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:10px">연결 가이드</div>
      {steps_html}
      <div style="margin-top:12px;font-size:0.78rem;font-weight:600;color:#64748b">CSV 다운로드</div>
      <div style="margin-top:4px">
        <a href="{gh_csv}" target="_blank" style="font-size:0.75rem;color:#60a5fa;text-decoration:none">
          ↓ indicator_ranking.csv (GitHub Pages)
        </a><br>
        <a href="{gh_csv.replace('indicator_ranking', 'market_signals')}" target="_blank"
           style="font-size:0.75rem;color:#60a5fa;text-decoration:none">
          ↓ market_signals.csv
        </a><br>
        <a href="{gh_csv.replace('indicator_ranking', 'stock_analysis')}" target="_blank"
           style="font-size:0.75rem;color:#60a5fa;text-decoration:none">
          ↓ stock_analysis.csv
        </a>
      </div>
      {f'<div style="margin-top:10px">{sheets_link}</div>' if sheets_link else ""}
    </div>

    <!-- 서비스 계정 설정 -->
    <div class="card">
      <div style="font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:10px">자동화 설정 (선택)</div>
      <div style="font-size:0.78rem;color:#64748b;line-height:1.8">
        <div style="color:#94a3b8;margin-bottom:6px">Google Service Account 설정 시 매주 자동 업로드</div>
        <code style="background:#0f172a;padding:4px 8px;border-radius:4px;font-size:0.72rem;color:#22c55e;display:block;margin-bottom:6px">
          .env에 추가:<br>GOOGLE_SA_JSON=/path/to/service-account.json<br>GOOGLE_SHARE_EMAIL=your@email.com
        </code>
        <div style="color:#64748b;font-size:0.72rem">
          또는 Looker Studio에서 직접 GitHub Pages CSV URL을 데이터 소스로 연결 가능<br>
          URL: <code style="color:#60a5fa">{gh_csv}</code>
        </div>
      </div>
    </div>
  </div>
</section>"""


if __name__ == "__main__":
    result = upload_to_sheets()
    print("상태:", result["status"])
    if result.get("sheets_url"):
        print("Sheets URL:", result["sheets_url"])
    print("\n수동 가이드:")
    for k, v in result.get("manual_guide", {}).items():
        if isinstance(v, str):
            print(f"  {k}: {v}")
