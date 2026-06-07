# AI Analyzer 배포 가이드

## Condition C: GitHub Pages (팀 공유 대시보드)

### 1단계: GitHub 저장소 설정
```bash
# 이 폴더를 GitHub에 푸시
git init
git remote add origin https://github.com/HwangatWork/AI-Analyzer.git
git add .
git commit -m "feat: AI Analyzer initial setup"
git push -u origin main
```

### 2단계: GitHub Pages 활성화
1. GitHub → Settings → Pages
2. Source: GitHub Actions
3. 저장 후 Actions 탭에서 'Deploy AI Analyzer Dashboard' 워크플로우 확인

### 3단계: FRED API Key 등록
1. GitHub → Settings → Secrets → Actions
2. New repository secret: `FRED_API_KEY` = 094e08568d16f0de504b72795cd4b5cc

### 배포 URL
```
https://hwangatwork.github.io/AI-Analyzer/
```
대시보드 자동 배포:
- 매주 월요일 07:00 KST (GitHub Actions 스케줄)
- output/dashboard.html 변경 시 즉시 배포

---

## Condition D: 로컬 자동화 (Windows Task Scheduler)

```powershell
# 관리자 권한으로 실행
.\schedule_weekly.ps1
```

### 알림 구독 (ntfy.sh - 무료)
1. https://ntfy.sh 또는 앱 설치
2. 채널 구독: **ai-analyzer-hwangatwork**
3. 완료/실패 시 자동 푸시 알림 수신

---

## 데이터 신뢰성 현황

| 지표 | 소스 | 신선도 | 신뢰도 | 비고 |
|------|------|--------|--------|------|
| SP500 | FDR | 2일 | 99.0 | 사용자 제공값과 0% 오차 |
| KOSPI | FDR | 2일 | 95.1 | 사용자 제공값과 0% 오차 |
| NASDAQ100 | FDR | 2일 | 99.0 | |
| HY_SPREAD | FRED | 3일 | 93.7 | |
| CNN_FG | alternative.me | 0일 | 51.2 | 오늘 데이터 (극단적공포=12) |
| VIX | yfinance | 2일 | - | |
| MARKET_STRENGTH | CALC:SP500/MA200 | 2일 | 84.3 | 버그 수정: RSI14 복사→MA200 기반 |

### 한국 주식 데이터
- FDR(KRX 직접) + yfinance 크로스 검증
- 두 소스 수익률 차이 <100%p: "검증완료"
- SK하이닉스 +804%, 삼성전자 +450% → **검증완료 (실제 AI붐 수혜)**
