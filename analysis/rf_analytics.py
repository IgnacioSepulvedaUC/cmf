"""Fixed-income analytics for the CMF curves and bond development tables.

Computes, entirely ex-ante (no live connection), the inputs for a static HTML
report:

  1. Classic return attribution (carry / roll-down / duration / convexity) on a
     constant-maturity 10y zero for each class, from the historical curves.
  2. Market regimes via a Gaussian HMM (nachometrics RegimeModel) on sovereign
     level / slope / monthly change.
  3. A calibrated regime-switching Ornstein-Uhlenbeck (Vasicek) short/level
     model -- the diffusion whose infinitesimal generator is the operator in
     the HJB / bond-valuation equation -- Monte-Carlo simulated to obtain the
     P&L distribution and VaR / CVaR at several horizons.
  4. Cashflows by asset class (bancario / corporativo), realized and projected,
     from the bond development tables (cmf_bonos_flujos_emisiones.xlsx).

All results are dumped to outputs/rf_data.json for hard-coding into the HTML.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "outputs"
OUTDIR.mkdir(exist_ok=True)

# nachometrics (for the HMM RegimeModel).
_np = os.environ.get("NACHOMETRICS_PATH")
if _np:
    sys.path.insert(0, _np)
else:
    for c in HERE.glob("nachometrics_unified_*"):
        if (c / "nachometrics").is_dir():
            sys.path.insert(0, str(c))
            break
from nachometrics.statisticalnacho.nachonetwork.regimes import RegimeModel  # noqa: E402

CURVE_PARQUET = os.environ.get(
    "CURVE_PARQUET",
    "/root/.claude/uploads/9d704e09-1b3a-56e9-b9c5-10597ad000eb/a15596e8-curva.parquet",
)
FLUJOS_XLSX = os.environ.get("FLUJOS_XLSX", str(HERE.parent / "cmf_bonos_flujos_emisiones.xlsx"))

PLAZOS = [90, 180, 360, 720, 1080, 1800, 2520, 3600, 5400, 7200, 9000, 10800]
DPY = 360.0
TENORS = [p / DPY for p in PLAZOS]           # years
BENCH = 10.0                                  # benchmark constant maturity (years)
DT = 1.0 / 12.0
HORIZONS = [1, 3, 6, 12, 60]                  # months
LEVELS = [0.95, 0.99]
SEGMENTS = {
    "Soberano": "Gob CERO Pesos",
    "Bancario": "CORP Bancarios AAA",
    "Corporativo": "CORP AAA",
}
HORA_PRIORITY = {"13:45 (Oficial)": 0, "09:40": 1, "Plazo único": 2}
COLORS = {"Soberano": "sob", "Bancario": "ban", "Corporativo": "corp"}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def monthly_wide(df: pd.DataFrame, curva: str) -> pd.DataFrame:
    """Month-end wide panel of zero yields (decimals) indexed by date, cols=tenor(y)."""
    sub = df[(df["curva"] == curva) & (df["plazo_dias"].isin(PLAZOS))].copy()
    sub = sub.sort_values(["fecha_dt", "plazo_dias", "prio"])
    sub = sub.drop_duplicates(["fecha_dt", "plazo_dias"], keep="first")
    wide = sub.pivot(index="fecha_dt", columns="plazo_dias", values="valor")
    wide = wide.resample("ME").last().dropna() / 100.0
    wide.columns = [c / DPY for c in wide.columns]
    return wide


def interp_row(row: pd.Series, x_new: float) -> float:
    xs = np.array(row.index, dtype=float)
    ys = row.to_numpy(dtype=float)
    return float(np.interp(x_new, xs, ys))


# --------------------------------------------------------------------------- #
# 1. Return attribution (constant-maturity 10y zero)
# --------------------------------------------------------------------------- #
def attribution(wide: pd.DataFrame) -> pd.DataFrame:
    """Monthly log-return decomposition of a constant-maturity BENCH-year zero.

    r = m*y_t(m) - (m-dt)*y_{t+1}(m-dt)
      = carry + rolldown + duration + convexity + residual
    """
    m, tau = BENCH, BENCH - DT
    rows = []
    idx = wide.index
    for t in range(len(idx) - 1):
        r0, r1 = wide.iloc[t], wide.iloc[t + 1]
        y_m = interp_row(r0, m)
        y_roll = interp_row(r0, tau)          # same curve, shorter tenor
        y_next = interp_row(r1, tau)          # next curve at aged tenor
        dy = y_next - y_roll
        carry = y_m * DT
        rolldown = tau * (y_m - y_roll)
        duration = -tau * dy
        convexity = 0.5 * tau * tau * dy * dy
        total = m * y_m - tau * y_next
        residual = total - (carry + rolldown + duration + convexity)
        rows.append(
            dict(date=idx[t + 1], carry=carry, rolldown=rolldown, duration=duration,
                 convexity=convexity, residual=residual, total=total, dy=dy)
        )
    return pd.DataFrame(rows).set_index("date")


# --------------------------------------------------------------------------- #
# 2. HMM regimes
# --------------------------------------------------------------------------- #
def regime_features(sov: pd.DataFrame) -> pd.DataFrame:
    level = sov[BENCH]
    slope = sov[TENORS[-1]] - sov[TENORS[0]]      # 30y - 3m
    chg = level.diff()
    feat = pd.DataFrame({"level": level, "slope": slope, "chg": chg}).dropna()
    feat.index.name = "date"
    return feat


def fit_regimes(feat: pd.DataFrame, n_states: int = 3):
    # standardize for a well-conditioned Gaussian mixture / HMM
    z = (feat - feat.mean()) / feat.std(ddof=0)
    res = RegimeModel(z, n_states=n_states, covariance_type="full", seed=0).fit()
    states = res.states
    # order regimes by average level (low -> high yield) for stable labels
    order = feat.groupby(states.values)["level"].mean().sort_values().index.tolist()
    remap = {old: new for new, old in enumerate(order)}
    states_ord = states.map(remap)
    smoothed = res.smoothed_probabilities.iloc[:, order].copy()
    smoothed.columns = [f"regime_{i}" for i in range(n_states)]
    trans = res.transition_matrix.to_numpy()[np.ix_(order, order)]
    dur = np.array(res.expected_duration)[order]
    means = feat.groupby(states.values).mean().loc[order].reset_index(drop=True)
    counts = pd.Series(states_ord).value_counts().sort_index()
    return states_ord, smoothed, trans, dur, means, counts


# --------------------------------------------------------------------------- #
# 3. Regime-switching OU (Vasicek) calibration + Monte-Carlo VaR/CVaR
# --------------------------------------------------------------------------- #
def calibrate_ou(level: pd.Series, states: pd.Series):
    """Per-regime OU: dr = kappa*(theta_k - r)dt + sigma_k dW (monthly dt)."""
    lv = level.reindex(states.index)
    dlv = lv.diff().dropna()
    st = states.reindex(dlv.index)
    # global mean-reversion from AR(1) on the level
    x0 = lv.shift(1).dropna()
    x1 = lv.reindex(x0.index)
    b = np.polyfit(x0.values, x1.values, 1)[0]
    b = min(max(b, 0.80), 0.999)
    kappa = -np.log(b) / DT
    theta = {}
    sigma = {}
    for k in sorted(states.unique()):
        theta[k] = float(lv[states == k].mean())
        s = dlv[st == k]
        sigma[k] = float(s.std(ddof=1) / np.sqrt(DT)) if len(s) > 2 else float(dlv.std(ddof=1) / np.sqrt(DT))
    return kappa, theta, sigma


def simulate(level0, regime0, kappa, theta, sigma, trans, months, n_paths, seed=7):
    rng = np.random.default_rng(seed)
    n_states = trans.shape[0]
    theta_arr = np.array([theta[k] for k in range(n_states)])
    sigma_arr = np.array([sigma[k] for k in range(n_states)])
    cdf = np.cumsum(trans, axis=1)
    r = np.full(n_paths, level0, dtype=float)
    reg = np.full(n_paths, regime0, dtype=int)
    snap = {}
    for month in range(1, months + 1):
        u = rng.random(n_paths)
        reg = (u[:, None] > cdf[reg]).sum(axis=1)
        reg = np.clip(reg, 0, n_states - 1)
        th = theta_arr[reg]
        sg = sigma_arr[reg]
        z = rng.standard_normal(n_paths)
        r = r + kappa * (th - r) * DT + sg * np.sqrt(DT) * z
        if month in HORIZONS:
            snap[month] = r.copy()
    return snap


def var_cvar(pnl: np.ndarray, level: float):
    loss = -pnl
    v = float(np.quantile(loss, level))
    c = float(loss[loss >= v].mean()) if np.any(loss >= v) else v
    return v, c


def risk_block(sov_level, sov_states, class_yields, kappa, theta, sigma, trans):
    """Simulate the sovereign level factor, map to each class, compute VaR/CVaR."""
    level0 = float(sov_level.iloc[-1])
    regime0 = int(sov_states.iloc[-1])
    N = 60000
    snap = simulate(level0, regime0, kappa, theta, sigma, trans, max(HORIZONS), N, seed=7)

    # class sensitivity to the sovereign factor (beta) + idiosyncratic vol
    dsov = sov_level.diff()
    betas, idio = {}, {}
    for seg, y in class_yields.items():
        dy = y[BENCH].diff()
        common = pd.concat([dsov, dy], axis=1).dropna()
        common.columns = ["s", "c"]
        if seg == "Soberano" or len(common) < 12:
            betas[seg], idio[seg] = 1.0, 0.0
        else:
            beta = float(np.polyfit(common["s"], common["c"], 1)[0])
            resid = common["c"] - beta * common["s"]
            betas[seg] = beta
            idio[seg] = float(resid.std(ddof=1))   # monthly idio vol of Δy

    D, C = BENCH, BENCH * BENCH                     # constant-maturity duration/convexity
    rng = np.random.default_rng(11)
    out = {"per_class": {}, "portfolio": {}, "betas": {k: round(v, 3) for k, v in betas.items()},
           "dist": {}}
    class_y0 = {seg: float(y[BENCH].iloc[-1]) for seg, y in class_yields.items()}

    for H in HORIZONS:
        dsov_H = snap[H] - level0
        pnl_classes = {}
        for seg in SEGMENTS:
            idio_shock = rng.standard_normal(N) * idio[seg] * np.sqrt(H) if idio[seg] > 0 else 0.0
            dy = betas[seg] * dsov_H + idio_shock
            carry = class_y0[seg] * (H * DT)
            pnl = 100.0 * (carry - D * dy + 0.5 * C * dy * dy)   # per 100 notional
            pnl_classes[seg] = pnl
        port = np.mean(np.column_stack([pnl_classes[s] for s in SEGMENTS]), axis=1)

        for seg in SEGMENTS:
            d = out["per_class"].setdefault(seg, {})
            for lvl in LEVELS:
                v, cv = var_cvar(pnl_classes[seg], lvl)
                d[f"{H}m_{int(lvl*100)}"] = {"var": round(v, 3), "cvar": round(cv, 3)}
        pd_ = out["portfolio"]
        for lvl in LEVELS:
            v, cv = var_cvar(port, lvl)
            pd_[f"{H}m_{int(lvl*100)}"] = {"var": round(v, 3), "cvar": round(cv, 3),
                                           "mean": round(float(port.mean()), 3)}
        # keep a downsampled histogram of the 12m portfolio loss for the chart
        if H == 12:
            loss = -port
            hist, edges = np.histogram(loss, bins=48)
            out["dist"] = {"counts": hist.tolist(),
                           "edges": [round(float(e), 3) for e in edges],
                           "var95": round(var_cvar(port, 0.95)[0], 3),
                           "var99": round(var_cvar(port, 0.99)[0], 3),
                           "cvar95": round(var_cvar(port, 0.95)[1], 3),
                           "cvar99": round(var_cvar(port, 0.99)[1], 3)}
    return out


# --------------------------------------------------------------------------- #
# 4. Cashflows by class (realized + projected)
# --------------------------------------------------------------------------- #
def _snap(x: float, ceiling: float) -> float:
    """Correct power-of-ten scale errors: divide by 10 until below a plausible ceiling.

    The source development table contains decimal/scale glitches (single coupons of
    up to 26 trillion CLP against ~1 bn neighbours). ~0.7% of flows carry >80% of the
    naive total. Dividing each implausible flow back into the plausible band removes
    the artefacts while preserving genuinely large payments.
    """
    x = float(x)
    while x > ceiling and x > 0:
        x /= 10.0
    return x


CEIL_INT = 15e9    # max plausible single coupon (CLP)
CEIL_AMO = 400e9   # max plausible single amortization (CLP)


def cashflows():
    fl = pd.read_excel(FLUJOS_XLSX, sheet_name="FLUJOS")
    em = pd.read_excel(FLUJOS_XLSX, sheet_name="EMISIONES")
    fl["fecha_flujo"] = pd.to_datetime(fl["fecha_flujo"])
    fl["fecha_vencimiento"] = pd.to_datetime(fl["fecha_vencimiento"])
    fl["interes"] = pd.to_numeric(fl["interes_pagado_clp"], errors="coerce").fillna(0.0).map(
        lambda v: _snap(v, CEIL_INT))
    fl["amort"] = pd.to_numeric(fl["amortizacion_pagada_clp"], errors="coerce").fillna(0.0).map(
        lambda v: _snap(v, CEIL_AMO))
    cutoff = pd.Timestamp("2026-06-01")
    B = 1e9  # report in miles de millones CLP (billions)

    # -- realized: by class, by year --
    past = fl[fl["fecha_flujo"] < cutoff].copy()
    past["year"] = past["fecha_flujo"].dt.year
    realized = (past.groupby(["fuente", "year"])[["interes", "amort"]].sum() / B).reset_index()

    # -- projected: roll each outstanding series forward (constant coupon + bullet) --
    em["monto"] = pd.to_numeric(em["monto_colocado_periodo_clp"], errors="coerce").fillna(0.0)
    principal = em.groupby("nro_inscripcion")["monto"].sum()   # placed amount ~ bullet principal

    proj_rows = []
    win_lo = pd.Timestamp("2025-06-01")
    for (fuente, nro), g in fl.groupby(["fuente", "nro_inscripcion"]):
        mat = g["fecha_vencimiento"].max()
        if pd.isna(mat) or mat < cutoff:
            continue
        recent = g[(g["fecha_flujo"] >= win_lo) & (g["fecha_flujo"] < cutoff)]
        ann_int = float(recent["interes"].sum())     # trailing-12m interest
        if ann_int <= 0:
            ann_int = float(g["interes"].tail(2).sum())
        prin = float(principal.get(nro, np.nan))
        if not np.isfinite(prin) or prin <= 0:
            prin = float(g["amort"].sum())            # fallback: total amortized to date
        start_year = cutoff.year
        end_year = int(mat.year)
        for y in range(start_year, end_year + 1):
            frac = (7.0 / 12.0) if y == start_year else 1.0   # partial first year
            proj_rows.append({"fuente": fuente, "year": y,
                              "interes": ann_int * frac if y < end_year else ann_int * frac * 0.5,
                              "amort": prin if y == end_year else 0.0})
    proj = pd.DataFrame(proj_rows)
    projected = (proj.groupby(["fuente", "year"])[["interes", "amort"]].sum() / B).reset_index()

    def to_series(dfin, key):
        years = list(range(2015, 2036))
        out = {}
        for fuente in ["bancario", "corporativo"]:
            sub = dfin[dfin["fuente"] == fuente].set_index("year")
            out[fuente] = [round(float(sub[key].get(y, 0.0)), 2) for y in years]
        return years, out

    years, real_int = to_series(realized, "interes")
    _, real_amo = to_series(realized, "amort")
    _, proj_int = to_series(projected, "interes")
    _, proj_amo = to_series(projected, "amort")
    return {
        "years": years,
        "cutoff_year": 2026,
        "realized": {"interes": real_int, "amort": real_amo},
        "projected": {"interes": proj_int, "amort": proj_amo},
        "unit": "miles de millones CLP",
        "note": "Montos con corrección de errores de escala (potencias de 10) en la fuente. "
                "Proyección por tabla de desarrollo: cupón constante (últimos 12m) hasta "
                "vencimiento + principal bullet a vencimiento.",
    }


# --------------------------------------------------------------------------- #
def main():
    df = pd.read_parquet(CURVE_PARQUET)
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y")
    df["prio"] = df["hora"].map(HORA_PRIORITY).fillna(9)
    wides = {seg: monthly_wide(df, cv) for seg, cv in SEGMENTS.items()}

    # 1. attribution
    attr = {seg: attribution(w) for seg, w in wides.items()}
    attr_out = {}
    for seg, a in attr.items():
        cum = a[["carry", "rolldown", "duration", "convexity", "residual"]].cumsum() * 100
        totals = (a[["carry", "rolldown", "duration", "convexity", "residual"]].sum() * 100)
        attr_out[seg] = {
            "dates": [d.strftime("%Y-%m") for d in a.index],
            "cum": {c: [round(float(x), 3) for x in cum[c]] for c in cum.columns},
            "totals": {c: round(float(totals[c]), 2) for c in totals.index},
            "total_return": round(float(a["total"].sum() * 100), 2),
        }

    # 2. regimes (sovereign)
    sov = wides["Soberano"]
    feat = regime_features(sov)
    states, smoothed, trans, dur, means, counts = fit_regimes(feat, 3)
    labels = ["Bajo/estable", "Intermedio", "Alto/estrés"]
    regimes_out = {
        "dates": [d.strftime("%Y-%m") for d in feat.index],
        "level": [round(float(x) * 100, 3) for x in feat["level"]],
        "slope": [round(float(x) * 100, 3) for x in feat["slope"]],
        "states": [int(s) for s in states],
        "labels": labels,
        "smoothed": {f"regime_{i}": [round(float(x), 4) for x in smoothed[f"regime_{i}"]]
                     for i in range(3)},
        "transition": [[round(float(x), 3) for x in row] for row in trans],
        "expected_duration": [round(float(x), 1) for x in dur],
        "means": {"level": [round(float(x) * 100, 2) for x in means["level"]],
                  "slope": [round(float(x) * 100, 2) for x in means["slope"]],
                  "chg": [round(float(x) * 100, 3) for x in means["chg"]]},
        "counts": [int(counts.get(i, 0)) for i in range(3)],
    }

    # 3. risk (calibrated regime-switching OU + Monte Carlo)
    kappa, theta, sigma = calibrate_ou(feat["level"], states)
    risk = risk_block(feat["level"], states, wides, kappa, theta, sigma, trans)
    risk["calibration"] = {
        "kappa": round(float(kappa), 3),
        "theta_pct": {int(k): round(v * 100, 2) for k, v in theta.items()},
        "sigma_pct": {int(k): round(v * 100, 2) for k, v in sigma.items()},
        "level0_pct": round(float(feat["level"].iloc[-1]) * 100, 2),
        "regime0": int(states.iloc[-1]),
        "n_paths": 60000,
        "horizons_m": HORIZONS,
    }

    # 4. cashflows
    cf = cashflows()

    data = {
        "meta": {
            "generated": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "bench_tenor_y": BENCH,
            "sample": [regimes_out["dates"][0], regimes_out["dates"][-1]],
            "segments": {seg: SEGMENTS[seg] for seg in SEGMENTS},
            "colors": COLORS,
        },
        "attribution": attr_out,
        "regimes": regimes_out,
        "risk": risk,
        "cashflows": cf,
    }
    (OUTDIR / "rf_data.json").write_text(json.dumps(data, ensure_ascii=False))
    print("=== attribution totals (pp, 10y CM zero, full sample) ===")
    for seg, a in attr_out.items():
        print(f"  {seg:12s} total={a['total_return']:+7.2f}  " +
              "  ".join(f"{k}={v:+.2f}" for k, v in a["totals"].items()))
    print("\n=== regimes ===")
    print("  counts", regimes_out["counts"], "labels", labels)
    print("  exp duration (m)", regimes_out["expected_duration"])
    print("  means level% ", regimes_out["means"]["level"], " slope% ", regimes_out["means"]["slope"])
    print("  transition", regimes_out["transition"])
    print("\n=== OU calibration ===  kappa", risk["calibration"]["kappa"],
          "theta%", risk["calibration"]["theta_pct"], "sigma%", risk["calibration"]["sigma_pct"])
    print("\n=== portfolio VaR/CVaR (per 100 notional) ===")
    for H in HORIZONS:
        p = risk["portfolio"][f"{H}m_95"]; q = risk["portfolio"][f"{H}m_99"]
        print(f"  {H:>3}m  mean={p['mean']:+6.2f}  VaR95={p['var']:6.2f} CVaR95={p['cvar']:6.2f}"
              f"  VaR99={q['var']:6.2f} CVaR99={q['cvar']:6.2f}")
    print("\n=== cashflows (miles de millones CLP) ===")
    yy = cf["years"]; i26 = yy.index(2026)
    for f in ["bancario", "corporativo"]:
        ri = sum(cf["realized"]["interes"][f][:i26 + 1]) + sum(cf["realized"]["amort"][f][:i26 + 1])
        pj = sum(cf["projected"]["interes"][f][i26:]) + sum(cf["projected"]["amort"][f][i26:])
        print(f"  {f:12s} realizado(int+amort)≈{ri:8.1f}   proyectado(int+amort)≈{pj:8.1f}")
    print("\nWrote", OUTDIR / "rf_data.json")


if __name__ == "__main__":
    main()
