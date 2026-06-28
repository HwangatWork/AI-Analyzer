# -*- coding: utf-8 -*-
"""
Phase 13-B-4 — `## Peer Review Concerns` 섹션을 13 agent MD에 일괄 추가.

스크립트 한 번 실행으로 완료. 멱등 (이미 있으면 SKIP).
schema: schemas/peer_review_concerns.schema.json
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CONCERNS = {
    "data-agent": {
        "domain": "29 market indicators collection (FDR / FRED / pykrx / CNN F&G)",
        "failure_modes": [
            "zero-fill 시계열을 stationary 로 오판 — Granger 우회 가능성",
            "단일 source 의존으로 cross-validate fallback 실패",
            "최신 row > 7일 stale 데이터 silent 통과"
        ],
        "verification_targets": [
            {
                "file": "data/collection_report_v2.json",
                "key": "is_mock",
                "check": "all False AND last_updated within 7 days"
            },
            {
                "file": "data/raw/<IND>.parquet",
                "key": "value",
                "check": "no zero-fill streak >= 5 in last 30 days"
            }
        ]
    },
    "analysis-agent": {
        "domain": "lag correlation + Granger causality + weight ranking",
        "failure_modes": [
            "non-stationary 데이터에서 Granger 직접 호출 (ADF 가드 미사용)",
            "co-movement 페널티 미적용 + 동행지수 Top3 진입",
            "cross_validate_return 미호출 + confidence 를 all_inds 에 계산"
        ],
        "verification_targets": [
            {
                "file": "output/indicator_ranking.csv",
                "key": "is_differenced",
                "check": "True for non-stationary inputs"
            },
            {
                "file": "output/indicator_ranking.csv",
                "key": "cv_ic_mean",
                "check": "non-null for at least 5 indicators"
            }
        ]
    },
    "evaluator-agent": {
        "domain": "statistical significance + confidence score (p<0.05)",
        "failure_modes": [
            "all_inds 에 confidence 계산 (filter_passed 한정 위반)",
            "ctd_ready boolean stop 무력화 (sys.exit(1) 미적용)",
            "카테고리 다양성 < 3 인데 valid_count >= 5 만족하여 편향"
        ],
        "verification_targets": [
            {
                "file": "output/evaluation_results.json",
                "key": "valid_count",
                "check": ">= 5 AND category_count >= 3"
            },
            {
                "file": "output/evaluation_results.json",
                "key": "extreme_return_flags",
                "check": "all stocks |return| > 200% flagged"
            }
        ]
    },
    "validation-agent": {
        "domain": "methodology checklist (dynamic universe / cross-validation / unit consistency)",
        "failure_modes": [
            "evaluator FAIL 우회해 decision-agent 통과시킴",
            "validation HOLD 가 deploy job if:always() 로 무력화",
            "category gate 등 quality gate skip"
        ],
        "verification_targets": [
            {
                "file": "output/validation_report.json",
                "key": "verdict",
                "check": "APPROVE only if all gates PASS"
            },
            {
                "file": ".github/workflows/deploy-dashboard.yml",
                "key": "deploy.if",
                "check": "needs result success, not always()"
            }
        ]
    },
    "decision-agent": {
        "domain": "BUY/SELL/HOLD + position sizing + confidence tier",
        "failure_modes": [
            "evaluator FAIL 시 HOLD 강제 미적용 (upstream 신호 무시)",
            "confidence_pct downgrade < 30% 미적용",
            "risk_flags 에 UPSTREAM_UNVERIFIED 누락"
        ],
        "verification_targets": [
            {
                "file": "output/decision.json",
                "key": "composite_score",
                "check": "downgraded if evaluator status != PASS"
            },
            {
                "file": "output/decision.json",
                "key": "risk_flags",
                "check": "contains UPSTREAM_UNVERIFIED when evaluator FAIL"
            }
        ]
    },
    "stock-agent": {
        "domain": "S&P500 contribution + KOSPI beneficiary Top5",
        "failure_modes": [
            "zero marcap 종목의 contribution_score 미보정 → 잘못된 Top5",
            "극단수익률 (±200%) 종목에 warn_reason 누락",
            "f12 (KOSPI 수혜) 가 evaluator FAIL 시 전체 차단 (f09 독립성 무시)"
        ],
        "verification_targets": [
            {
                "file": "output/stock_analysis.csv",
                "key": "warn_reason",
                "check": "non-empty for extreme return rows"
            },
            {
                "file": "data/processed/stock_results.json",
                "key": "f09_sp500_contribution_top5",
                "check": "len == 5 regardless of evaluator status"
            }
        ]
    },
    "sector-agent": {
        "domain": "semiconductor / AI / energy sector deep-dive",
        "failure_modes": [
            "텍스트만 산출하고 수치 (avg_return / cycle_signal) 누락",
            "sectors_count < 5 인데 mtime 만으로 완료 위장",
            "data_source 메타데이터 (script / collected_at) 부재로 freshness 미검증"
        ],
        "verification_targets": [
            {
                "file": "agent_memo_sector.json",
                "key": "leader_sectors",
                "check": "len >= 5 AND each has avg_return + cycle_signal"
            },
            {
                "file": "agent_memo_sector.json",
                "key": "data_source.collected_at",
                "check": "within 1 hour"
            }
        ]
    },
    "news-agent": {
        "domain": "news collection (Google RSS + body) + 인과 시황 해설",
        "failure_modes": [
            "RSS 빈 응답이어도 mtime 갱신 → news_report.json 만으로 성공 오판",
            "single-source 지배 (예: Reuters 만) → 인과 사슬 편향",
            "stale article (24h 초과) 를 fresh 로 처리"
        ],
        "verification_targets": [
            {
                "file": "output/news_report.json",
                "key": "articles",
                "check": "len >= 5 AND len(set(a.source)) >= 3"
            },
            {
                "file": "output/news_report.json",
                "key": "articles[].published_at",
                "check": "all within last 24h"
            }
        ]
    },
    "narrative-agent": {
        "domain": "Korean language market narrative + action plan",
        "failure_modes": [
            "템플릿 f-string fallback 으로 LLM 출력 위장 (RC-3c / FIX-G 패턴)",
            "FINAL_REPORT_v2.md prose 80자 미만 또는 entropy 4.0 미만",
            "key_indicators 수치가 final_results.json 과 불일치"
        ],
        "verification_targets": [
            {
                "file": "output/FINAL_REPORT_v2.md",
                "key": "market_summary",
                "check": "length >= 80 AND token entropy >= 4.0"
            },
            {
                "file": "output/narrative_context.json",
                "key": "key_indicators",
                "check": "values match output/final_results.json"
            }
        ]
    },
    "ui-agent": {
        "domain": "dashboard HTML + CSV + GitHub Pages deploy",
        "failure_modes": [
            "validation gate 우회한 stale dashboard 가 Pages 로 배포",
            "build_sha / commit_sha 임베드 누락 → 어떤 커밋이 배포됐는지 불명",
            "concurrency.cancel-in-progress 부재로 push 연타 시 race"
        ],
        "verification_targets": [
            {
                "file": "output/dashboard.html",
                "key": "meta build-sha",
                "check": "non-empty AND matches HEAD commit"
            },
            {
                "file": ".github/workflows/deploy-dashboard.yml",
                "key": "concurrency",
                "check": "group + cancel-in-progress: true"
            }
        ]
    },
    "report-agent": {
        "domain": "Telegram + Notion + GitHub Pages 배포",
        "failure_modes": [
            "HOLD reason payload 누락으로 사용자가 보류 사유 미인지",
            "Telegram dedup cache 60s leak 으로 동일 hash 메시지 차단",
            "Notion 권한 만료 silently swallow"
        ],
        "verification_targets": [
            {
                "file": "output/decision.json",
                "key": "position_note",
                "check": "length >= 20 if action == HOLD"
            },
            {
                "file": "agents/run_telegram_agent.py",
                "key": "_require_hold_reason",
                "check": "exists and called"
            }
        ]
    },
    "audit-agent": {
        "domain": "spec-implementation gap detection (Claude API 위장 패턴 등)",
        "failure_modes": [
            "grep 만으로 의미 검증 → placeholder (AUTO-GENERATED) 통과 위험",
            "단일 run 의 동적 증거만 의존 → cross-session pattern 미감지",
            "OWASP Top 10 Agentic Apps 항목 미적용"
        ],
        "verification_targets": [
            {
                "file": "output/audit_report.json",
                "key": "grep_pass",
                "check": "each grep_pass corresponds to actual implementation, not placeholder"
            },
            {
                "file": "agents/pm_quality.py",
                "key": "QC-29",
                "check": "Level >=8 evidence gate active"
            }
        ]
    },
    "meta-audit-agent": {
        "domain": "PM Agent self-audit (pending_requests vs commits + AI 자기 라벨 감시)",
        "failure_modes": [
            "pending_requests done 항목이 commit_hash 와 미매핑 (영구 위장 가능)",
            "AI 가 PARTIAL_ACCEPT / REBUT 등 자기 라벨 부여 → 감시 누락",
            "DC 정의 변경 (goalposts moving) 미감지"
        ],
        "verification_targets": [
            {
                "file": "pending_requests.json",
                "key": "completed commit_hash",
                "check": "all match git log --grep=<id>"
            },
            {
                "file": "ROADMAP.md",
                "key": "DC 정의 변경",
                "check": "변경 시 별도 commit + 사유 명시"
            }
        ]
    }
}


def main():
    base = REPO / ".claude" / "agents"
    added = []
    skipped = []
    for agent, data in CONCERNS.items():
        md_path = base / f"{agent}.md"
        if not md_path.exists():
            skipped.append((agent, "file not found"))
            continue
        text = md_path.read_text(encoding="utf-8")
        if "## Peer Review Concerns" in text:
            skipped.append((agent, "section already exists"))
            continue
        section = (
            "\n\n## Peer Review Concerns\n"
            "<!-- TF Phase 13-B-4 (2026-06-29). schema: schemas/peer_review_concerns.schema.json -->\n"
            "```json\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        md_path.write_text(text + section, encoding="utf-8")
        added.append(agent)

    print(f"added: {len(added)}/{len(CONCERNS)}")
    for a in added:
        print(f"  + {a}")
    if skipped:
        print(f"skipped: {len(skipped)}")
        for agent, reason in skipped:
            print(f"  - {agent} ({reason})")


if __name__ == "__main__":
    main()
