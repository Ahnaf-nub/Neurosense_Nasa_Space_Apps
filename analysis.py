"""Forecasting + cause attribution. Pure numpy so it is easy to run and test."""
import numpy as np

def _ridge_fit(X, y, lam=2.0):
    mu, sd = X.mean(0), X.std(0); sd[sd < 1e-9] = 1
    Xs = (X - mu) / sd
    w = np.linalg.solve(Xs.T @ Xs + lam * np.eye(X.shape[1]), Xs.T @ (y - y.mean()))
    return lambda Z: ((Z - mu) / sd) @ w + y.mean()

def _lin(x, y):
    s, b = np.polyfit(x, y, 1); return lambda v: s * np.asarray(v, float) + b

def analyse(c_years, cover, p_years, temp, rain, end_year=2035):
    cy = {int(y): v for y, v in zip(c_years, cover) if v == v}
    py = {int(y): (t, r) for y, t, r in zip(p_years, temp, rain)}
    years = sorted(y for y in cy if y in py)
    if len(years) < 8:
        raise ValueError("not enough overlapping years (%d)" % len(years))
    y_arr = np.array(years, float)
    cov = np.array([cy[y] for y in years])
    T = np.array([py[y][0] for y in years]); R = np.array([py[y][1] for y in years])
    tm, ts, rm, rs = T.mean(), T.std() or 1, R.mean(), R.std() or 1
    tz, rz = (T - tm) / ts, (R - rm) / rs

    def feats(yr, tzv, rzv, rzprev):
        return np.column_stack([(np.asarray(yr, float) - 2000) / 10, tzv, rzv, rzprev])
    rprev = np.r_[rz[0], rz[:-1]]
    X = feats(y_arr, tz, rz, rprev)

    mae = naive = None                           # honest hold-out: train on all but the last 3 years
    if len(years) > 10:
        m = _ridge_fit(X[:-3], cov[:-3]); mae = float(np.mean(np.abs(m(X[-3:]) - cov[-3:])))
        naive = float(np.mean(np.abs(cov[-4] - cov[-3:])))   # baseline: repeat the last training year
    model = _ridge_fit(X, cov)

    fy = list(range(max(years) + 1, end_year + 1))
    ft = _lin(y_arr, T)(fy); fr = _lin(y_arr, R)(fy)
    ftz, frz = (ft - tm) / ts, (fr - rm) / rs
    Xf = feats(fy, ftz, frz, np.r_[rz[-1], frz[:-1]])
    decay = np.exp(-np.arange(len(fy)) / 4)
    fc = np.clip(model(Xf) + (cov[-1] - model(X[-1:])[0]) * decay, 0, 100)

    # 80% band: residual bootstrap of the model + allowance that widens with horizon
    rng = np.random.default_rng(42)
    fitted = model(X); resid = cov - fitted; sig = resid.std()
    sims = []
    for _ in range(200):
        mb = _ridge_fit(X, fitted + rng.choice(resid, len(resid)))
        s = mb(Xf) + (cov[-1] - mb(X[-1:])[0]) * decay
        s = s + rng.normal(0, sig, len(fy)) * np.sqrt(np.arange(1, len(fy) + 1)) * 0.35
        sims.append(np.clip(s, 0, 100))
    lo, hi = np.percentile(sims, [10, 90], axis=0)
    lo, hi = np.minimum(lo, fc), np.maximum(hi, fc)

    # cause attribution: is cover LOSS concentrated in hot/dry years more than chance?
    drops = np.maximum(0, -np.diff(cov)); total = drops.sum()
    stressed = (tz > 0.7) | (rz < -0.7)
    def lift_for(st):
        sa = st[1:] | st[:-1]; return drops[sa].sum() / total - sa.mean()
    stressed_any = stressed[1:] | stressed[:-1]
    p = None
    if total < 1.0:
        cause, prob, share = "mixed", 0.5, 0.5
    else:
        share = float(drops[stressed_any].sum() / total)
        lift = lift_for(stressed)
        null = [lift_for(np.roll(stressed, k)) for k in range(1, len(stressed))]   # circular shifts keep trends
        p = float((1 + sum(v >= lift - 1e-12 for v in null)) / (1 + len(null)))
        if lift >= 0.2 and p <= 0.15: cause, prob = "climate", min(0.95, 0.5 + lift)
        elif lift >= 0.05: cause, prob = "mixed", 0.5
        else: cause, prob = "human", min(0.9, 0.6 + (0.05 - lift))
    events = [{"year": years[i + 1], "drop": round(float(drops[i]), 1), "stressed": bool(stressed_any[i])}
              for i in np.argsort(drops)[::-1][:3] if drops[i] >= 0.5]
    r2 = lambda a: [round(float(v), 2) for v in a]
    return {
        "years": years, "cover": r2(cov), "forecast_years": fy, "forecast": r2(fc),
        "forecast_lo": r2(lo), "forecast_hi": r2(hi),
        "cause": cause, "cause_prob": round(float(prob), 2), "cause_p_value": None if p is None else round(p, 3),
        "climate_loss_share": round(share, 2), "holdout_mae_pct": None if mae is None else round(mae, 2),
        "naive_mae_pct": None if naive is None else round(naive, 2),
        "loss_events": events,
        "method": "Ridge on year + NASA POWER temp/rain anomalies; 80% band by residual bootstrap; cause = loss share in hot/dry years vs chance (circular-shift permutation test)",
    }