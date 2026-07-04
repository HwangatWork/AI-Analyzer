"""Stage Engine v3.0 - Phase 0 Smoke Test
데이터: 2026-07-02~03 세션 실측 확정치 (스크린샷/검색 검증분만 사용)
결측 처리: 가용 차원만으로 마할라노비스 거리 계산 + Confidence에 반영
"""
import numpy as np

# ── 특징: [pos_low(저점대비배수), pos_high(고점대비), per_t(트레일링), gap(목표가괴리), rsi]
# None = 미확보(결측)
STOCKS = {
    #                     pos_low  pos_high   per     gap     rsi    실측라벨
    "지엔씨에너지":      [0.515,  -0.405,   None,   None,   63.9],  # 0 (0->1 경계)
    "오이솔루션":        [1.518,  -0.588,   None,   None,   26.1],  # 4
    "대한전선":          [1.232,  -0.567,   None,   None,   34.1],  # 4
    "LS":                [1.320,  -0.381,   None,   None,   38.4],  # 4
    "심텍":              [4.302,  -0.214,   None,   None,   47.9],  # 2 (후반)
    "삼화콘덴서":        [3.300,  -0.394,   None,   None,   42.4],  # 4 (3->4 진행, 라벨 4)
    "가온전선":          [8.494,  -0.214,   148.2,  None,   None],  # 3
    "SK하이닉스":        [8.878,  -0.190,   7.0,    0.62,   None],  # 2 (연장형)
    "삼성전기":          [None,   None,     None,  -0.02,   None],  # 3 (목표가 상회)
    "대덕전자":          [None,   -0.051,   22.0,  -0.149,  None],  # 3
    "Nvidia":            [None,   -0.30,    None,   0.50,   None],  # 2
    "GE_Vernova":        [None,   -0.037,   63.0,   0.11,   None],  # 3
    "ASML":              [None,   -0.078,   64.7,  -0.052,  None],  # 3
    "TokyoElectron":     [None,   None,     None,  -0.167,  None],  # 3
}
LABELS = {"지엔씨에너지":0,"오이솔루션":4,"대한전선":4,"LS":4,"심텍":2,"삼화콘덴서":4,
          "가온전선":3,"SK하이닉스":2,"삼성전기":3,"대덕전자":3,"Nvidia":2,
          "GE_Vernova":3,"ASML":3,"TokyoElectron":3}

# ── 단계별 전형 프로파일 μ (v3.0 설계값) & 표준편차 σ (허용 폭)
#           pos_low  pos_high  per    gap    rsi
MU = {
    0: [0.35,  -0.35,   22,   0.55,  55],
    1: [1.00,  -0.15,   35,   0.35,  68],
    2: [3.20,  -0.15,   45,   0.20,  65],
    3: [6.50,  -0.10,  110,  -0.05,  60],
    4: [1.60,  -0.52,   60,   0.05,  33],
}
SIG = {
    0: [0.30,  0.15,   15,   0.20,  10],
    1: [0.40,  0.10,   15,   0.15,   8],
    2: [1.60,  0.12,   25,   0.15,  12],
    3: [3.00,  0.10,   50,   0.12,  12],
    4: [0.80,  0.12,   40,   0.15,   8],
}

def classify(x):
    logps = {}
    n_avail = sum(v is not None for v in x)
    for k in MU:
        d2, dims = 0.0, 0
        for i, v in enumerate(x):
            if v is None: continue
            d2 += ((v - MU[k][i]) / SIG[k][i]) ** 2
            dims += 1
        logps[k] = -d2 / 2
    m = max(logps.values())
    ps = {k: np.exp(v - m) for k, v in logps.items()}
    z = sum(ps.values())
    P = {k: ps[k] / z for k in ps}
    # Confidence = 데이터충족률 x 판별선명도
    coverage = n_avail / 5
    ent = -sum(p * np.log(p + 1e-12) for p in P.values()) / np.log(5)
    conf = coverage * (1 - ent)
    return P, conf

print(f"{'종목':<14}{'P0':>6}{'P1':>6}{'P2':>6}{'P3':>6}{'P4':>6} | 판정 실측 일치  Conf")
print("-" * 78)
hit, results = 0, []
for name, x in STOCKS.items():
    P, conf = classify(x)
    pred = max(P, key=P.get)
    ok = pred == LABELS[name]
    hit += ok
    results.append((name, conf, ok))
    print(f"{name:<14}" + "".join(f"{P[k]:>6.2f}" for k in range(5)) +
          f" |  S{pred}   S{LABELS[name]}   {'O' if ok else 'X'}   {conf:.2f}")

n = len(STOCKS)
print("-" * 78)
print(f"재현율: {hit}/{n} ({hit/n*100:.0f}%)  | 합격선: 재현 >= 81% (13/16 스케일 -> {int(np.ceil(n*0.8125))}/{n})")
# Confidence 캘리브레이션 미니 체크 (H5 예비)
confs_ok  = [c for _, c, o in results if o]
confs_bad = [c for _, c, o in results if not o]
if confs_bad:
    print(f"H5 예비: 정답판정 평균 Conf {np.mean(confs_ok):.2f} vs 오답판정 평균 Conf {np.mean(confs_bad):.2f}"
          f" -> {'PASS(오답에서 Conf 낮음)' if np.mean(confs_bad) < np.mean(confs_ok) else 'FAIL'}")
else:
    print("H5 예비: 오답 표본 없음 - 측정 불가")
