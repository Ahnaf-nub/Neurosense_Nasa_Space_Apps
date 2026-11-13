"""Linear-trend statistics: OLS t-test with 95% CI and Mann-Kendall with Sen's slope. Pure numpy/math."""
import math
import numpy as np

VARS = {
 "T2M": ("Air temperature", "°C", "The average air temperature 2 m above the ground."),
 "T2M_MAX": ("Daily maximum temperature", "°C", "The hottest temperature reached each day, averaged over the period."),
 "T2M_MIN": ("Daily minimum temperature", "°C", "The coolest temperature each day, usually at night."),
 "PRECTOTCORR": ("Rainfall", "mm/day", "Average daily rainfall, from NASA models corrected with satellite rain data."),
 "RH2M": ("Relative humidity", "%", "How much water vapour the air holds compared with the most it could hold."),
 "WS2M": ("Wind speed", "m/s", "Average wind speed 2 m above the ground."),
 "ALLSKY_SFC_SW_DWN": ("Sunlight at the surface", "kWh/m²/day", "Solar energy reaching the ground, including the effect of clouds."),
 "GWETROOT": ("Root-zone soil wetness", "0 to 1", "How wet the soil is where plant roots reach (0 = dry, 1 = saturated)."),
 "GWETTOP": ("Surface soil wetness", "0 to 1", "How wet the top few centimetres of soil are."),
 "TREECOVER": ("Tree cover", "%", "Share of the ground covered by tree canopy, from MODIS (yearly)."),
}

def _betacf(a, b, x):
    FP = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > FP else FP); h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = d if abs(d) > FP else FP
        c = 1 + aa / c; c = c if abs(c) > FP else FP
        d = 1 / d; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = d if abs(d) > FP else FP
        c = 1 + aa / c; c = c if abs(c) > FP else FP
        d = 1 / d; de = d * c; h *= de
        if abs(de - 1) < 3e-12: break
    return h

def _betai(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2): return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b

def t_p(t, df):          # two-sided p-value of Student's t
    return _betai(df / 2, 0.5, df / (df + t * t))

def t_crit(df, conf=0.95):
    lo, hi = 0.0, 60.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if t_p(mid, df) > 1 - conf: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def mann_kendall(x, y):
    n = len(y); s = 0.0
    for i in range(n - 1): s += np.sign(y[i + 1:] - y[i]).sum()
    _, cnt = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - sum(c * (c - 1) * (2 * c + 5) for c in cnt if c > 1)) / 18
    z = 0.0 if s == 0 or var <= 0 else (s - np.sign(s)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    sen = float(np.median([(y[j] - y[i]) / (x[j] - x[i]) for i in range(n - 1) for j in range(i + 1, n)]))
    return float(s), float(z), p, sen

def stats_annual(var, years, annual, monthly=None):
    x, y = np.asarray(years, float), np.asarray(annual, float); n = len(x)
    if n < 8: raise ValueError("need at least 8 years, have %d" % n)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or len(set(x)) != n:
        raise ValueError("Years must be unique and values finite")
    xm = x.mean(); sxx = ((x - xm) ** 2).sum()
    slope = float(((x - xm) * (y - y.mean())).sum() / sxx); icpt = float(y.mean() - slope * xm)
    res = y - (icpt + slope * x); df = n - 2
    se = math.sqrt((res ** 2).sum() / df / sxx) if sxx > 0 else 0.0
    p_ols = t_p(slope / se, df) if se > 1e-12 else (0.0 if abs(slope) > 1e-12 else 1.0)
    tc = t_crit(df); r2 = 1 - (res ** 2).sum() / (((y - y.mean()) ** 2).sum() or 1)
    s, z, p_mk, sen = mann_kendall(x, y)
    sig = (p_ols < 0.05) + (p_mk < 0.05)
    name, unit, defin = VARS.get(var, (var, "", ""))
    return {"var": var, "name": name, "unit": unit, "definition": defin, "n": n,
            "years": [int(v) for v in x], "annual": [round(float(v), 4) for v in y],
            "trend_line": [round(icpt + slope * float(v), 4) for v in x],
            "slope_decade": round(slope * 10, 4), "ci_decade": [round((slope - tc * se) * 10, 4), round((slope + tc * se) * 10, 4)],
            "p_ols": round(p_ols, 4), "p_mk": round(p_mk, 4), "mk_z": round(z, 3), "sen_decade": round(sen * 10, 4), "r2": round(float(r2), 3),
            "verdict": "significant" if sig == 2 else ("borderline" if sig == 1 else "not significant"),
            "monthly": monthly or []}

def analyse_monthly(var, raw):
    """raw: {'YYYYMM': value}. Uses only complete years; annual means remove the seasonal cycle."""
    by = {}
    for k, v in raw.items():
        if len(k) == 6 and 1 <= int(k[4:]) <= 12 and v > -90: by.setdefault(int(k[:4]), {})[int(k[4:])] = v
    yrs = sorted(y for y, m in by.items() if len(m) == 12)
    if len(yrs) < 8: raise ValueError("not enough complete years")
    ann = [sum(by[y].values()) / 12 for y in yrs]
    mon = [[round(y + (m - .5) / 12, 3), round(by[y][m], 3)] for y in yrs for m in range(1, 13)]
    return stats_annual(var, yrs, ann, mon)